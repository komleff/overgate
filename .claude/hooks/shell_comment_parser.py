#!/usr/bin/env python3
"""Ограниченный stateful shell-парсер для публикаций PR-комментариев.

Парсер не исполняет shell и не пытается покрыть всю грамматику Bash. За один
лексический проход он переносит состояние кавычек и substitutions между
строками, признаёт heredoc только в активном shell-контексте и делит top-level
последовательность на команды. Всё вне доказанного подмножества помечается как
неоднозначное: hard gate блокирует, информер пропускает только такой вызов.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
import importlib.util
import os
import re
import sys
import time

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_sibling(name: str):
    """Загрузить соседний модуль пакета обработчиков по явному пути файла.

    Каталог обработчиков в ``sys.path`` намеренно НЕ добавляется: одноимённый
    файл рядом подменил бы модуль стандартной библиотеки, а подменённый предикат
    отключается молча — с кодом «пропустить». Отказ загрузки поднимается наружу
    и превращается в блокировку вызывающим гейтом.
    """

    path = os.path.join(_MODULE_DIR, name + ".py")
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None):
        try:
            if os.path.samefile(existing.__file__, path):
                return existing
        except OSError:
            pass
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не найден модуль пакета обработчиков: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shell_grammar = _load_sibling("shell_grammar")
COMMENT_START_METACHARACTERS = shell_grammar.COMMENT_START_METACHARACTERS
is_comment_start = shell_grammar.is_comment_start
_EXTGLOB_OPENERS = shell_grammar._EXTGLOB_OPENERS

# Граница для открывающих групп ``(`` и ``{``. Это ДРУГОЙ вопрос, чем «где
# начинается комментарий»: помимо метасимволов слово начинается и после фигурных
# скобок, потому что в bash ``}`` завершает составную команду ``{ list; }``.
# Набор выводится из единого правила добавлением этих двух символов, а не пишется
# третьей копией: любое расширение единого набора автоматически доезжает сюда.
_GROUP_BOUNDARY_CHARACTERS = frozenset(COMMENT_START_METACHARACTERS | {"{", "}"})


@dataclass
class _Heredoc:
    operator_start: int
    delimiter: str
    quote_style: str | None
    strip_tabs: bool
    body_start: int = 0
    body_end: int = 0
    end: int = 0
    body: str = ""


@dataclass(frozen=True)
class _Redirection:
    operator_start: int
    operator_end: int
    designator_start: int | None = None
    designator_end: int | None = None


@dataclass
class _Command:
    start: int
    end: int = 0
    separator: str = "sequence"
    heredocs: list[_Heredoc] = field(default_factory=list)
    redirections: list[_Redirection] = field(default_factory=list)
    execution_boundaries: list[int] = field(default_factory=list)
    ambiguous: bool = False


@dataclass(frozen=True)
class _Word:
    start: int
    end: int
    value: str | None
    literal_prefix: str
    may_split: bool


@dataclass(frozen=True)
class _Execution:
    state: str
    index: int | None = None
    payload: _Word | None = None
    carrier: _Word | None = None


@dataclass(frozen=True)
class _GhValueOption:
    """Один value-taking option ``gh pr comment`` и следующий argv-index."""

    canonical: str
    value: _Word | None
    next_position: int


@dataclass(frozen=True)
class Publication:
    """Один реальный top-level кандидат ``gh pr comment``."""

    start: int
    end: int
    command_start: int
    command_end: int
    body: str | None
    body_kind: str
    ambiguous: bool
    pr_number: str | None = None


@dataclass(frozen=True)
class ShellAnalysis:
    publications: tuple[Publication, ...]
    global_ambiguous: bool


class _LexError(Exception):
    """Синтаксис вышел за доказуемое подмножество."""


class ShellParseLimitExceeded(Exception):
    """Разбор не уложился в отведённый предел.

    Вердикта «команда инертна» в этом случае НЕ существует: разбор не закончен,
    значит доказательства нет. Вызывающий обязан трактовать исключение как
    блокировку, а не как разрешение.
    """


# Предел вложенности рекурсивного разбора подстановок и shell-payload'ов.
# Стоимость разбора растёт экспоненциально по глубине: тело подстановки
# разбирается заново на каждом уровне, и вместе с ним — все вложенные в него
# уровни. Замер на гейте публикации (2026-08-12, macOS): глубина 16 — 0,61 с,
# 18 — 2,43 с, 19 — 4,87 с, 21 — 19,4 с при длине команды 111 символов.
# Восьми уровней хватает любой рабочей записи с запасом (реальные формы —
# `bash -c "…"`, `$(cat <<'EOF' … EOF)` — не выходят за 2-3), а всё, что глубже,
# доказательству не поддаётся и обязано блокироваться.
DEFAULT_MAX_SUBSTITUTION_DEPTH = 8

# Как часто лексер сверяется с часами: раз в столько шагов основного цикла.
# Ежешаговая сверка заметно дороже самого шага, а раз в 4096 символов даёт
# погрешность в доли миллисекунды на команде любого разумного размера.
_TIME_CHECK_STRIDE = 4096


@dataclass
class _ParseBudget:
    """Отведённые разбору ресурсы: абсолютный дедлайн и предел вложенности.

    Один и тот же дедлайн покрывает ВЕСЬ разбор — лексинг, обход команд,
    вложенные публикации, запасной вердикт и дедупликацию. Каждая фаза сверяется
    с ним на своих итерациях: незавершённая фаза не доказывает инертность входа,
    поэтому истечение предела на любой из них — `ShellParseLimitExceeded`.
    """

    deadline: float | None
    max_depth: int
    depth: int = 0
    _steps_since_time_check: int = 0

    def check_time(self) -> None:
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise ShellParseLimitExceeded(
                "разбор команды не уложился в предел времени"
            )

    def checkpoint(self) -> None:
        """Строобированная сверка с дедлайном для длинных пофазных циклов.

        Как и в лексере, часы опрашиваются не на каждой итерации, а раз в
        `_TIME_CHECK_STRIDE`: сама сверка дороже одной итерации, а погрешность
        на разумном входе — доли миллисекунды.
        """
        self._steps_since_time_check += 1
        if self._steps_since_time_check >= _TIME_CHECK_STRIDE:
            self._steps_since_time_check = 0
            self.check_time()

    def descend(self) -> "_ParseBudget":
        """Спуститься на уровень вложенности, проверив оба предела."""
        self.check_time()
        if self.depth + 1 > self.max_depth:
            raise ShellParseLimitExceeded(
                "разбор команды превысил предел вложенности "
                f"({self.max_depth} уровней)"
            )
        return _ParseBudget(self.deadline, self.max_depth, self.depth + 1)


# Пределы по умолчанию отсутствуют: разбор ведёт себя ровно как раньше, пока
# вызывающий не запросил их явно. Так информер петли ревью (fail-open по своему
# классу риска) не меняет поведения, а блокирующие гейты запрашивают пределы сами.
_UNLIMITED_BUDGET = _ParseBudget(deadline=None, max_depth=2 ** 30)


_CONTROL_WORDS = {
    "if", "then", "elif", "else", "fi",
    "for", "while", "until", "do", "done",
    "case", "in", "esac", "select", "function",
}

_CONTROL_OPENERS = {
    "if": "fi",
    "for": "done",
    "while": "done",
    "until": "done",
    "case": "esac",
    "select": "done",
}
_CONTROL_CLOSERS = {closer for closer in _CONTROL_OPENERS.values()}

_EXECUTION_CONTROL_PREFIXES = {
    "!", "if", "then", "elif", "else", "while", "until", "do",
}

_SHELL_EXECUTION_WRAPPERS = {
    "bash", "dash", "ksh", "mksh", "sh", "zsh",
}

# Команды из этого узкого списка доказанно трактуют следующие argv как данные,
# а не как исполняемую команду. Для остальных неизвестных carriers действует
# fail-closed анализ literal payload'ов: безопаснее лишняя блокировка кандидата,
# чем исчезнувшая публикация. Список намеренно позитивный и минимальный.
_PROVEN_DATA_COMMANDS = {"echo", "egrep", "fgrep", "grep", "printf", "rg"}

_GH_REPO_OPTION_LEXEME = (
    r"(?:--repo(?:=\S+|\s+\S+)|-R(?:=?\S+|\s+\S+))"
)
_LITERAL_PUBLICATION_LEXEME = re.compile(
    r"(?<![A-Za-z0-9_])(?i:gh(?:\.exe)?)\s+"
    rf"(?:{_GH_REPO_OPTION_LEXEME}\s+)*pr\s+"
    rf"(?:{_GH_REPO_OPTION_LEXEME}\s+)*comment\b"
)

# Буквы вызова публикации в порядке следования. Используются НЕ как образец, а
# как необходимое условие: см. ``_may_carry_publication``.
_PUBLICATION_LETTER_SEQUENCE = "ghprcomment"

# Символы, с которых начинается раскрытие. Раскрытие умеет ВСТАВЛЯТЬ текст,
# поэтому при них необходимое условие ниже неприменимо.
_EXPANSION_CHARACTERS = ("$", "`")


def _may_carry_publication(value: str) -> bool:
    """Может ли литеральный текст ещё обернуться вызовом публикации.

    Позитивный образец ``gh … pr … comment`` неустойчив к кавычкам: в тексте,
    который исполнит ЕЩЁ ОДНА оболочка, кавычки стоят где угодно, совпадения с
    образцом нет, а вызов остаётся. Умолчание «образец не совпал — пропускаем»
    и есть тот пропуск, который здесь закрывается: разбор обязан запускаться,
    пока инертность не доказана.

    Доказательство инертности строится не на образце, а на необходимом условии,
    устойчивом к любому дальнейшему снятию кавычек. Значение слова уже
    литеральное (раскрытия делают слово непрозрачным и сюда не доходят), а
    снятие кавычек умеет только УДАЛЯТЬ символы — значит итог является
    подпоследовательностью исходного текста. Если в тексте нет даже
    подпоследовательности букв ``ghprcomment``, вызова публикации в нём не
    появится ни при какой расстановке кавычек, и текст доказанно инертен.

    Раскрытия (``$``, обратная кавычка) умеют вставлять текст, поэтому при них
    условие не проверяется и разбор идёт всегда — fail-closed.
    """

    if any(character in value for character in _EXPANSION_CHARACTERS):
        return True
    lowered = value.lower()
    position = 0
    for letter in _PUBLICATION_LETTER_SEQUENCE:
        position = lowered.find(letter, position)
        if position < 0:
            return False
        position += 1
    return True


_EXECUTION_EXACT = "exact"
_EXECUTION_NO_EXEC = "no_exec"
_EXECUTION_OPAQUE = "opaque"

_SHELL_OPERAND_OPTIONS = {
    "bash": {"--init-file", "--rcfile", "-O", "+O", "-o", "+o"},
    "dash": {"-o", "+o"},
    "ksh": {"-o", "+o"},
    "mksh": {"-o", "+o"},
    "sh": {"-o", "+o"},
    "zsh": {"-o", "+o"},
}

_SHELL_NO_EXEC_OPTIONS = {"--help", "--version"}
_SHELL_NO_OPERAND_OPTIONS = {
    "bash": {"--norc", "--noprofile", "--posix", "--restricted", "--verbose"},
    "dash": set(),
    "ksh": set(),
    "mksh": set(),
    "sh": set(),
    "zsh": set(),
}

_SHELL_SHORT_FLAG_CHARS = set("abefhkmnptuvxBCEHPTlrsD")

# Bash считает присваиванием только смежное ASCII-имя ``NAME=value`` без
# пробелов вокруг ``=`` и без Unicode в имени. Форма ``BODY =value`` (с пробелом)
# присваиванием НЕ является — это команда ``BODY`` с аргументом; такая запись не
# должна признаваться доверенной привязкой, иначе прежнее значение переменной
# осталось бы, а разбор выдал бы безопасное body.
_TRUSTED_ASSIGNMENT = re.compile(
    r"[ \t]*(?:export[ \t]+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)="
    r"\$\([ \t]*cat\b[ \t]*<<-?[ \t]*"
    r"(?P<q>['\"])(?P<token>[^'\"\r\n]+)(?P=q)"
    r"[ \t]*\r?\n(?P<body>.*?)\r?\n[ \t]*(?P=token)[ \t]*\r?\n"
    r"[ \t]*\)[ \t]*\Z",
    re.DOTALL,
)

_SIMPLE_ASSIGNMENT = re.compile(
    r"[ \t]*(?:export[ \t]+)?[A-Za-z_][A-Za-z0-9_]*=.*\Z",
    re.DOTALL,
)

_BODY_EXACT_VAR = re.compile(
    r'"?\$(?:\{(?P<braced>[A-Za-z_]\w*)\}|(?P<plain>[A-Za-z_]\w*))"?\Z'
)

_GH_COMMENT_VALUE_OPTIONS = (
    ("--body", "-b", "body"),
    ("--body-file", "-F", "body_file"),
)
_VAR_EXPANSION = re.compile(r"\$(?:\{[^}]+\}|[A-Za-z_]\w*)")
_DIRECT_HEREDOC_VALUE = re.compile(
    r"\"?\$\([ \t]*cat\b[ \t]*<<-?[ \t]*"
    r"(?P<q>['\"])(?P<token>[^'\"\r\n]+)(?P=q)"
    r"[ \t]*\r?\n.*?\r?\n[ \t]*(?P=token)[ \t]*\r?\n"
    r"[ \t]*\)\"?\Z",
    re.DOTALL,
)


class _Lexer:
    def __init__(self, source: str, budget: "_ParseBudget" = _UNLIMITED_BUDGET):
        self.source = source
        self.length = len(source)
        self.budget = budget
        self._steps_since_time_check = 0
        # 1 = активный unquoted top-level код; 2 = активный код substitution.
        self.visible = bytearray(self.length)
        self.commands: list[_Command] = []
        self.global_ambiguous = False
        self.group_stack: list[str] = []
        self.opaque_spans: list[tuple[int, int]] = []
        # Позиции закрывающих скобок подстановок (`$( )`, `$(( ))`, `<( )`,
        # `>( )`). Там слово ПРОДОЛЖАЕТСЯ, поэтому решётка сразу за такой
        # скобкой комментария не открывает и остаток строки оболочка исполняет.
        # Лексер ведёт контекст сам, поэтому знает это точно; общее правило
        # получает набор вторым входом.
        self.word_continuations: set[int] = set()

    def _close_substitution(self, end: int) -> None:
        """Отметить закрывающую скобку подстановки, завершившейся на `end`."""

        if end - 1 >= 0:
            self.word_continuations.add(end - 1)

    def scan(self):
        position = 0
        while position < self.length:
            position = self._skip_separators(position)
            if position >= self.length:
                break
            command = _Command(start=position, ambiguous=bool(self.group_stack))
            try:
                end, position, separator = self._scan_context(
                    position, command, root=True, terminator=None
                )
            except _LexError:
                command.end = self.length
                command.ambiguous = True
                # При незавершённом heredoc граница redirect operand не
                # доказана: оставляем непрозрачное слово целиком, чтобы оно
                # могло породить candidate-scoped ambiguity.
                command.redirections.clear()
                self.commands.append(command)
                self.global_ambiguous = True
                break
            command.end = end
            command.separator = separator
            if self.source[command.start:command.end].strip():
                self.commands.append(command)
        if self.group_stack:
            self.global_ambiguous = True
        return self

    def _skip_separators(self, position: int) -> int:
        while position < self.length:
            char = self.source[position]
            if char in " \t\r\n;":
                position += 1
                continue
            if char == "#" and is_comment_start(
                self.source, position, word_continuations=self.word_continuations
            ):
                line_end = self.source.find("\n", position)
                return self.length if line_end < 0 else self._skip_separators(line_end + 1)
            return position
        return position

    def _mark_visible(self, start: int, end: int, root: bool):
        level = 1 if root else 2
        for index in range(start, min(end, self.length)):
            self.visible[index] = level

    def _scan_context(self, position, command, *, root, terminator):
        pending: list[_Heredoc] = []
        # Внутри подстановки ``$(...)`` вложенная группа ``( ... )`` — часть её
        # тела, а не конец. Без учёта вложенности скан обрывался на первой
        # закрывающей скобке, и остаток тела (вместе с командами в нём) не
        # попадал в opaque-контекст. Глубина считается только для терминатора
        # ``)``; непарная закрывающая скобка по-прежнему завершает скан.
        group_depth = 0
        while position < self.length:
            # Сверка с дедлайном внутри лексического цикла: без неё длинная
            # команда без вложенности прошла бы весь скан, не заметив предела.
            self._steps_since_time_check += 1
            if self._steps_since_time_check >= _TIME_CHECK_STRIDE:
                self._steps_since_time_check = 0
                self.budget.check_time()
            char = self.source[position]

            if terminator == ")" and char == "(":
                group_depth += 1
                self._mark_visible(position, position + 1, root)
                position += 1
                continue

            if terminator and char == terminator:
                if group_depth > 0:
                    group_depth -= 1
                    self._mark_visible(position, position + 1, root)
                    position += 1
                    continue
                return position + 1, position + 1, "nested"

            if char == "'":
                position = self._scan_single_quote(position)
                continue
            if char == '"':
                position = self._scan_double_quote(position, command)
                continue
            if char == "`":
                position = self._scan_backtick(position, command)
                continue
            if char == "\\":
                if position + 1 >= self.length:
                    raise _LexError()
                position += 2
                continue
            if self.source.startswith("$((", position):
                arith_end = self._scan_arithmetic(position, command)
                if arith_end is not None:
                    position = arith_end
                    continue
                # Не арифметика (`$( (…) )`) — разбираем как подстановку команды.
            if self.source.startswith("$(", position):
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, end - 1))
                self._close_substitution(end)
                position = end
                continue
            if self.source.startswith("${", position):
                position = self._scan_parameter(position + 2, command)
                continue
            if self.source.startswith(("<(", ">("), position):
                # Подстановка процесса — тоже подстановка: её тело исполняется,
                # а закрывающая скобка остаётся ВНУТРИ слова (оболочка
                # подставляет на её месте путь к каналу, и решётка сразу за
                # скобкой комментария не открывает). Тело осматривается тем же
                # рекурсивным проходом, что и `$( )`. Команда при этом остаётся
                # неоднозначной: достижимость публикации внутри канала разбор
                # не доказывает.
                command.ambiguous = True
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, end - 1))
                self._close_substitution(end)
                position = end
                continue
            if self.source.startswith(_EXTGLOB_OPENERS, position):
                # Extglob-шаблон (`@( ?( *( +( !(`) — часть слова: тело —
                # шаблон имени, закрывающая скобка остаётся внутри слова, как у
                # подстановки, и решётка сразу за ней комментария не открывает.
                # Конструкция разобрана полностью. Вложенные `$( )` в теле берёт
                # на себя рекурсивный проход.
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self._close_substitution(end)
                position = end
                continue
            if self.source.startswith("<<", position) and not self.source.startswith("<<<", position):
                heredoc, position = self._parse_heredoc(position)
                pending.append(heredoc)
                if root:
                    command.redirections.append(
                        _Redirection(
                            heredoc.operator_start,
                            heredoc.operator_start + (3 if heredoc.strip_tabs else 2),
                        )
                    )
                self._mark_visible(heredoc.operator_start, position, root)
                continue
            if char == "#" and is_comment_start(
                self.source, position, word_continuations=self.word_continuations
            ):
                line_end = self.source.find("\n", position)
                position = self.length if line_end < 0 else line_end
                continue
            if char == "\n":
                if pending:
                    position = self._consume_heredocs(position + 1, pending, command)
                    pending.clear()
                    if root:
                        return position, position, "sequence"
                    continue
                if root:
                    return position, position + 1, "sequence"
                position += 1
                continue
            if root and char == ";":
                if self.source.startswith((";;", ";&"), position):
                    return position, position + 2, "control"
                return position, position + 1, "sequence"
            if root and self.source.startswith(("&&", "||"), position):
                return position, position + 2, "control"
            if root and (char in "<>" or self.source.startswith("&>", position)):
                operator_end = self._redirection_operator_end(position)
                command.redirections.append(_Redirection(position, operator_end))
                self._mark_visible(position, operator_end, root)
                position = operator_end
                continue
            if root and char == "{":
                redirection = self._brace_fd_redirection(position)
                if redirection is not None:
                    command.redirections.append(redirection)
                    self._mark_visible(position, redirection.operator_end, root)
                    position = redirection.operator_end
                    continue
            if root and char == "|":
                return position, position + 1, "control"
            if root and char == "&":
                # Финальный background-list возвращает управление до результата
                # ``gh``. PostToolUse видит успех shell, но не успех публикации.
                return position, position + 1, "background"
            if root and char in "({":
                # Подоболочка `( … )` и группа `{ … }` РАЗБИРАЮТСЯ полностью:
                # их тело сканируется здесь же, и любая публикация внутри
                # помечается неоднозначной (команда открыта группой). Сама
                # сбалансированная группа вход недоказуемым не делает, поэтому
                # глобальный признак незавершённого разбора не поднимает —
                # его поднимет незакрытая группа (см. `scan`).
                command.ambiguous = True
                self.group_stack.append(")" if char == "(" else "}")
                if self._at_group_boundary(position):
                    command.execution_boundaries.append(position + 1)
            elif root and char in ")}":
                command.ambiguous = True
                matching_group = bool(
                    self.group_stack and self.group_stack[-1] == char
                )
                if matching_group:
                    self.group_stack.pop()
                # Закрывающая скобка без парной открывающей — это либо разделитель
                # ветки `case` (`pattern)`), либо синтаксическая ошибка оболочки.
                # В первом случае вход разобран (ветку разбирает `analyze_shell`);
                # во втором оболочка команду не исполнит, публикации в ней нет.
                # Поэтому признак незавершённого разбора здесь не поднимается —
                # реальную незавершённость ловят остаток `group_stack` и незакрытые
                # управляющие конструкции.
                if char == ")" and not matching_group:
                    command.execution_boundaries.append(position + 1)
            self._mark_visible(position, position + 1, root)
            position += 1

        if terminator or pending:
            raise _LexError()
        return position, position, "eof"

    def _redirection_operator_end(self, position: int) -> int:
        for operator in ("&>>", "<<<", ">>", "<>", ">&", "<&", ">|", "&>"):
            if self.source.startswith(operator, position):
                return position + len(operator)
        return position + 1

    def _brace_fd_redirection(self, position: int) -> _Redirection | None:
        name_start = position + 1
        if name_start >= self.length:
            return None
        first = self.source[name_start]
        if not (first == "_" or first.isascii() and first.isalpha()):
            return None
        name_end = name_start + 1
        while name_end < self.length:
            char = self.source[name_end]
            if char == "_" or char.isascii() and char.isalnum():
                name_end += 1
                continue
            break
        if name_end >= self.length or self.source[name_end] != "}":
            return None
        operator_start = name_end + 1
        if operator_start >= self.length or self.source[operator_start] not in "<>":
            return None
        return _Redirection(
            operator_start=operator_start,
            operator_end=self._redirection_operator_end(operator_start),
            designator_start=position,
            designator_end=name_end + 1,
        )

    def _scan_single_quote(self, position: int) -> int:
        end = self.source.find("'", position + 1)
        if end < 0:
            raise _LexError()
        return end + 1

    def _scan_double_quote(self, position: int, command: _Command) -> int:
        position += 1
        while position < self.length:
            char = self.source[position]
            if char == '"':
                return position + 1
            if char == "\\":
                if position + 1 >= self.length:
                    raise _LexError()
                position += 2
                continue
            if self.source.startswith("$((", position):
                arith_end = self._scan_arithmetic(position, command)
                if arith_end is not None:
                    position = arith_end
                    continue
                # Не арифметика (`$( (…) )`) — разбираем как подстановку команды.
            if self.source.startswith("$(", position):
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, end - 1))
                self._close_substitution(end)
                position = end
                continue
            if self.source.startswith("${", position):
                position = self._scan_parameter(position + 2, command)
                continue
            if char == "`":
                position = self._scan_backtick(position, command)
                continue
            position += 1
        raise _LexError()

    def _scan_backtick(self, position: int, command: _Command) -> int:
        # Backtick-подстановка со своим экранированием — вне доказуемого
        # подмножества: помечаем АКТИВНУЮ команду неоднозначной, чтобы её
        # публикация не считалась доказанной. Но сама подстановка ЗАКРЫТА и
        # разобрана — вход недоказуемым она не делает, поэтому глобальный признак
        # незавершённого разбора не поднимает (его поднимет незакрытая обратная
        # кавычка через `_LexError`).
        command.ambiguous = True
        inner_start = position + 1
        position = inner_start
        while position < self.length:
            char = self.source[position]
            if char == "`":
                self.opaque_spans.append((inner_start, position))
                return position + 1
            if char == "\\":
                position += 2
            else:
                position += 1
        raise _LexError()

    def _scan_parameter(self, position: int, command: _Command) -> int:
        depth = 1
        while position < self.length:
            char = self.source[position]
            if char == "'":
                position = self._scan_single_quote(position)
                continue
            if char == '"':
                position = self._scan_double_quote(position, command)
                continue
            if self.source.startswith("$((", position):
                arith_end = self._scan_arithmetic(position, command)
                if arith_end is not None:
                    position = arith_end
                    continue
                # Не арифметика (`$( (…) )`) — разбираем как подстановку команды.
            if self.source.startswith("$(", position):
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, end - 1))
                self._close_substitution(end)
                position = end
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return position + 1
            elif char == "\\":
                position += 2
                continue
            elif char == "`":
                position = self._scan_backtick(position, command)
                continue
            position += 1
        raise _LexError()

    def _scan_arithmetic(self, position: int, command: _Command):
        """Разобрать арифметическое раскрытие ``$((EXPR))``; вернуть конец или None.

        Оболочка ВЫЧИСЛЯЕТ содержимое ``$((…))`` как арифметику, а не исполняет
        его как команду: ``$((a*b))`` — обычная арифметика. Поэтому голый текст
        выражения (``a*b``, ``2**8``, ``a?b:c``) командным словом НЕ является и в
        ``opaque_spans`` не попадает — иначе метасимвол ``*`` читался бы как glob
        и порождал фантомную публикацию. Вложенные РЕАЛЬНЫЕ подстановки внутри
        выражения (``$(…)``, обратная кавычка, ``${…}``) остаются подстановками и
        осматриваются отдельно: арифметика их результат подставляет.

        Отличие от ``$( (cmd) )`` (подстановка команды с подоболочкой) — по
        БАЛАНСУ двойных скобок: арифметика ЗАКРЫВАЕТСЯ смежными ``))``. Если
        закрытие не смежное (``$( (cmd) )`` — между закрывающими скобками пробел
        или содержимое), оболочка исполняет запись как подстановку команды, а не
        арифметику. В этом случае метод возвращает ``None`` без побочных эффектов,
        и вызывающий разбирает запись как обычную ``$(``-подстановку (там команда
        внутри подоболочки будет найдена). Невалидная арифметика со смежными
        ``))`` (``$((a b))``) оболочкой НЕ исполняется (синтаксическая ошибка),
        поэтому остаётся инертной.
        """
        start = position
        saved_opaque_len = len(self.opaque_spans)
        saved_word_continuations = set(self.word_continuations)

        def _abandon():
            del self.opaque_spans[saved_opaque_len:]
            self.word_continuations.clear()
            self.word_continuations.update(saved_word_continuations)
            return None

        # Две открывающие скобки из ``$((``. Считаем ТОЛЬКО голые скобки
        # арифметической группировки; скобки вложенных подстановок съедают их
        # собственные сканеры.
        paren = 2
        position += 3
        while position < self.length:
            char = self.source[position]
            if self.source.startswith("$((", position):
                nested_end = self._scan_arithmetic(position, command)
                if nested_end is None:
                    # Вложенная запись оказалась подстановкой команды, а не
                    # арифметикой — разбираем её как ``$(`` в контексте команды.
                    inner_start = position + 2
                    end, _, _ = self._scan_context(
                        inner_start, command, root=False, terminator=")"
                    )
                    self.opaque_spans.append((inner_start, end - 1))
                    self._close_substitution(end)
                    position = end
                    continue
                position = nested_end
                continue
            if self.source.startswith("$(", position):
                inner_start = position + 2
                end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, end - 1))
                self._close_substitution(end)
                position = end
                continue
            if self.source.startswith("${", position):
                position = self._scan_parameter(position + 2, command)
                continue
            if char == "`":
                position = self._scan_backtick(position, command)
                continue
            if char == "'":
                position = self._scan_single_quote(position)
                continue
            if char == '"':
                position = self._scan_double_quote(position, command)
                continue
            if char == "(":
                paren += 1
            elif char == ")":
                paren -= 1
                if paren == 0:
                    # Арифметику закрывают смежные ``))``. Иначе это ``$( (…) )`` —
                    # подстановка команды; отдаём разбор вызывающему.
                    if position == 0 or self.source[position - 1] != ")":
                        return _abandon()
                    # Всё выражение — не активный top-level код: помечаем уровнем
                    # подстановки, чтобы ни разбиение на слова, ни backstop не
                    # приняли арифметику за команду. Закрывающая скобка остаётся
                    # частью слова (решётка за ``))`` комментария не открывает).
                    self._mark_visible(start, position + 1, root=False)
                    self._close_substitution(position + 1)
                    return position + 1
            position += 1
        return _abandon()

    def _parse_heredoc(self, position: int):
        start = position
        position += 2
        strip_tabs = False
        if position < self.length and self.source[position] == "-":
            strip_tabs = True
            position += 1
        while position < self.length and self.source[position] in " \t":
            position += 1
        if position >= self.length:
            raise _LexError()

        # Разделитель heredoc разбирается ОБЩИМ shell-word парсером — тем же, что
        # определяет границы слова везде. Оболочка применяет к разделителю только
        # снятие кавычек, без раскрытия, поэтому терминатор известен статически
        # при любом кавычировании/экранировании (`<<\EOF`, `<<E"OF"`, `<<'E'OF`,
        # `<<"EOF"`, `<<'123'`). Тело нераскрываемо, если разделитель нёс хоть
        # одну кавычку или экранирование; при плоском слове — раскрываемо.
        delimiter, end, quoted, exact = shell_grammar.read_heredoc_word(
            self.source, position
        )
        if not exact or not delimiter or "\n" in delimiter:
            raise _LexError()
        # Незакавыченные `$`/обратная кавычка в разделителе выглядят раскрытием.
        # Оболочка их не раскрывает, но такой разделитель — не рабочая форма, и
        # разбор оставляет его недоказанным (global_ambiguous), а не угадывает.
        if not quoted and ("$" in delimiter or "`" in delimiter):
            raise _LexError()
        # Маркер нераскрываемости: любое кавычирование/экранирование делает тело
        # инертным (не сканируется на подстановки), плоское слово — раскрываемым.
        quote_style = "'" if quoted else None
        position = end
        return _Heredoc(start, delimiter, quote_style, strip_tabs), position

    def _consume_heredocs(self, position, pending, command):
        for heredoc in pending:
            body_start = position
            while position <= self.length:
                line_end = self.source.find("\n", position)
                if line_end < 0:
                    line_end = self.length
                line = self.source[position:line_end].rstrip("\r")
                comparable = line.lstrip("\t") if heredoc.strip_tabs else line
                if comparable == heredoc.delimiter:
                    raw_body = self.source[body_start:position]
                    if raw_body.endswith("\n"):
                        raw_body = raw_body[:-1]
                    if raw_body.endswith("\r"):
                        raw_body = raw_body[:-1]
                    heredoc.body_start = body_start
                    heredoc.body_end = position
                    heredoc.end = line_end + (1 if line_end < self.length else 0)
                    heredoc.body = raw_body
                    command.heredocs.append(heredoc)
                    # Тело heredoc с раскрываемым (unquoted) делимитером
                    # исполняет вложенные подстановки, поэтому гейт распознаёт
                    # $()/backtick/арифметику в нём как opaque-контекст и
                    # разбирает тем же рекурсивным проходом. Тело с
                    # quoted-делимитером раскрытия не имеет и остаётся инертным.
                    if heredoc.quote_style is None:
                        self._scan_expandable_body(
                            heredoc.body_start, heredoc.body_end, command
                        )
                    position = heredoc.end
                    break
                if line_end >= self.length:
                    raise _LexError()
                position = line_end + 1
            else:  # pragma: no cover — защитная ветка цикла
                raise _LexError()
        return position

    def _scan_expandable_body(self, start: int, end: int, command: _Command):
        """Просканировать тело раскрываемого heredoc на исполняемые подстановки.

        В теле heredoc с unquoted-делимитером исполняется только раскрытие:
        ``$(...)``, backtick и ``${...}``. Литеральный текст тела командой не
        является, поэтому сканируются именно подстановки, а их содержимое
        записывается в ``opaque_spans`` — так гейт распознаёт вложенный вызов в
        этом контексте тем же рекурсивным анализом, что и подстановку в обычном
        коде. Запись ``$((`` отдельного маршрута не имеет: она начинается с тех
        же символов, что ``$(``, и разбирается общей веткой, поэтому её тело
        целиком попадает в ``opaque_spans`` и осматривается fail-closed.
        """
        position = start
        while position < end:
            char = self.source[position]
            if char == "\\":
                position += 2
                continue
            if self.source.startswith("$(", position):
                inner_start = position + 2
                sub_end, _, _ = self._scan_context(
                    inner_start, command, root=False, terminator=")"
                )
                self.opaque_spans.append((inner_start, sub_end - 1))
                self._close_substitution(sub_end)
                position = sub_end
                continue
            if self.source.startswith("${", position):
                position = self._scan_parameter(position + 2, command)
                continue
            if char == "`":
                position = self._scan_backtick(position, command)
                continue
            position += 1

    def _at_group_boundary(self, position: int) -> bool:
        """Открывает ли символ по индексу новую группу ``(`` / ``{``.

        Вопрос «где начинается комментарий» решает единое правило
        ``shell_grammar.is_comment_start`` — здесь оно НЕ дублируется. Этот
        предикат отвечает на смежный вопрос про составные команды и потому
        считает границей ещё и фигурные скобки (см. ``_GROUP_BOUNDARY_CHARACTERS``).
        """
        if position == 0:
            return True
        previous = self.source[position - 1]
        return previous.isspace() or previous in _GROUP_BOUNDARY_CHARACTERS


_ROOT_OPERATORS = ";|&(){}<>"


def _decode_word(source: str, start: int, end: int) -> _Word:
    """Восстановить значение одного shell-word в доказанном подмножестве.

    Обычные single/double quotes, соседние quoted-сегменты, escape removal и
    backslash-newline обрабатываются точно. Expansion/globbing оставляют слово
    непрозрачным; для unquoted форм также отмечается возможное word splitting.
    """
    value = []
    prefix = []
    exact = True
    may_split = False
    position = start

    def append_literal(text: str):
        value.append(text)
        if exact:
            prefix.append(text)

    def mark_opaque(*, splits: bool):
        nonlocal exact, may_split
        exact = False
        may_split = may_split or splits

    while position < end:
        char = source[position]
        if char == "'":
            closing = source.find("'", position + 1, end)
            if closing < 0:
                mark_opaque(splits=False)
                break
            append_literal(source[position + 1:closing])
            position = closing + 1
            continue
        if char == '"':
            position += 1
            closed = False
            while position < end:
                char = source[position]
                if char == '"':
                    closed = True
                    position += 1
                    break
                if char == "\\":
                    if position + 1 >= end:
                        mark_opaque(splits=False)
                        position = end
                        break
                    following = source[position + 1]
                    if following == "\n":
                        position += 2
                        continue
                    if following == "\r" and position + 2 < end and source[position + 2] == "\n":
                        position += 3
                        continue
                    if following in '$`"\\':
                        append_literal(following)
                    else:
                        append_literal("\\" + following)
                    position += 2
                    continue
                if char in "$`":
                    mark_opaque(splits=False)
                    position += 1
                    continue
                append_literal(char)
                position += 1
            if not closed:
                mark_opaque(splits=False)
            continue
        if char == "\\":
            if position + 1 >= end:
                mark_opaque(splits=False)
                break
            following = source[position + 1]
            if following == "\n":
                position += 2
                continue
            if following == "\r" and position + 2 < end and source[position + 2] == "\n":
                position += 3
                continue
            append_literal(following)
            position += 2
            continue
        if char in "$`":
            mark_opaque(splits=True)
            position += 1
            continue
        if char in "*?":
            mark_opaque(splits=True)
            position += 1
            continue
        if char == "[":
            # Одиночные ``[``/``[[`` в command position — test builtin/keyword,
            # не glob. Glob-класс требует непустое содержимое и закрывающую ``]``.
            closing = source.find("]", position + 1, end)
            if closing > position + 1:
                mark_opaque(splits=True)
            else:
                append_literal(char)
            position += 1
            continue
        if char == "{" or (char == "~" and (not value or "".join(value).endswith("="))):
            mark_opaque(splits=True)
            position += 1
            continue
        append_literal(char)
        position += 1

    return _Word(
        start=start,
        end=end,
        value="".join(value) if exact else None,
        literal_prefix="".join(prefix),
        may_split=may_split,
    )


def _command_words(source: str, visible, command: _Command) -> list[_Word]:
    """Сформировать argv-подобные word-токены из уже доказанных границ."""
    words = []
    position = command.start
    while position < command.end:
        char = source[position]
        if visible[position] == 1 and (char.isspace() or char in _ROOT_OPERATORS):
            position += 1
            continue
        if visible[position] == 0 and char == "#":
            break
        start = position
        while position < command.end:
            char = source[position]
            if visible[position] == 1 and (
                char.isspace() or char in _ROOT_OPERATORS
            ):
                break
            position += 1
        if position > start:
            word = _decode_word(source, start, position)
            # После lexer-error нулевая visibility уже не доказывает, что
            # whitespace принадлежит одному quoted word. Такой непрозрачный
            # command-word способен скрывать несколько argv и остаётся
            # candidate-scoped unknown, а не глобальным запретом всего Bash.
            if (
                command.ambiguous
                and word.value is None
                and any(character.isspace() for character in source[start:position])
            ):
                word = _Word(
                    word.start,
                    word.end,
                    word.value,
                    word.literal_prefix,
                    True,
                )
            words.append(word)
        else:  # pragma: no cover — защитный прогресс
            position += 1
    redirected = set()
    for redirection in command.redirections:
        for index, word in enumerate(words):
            if (
                redirection.designator_start is not None
                and redirection.designator_end is not None
                and redirection.designator_start < word.start
                and word.end < redirection.designator_end
            ):
                redirected.add(index)
            if (
                word.end == redirection.operator_start
                and word.value is not None
                and word.value.isascii()
                and word.value.isdigit()
            ):
                redirected.add(index)
            if word.start >= redirection.operator_end:
                redirected.add(index)
                break
    return [word for index, word in enumerate(words) if index not in redirected]


def _is_assignment_word(source: str, word: _Word) -> bool:
    raw = source[word.start:word.end]
    return bool(re.match(r"[A-Za-z_]\w*=", raw))


def _command_word_index(source: str, words: list[_Word]) -> int | None:
    position = 0
    while position < len(words) and _is_assignment_word(source, words[position]):
        position += 1
    return position if position < len(words) else None


def _executable_name(word: _Word) -> str | None:
    if word.value is None:
        return None
    name = word.value.rsplit("/", 1)[-1]
    # Git Bash запускает Windows CLI регистронезависимо и допускает как
    # ``gh.exe``, так и безсуффиксное ``GH``. Оба написания должны попадать в
    # одну границу hard gate/consumer.
    normalized = name.lower()
    return normalized[:-4] if normalized.endswith(".exe") else normalized


def _payload_execution(payload: _Word | None) -> _Execution:
    if payload is None:
        return _Execution(_EXECUTION_NO_EXEC)
    if payload.value is None:
        return _Execution(_EXECUTION_OPAQUE, carrier=payload)
    return _Execution(_EXECUTION_EXACT, payload=payload)


def _split_string_execution(
    source: str, operand: _Word | None, trailing: list[_Word]
) -> _Execution:
    """``env -S`` / ``--split-string``: строка после разбиения плюс оставшиеся
    argv образуют исполняемую команду ЦЕЛИКОМ. Разбирается вся связка, а не
    только первый операнд, иначе публикация в хвосте argv терялась бы. Строка
    даёт свои токены разбором пробелов, хвостовые argv добавляются как есть.
    """

    if operand is None:
        return _Execution(_EXECUTION_NO_EXEC)
    if operand.value is None:
        return _Execution(_EXECUTION_OPAQUE, carrier=operand)
    parts = [operand.value]
    for word in trailing:
        parts.append(source[word.start:word.end])
    combined = " ".join(part for part in parts if part != "")
    if not combined.strip():
        return _Execution(_EXECUTION_NO_EXEC)
    end = trailing[-1].end if trailing else operand.end
    synthetic = _Word(operand.start, end, combined, combined, False)
    return _Execution(_EXECUTION_EXACT, payload=synthetic)


def _attached_option_payload(source: str, word: _Word) -> _Word | None:
    raw = source[word.start:word.end]
    equals = raw.find("=")
    if equals < 0:
        return None
    return _decode_word(source, word.start + equals + 1, word.end)


def _execution_index(source: str, words: list[_Word], start: int) -> _Execution:
    """Разрешить finite prefixes в exact/no-exec/opaque execution."""
    position = start
    while position < len(words):
        while position < len(words) and _is_assignment_word(source, words[position]):
            position += 1
        if position >= len(words):
            return _Execution(_EXECUTION_NO_EXEC)

        executable = _executable_name(words[position])
        if executable in _EXECUTION_CONTROL_PREFIXES:
            position += 1
            continue
        if executable == "command":
            position += 1
            while position < len(words):
                word = words[position]
                option = word.value
                if option == "-p":
                    position += 1
                    continue
                if option == "--":
                    position += 1
                    break
                if option in ("-v", "-V"):
                    return _Execution(_EXECUTION_NO_EXEC)
                if option is None:
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                if option.startswith("-"):
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                break
            continue
        if executable == "exec":
            position += 1
            while position < len(words):
                word = words[position]
                option = word.value
                if option in ("-c", "-l", "-cl", "-lc"):
                    position += 1
                    continue
                if option == "--":
                    position += 1
                    break
                if option == "-a":
                    if position + 1 >= len(words):
                        return _Execution(_EXECUTION_NO_EXEC)
                    position += 2
                    continue
                if option is None:
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                if option.startswith("-"):
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                break
            continue
        if executable == "env":
            position += 1
            while position < len(words):
                word = words[position]
                option = word.value
                if _is_assignment_word(source, word):
                    position += 1
                    continue
                if option in ("-i", "--ignore-environment"):
                    position += 1
                    continue
                if option == "--":
                    position += 1
                    break
                if option in ("-u", "--unset", "-C", "--chdir"):
                    if position + 1 >= len(words):
                        return _Execution(_EXECUTION_NO_EXEC)
                    position += 2
                    continue
                if option in ("-S", "--split-string"):
                    operand = words[position + 1] if position + 1 < len(words) else None
                    return _split_string_execution(
                        source, operand, list(words[position + 2:])
                    )
                if option is not None and option.startswith("--split-string="):
                    return _split_string_execution(
                        source,
                        _attached_option_payload(source, word),
                        list(words[position + 1:]),
                    )
                if option is not None and option.startswith(("--unset=", "--chdir=")):
                    position += 1
                    continue
                if option is None and word.literal_prefix.startswith("--split-string="):
                    return _split_string_execution(
                        source,
                        _attached_option_payload(source, word),
                        list(words[position + 1:]),
                    )
                if option is None:
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                if option.startswith("-"):
                    return _Execution(_EXECUTION_OPAQUE, carrier=word)
                break
            continue
        return _Execution(_EXECUTION_EXACT, index=position)
    return _Execution(_EXECUTION_NO_EXEC)


def _execution_sites(source: str, words: list[_Word], command: _Command):
    starts = []
    command_index = _command_word_index(source, words)
    if command_index is not None:
        starts.append(command_index)
    for boundary in command.execution_boundaries:
        for index, word in enumerate(words):
            if word.start >= boundary:
                starts.append(index)
                break

    executions = []
    seen = set()
    for start in starts:
        execution = _execution_index(source, words, start)
        key = (
            execution.state,
            execution.index,
            execution.payload.start if execution.payload is not None else None,
            execution.carrier.start if execution.carrier is not None else None,
        )
        if key not in seen:
            seen.add(key)
            executions.append(execution)
    return executions


def _possible_sequence(words: list[_Word], start: int, targets: tuple[str, ...]):
    """Вернуть конец возможной последовательности и признак неопределённости."""
    position = start
    uncertain = False
    for target in targets:
        if position >= len(words):
            return None
        word = words[position]
        if word.value == target:
            position += 1
            continue
        if word.value is None:
            uncertain = True
            position += 1
            if word.may_split:
                return position, True
            continue
        return None
    return position, uncertain


def _gh_repo_option(words: list[_Word], position: int):
    """Вернуть позицию после одного доказанного ``--repo``/``-R``.

    Persistent option GitHub CLI допустим до ``pr`` и между ``pr``/``comment``;
    Cobra принимает как раздельные, так и attached-формы. Динамический payload
    безопасен только когда граница argv доказана кавычками.
    """

    if position >= len(words):
        return None
    word = words[position]
    value = word.value
    prefix = word.literal_prefix

    if value in ("-R", "--repo"):
        if position + 1 >= len(words):
            return None
        operand = words[position + 1]
        return position + 2, operand.value is None and operand.may_split

    attached = bool(
        value is not None
        and (
            value.startswith("--repo=") and len(value) > len("--repo=")
            or value.startswith("-R") and len(value) > len("-R")
        )
    )
    dynamic_attached = bool(
        value is None
        and (
            prefix.startswith("--repo=")
            or prefix.startswith("-R=")
            or prefix.startswith("-R") and len(prefix) > len("-R")
        )
    )
    if attached or dynamic_attached:
        return position + 1, word.may_split
    return None


def _candidate(words: list[_Word], command_index: int):
    """Найти точный либо подозреваемый ``gh [repo] pr [repo] comment``."""
    gh_word = words[command_index]
    gh_possible = _executable_name(gh_word) == "gh" or gh_word.value is None
    if gh_possible:
        position = command_index + 1
        uncertain = gh_word.value is None
        while True:
            option = _gh_repo_option(words, position)
            if option is None:
                break
            position, option_uncertain = option
            uncertain = uncertain or option_uncertain

        if position < len(words):
            pr_word = words[position]
            if pr_word.value == "pr" or pr_word.value is None:
                uncertain = uncertain or pr_word.value is None
                position += 1
                while True:
                    option = _gh_repo_option(words, position)
                    if option is None:
                        break
                    position, option_uncertain = option
                    uncertain = uncertain or option_uncertain
                if position < len(words):
                    comment_word = words[position]
                    if comment_word.value == "comment" or comment_word.value is None:
                        uncertain = uncertain or comment_word.value is None
                        end = position + 1
                        return None if uncertain else position, end, uncertain

    # Непрозрачный argv до literal ``pr comment`` может быть attached repo
    # option. Граница неизвестна, поэтому такой кандидат блокируется.
    if gh_possible and command_index + 2 < len(words):
        option_word = words[command_index + 1]
        if option_word.value is None:
            direct = _possible_sequence(
                words, command_index + 2, ("pr", "comment")
            )
            if direct:
                end, _ = direct
                return None, end, True
        if option_word.value is None and command_index + 3 < len(words):
            separate = _possible_sequence(
                words, command_index + 3, ("pr", "comment")
            )
            if separate:
                end, _ = separate
                return None, end, True

    # Одно unquoted непрозрачное command-word может раскрыться в несколько argv.
    if words[command_index].value is None and words[command_index].may_split:
        return None, command_index + 1, True
    return None


def _trusted_binding(source, command):
    match = _TRUSTED_ASSIGNMENT.fullmatch(source[command.start:command.end])
    if match is None or len(command.heredocs) != 1:
        return None
    heredoc = command.heredocs[0]
    if heredoc.quote_style != "'":
        return None
    if heredoc.delimiter != match.group("token") or heredoc.body != match.group("body"):
        return None
    return match.group("name"), heredoc.body


def _body_from_word(source, command, word: _Word, bindings):
    raw = source[word.start:word.end]
    direct = _DIRECT_HEREDOC_VALUE.fullmatch(raw)
    matching_heredocs = [
        heredoc
        for heredoc in command.heredocs
        if word.start <= heredoc.operator_start < word.end
    ]
    if direct and len(matching_heredocs) == 1:
        heredoc = matching_heredocs[0]
        if heredoc.quote_style == "'" and heredoc.delimiter == direct.group("token"):
            return heredoc.body, "direct_heredoc"

    variable = _BODY_EXACT_VAR.fullmatch(raw)
    if variable:
        name = variable.group("braced") or variable.group("plain")
        if name in bindings:
            return bindings[name], "variable_heredoc"
        return None, "opaque_variable"
    if word.value is not None:
        return word.value, "literal"
    if "$(" in raw or "`" in raw:
        return None, "opaque_substitution"
    if _VAR_EXPANSION.search(raw):
        return None, "opaque_variable"
    return None, "ambiguous_word"


def _attached_option_value(
    source: str, word: _Word, spelling: str, *, short: bool
) -> _Word:
    """Декодировать attached operand, сохранив shell-семантику его части.

    Long options принимают только ``--name=value``. Value-taking short options
    Cobra/pflag принимают как ``-bVALUE`` и ``-b=VALUE``; необязательный ``=``
    не является частью значения. Если сам spelling собран динамически, границу
    доказать нельзя и вызывающая сторона получит непрозрачный word.
    """

    raw = source[word.start:word.end]
    marker = spelling if short else spelling + "="
    if raw.startswith(marker):
        value_start = word.start + len(marker)
        if short and value_start < word.end and source[value_start] == "=":
            value_start += 1
        return _decode_word(source, value_start, word.end)

    value = word.value
    if value is not None and value.startswith(marker):
        payload = value[len(marker):]
        if short and payload.startswith("="):
            payload = payload[1:]
        return _Word(word.start, word.end, payload, payload, False)

    return _Word(word.start, word.end, None, word.literal_prefix, word.may_split)


def _gh_comment_value_option(
    source: str, words: list[_Word], position: int
) -> _GhValueOption | None:
    """Разобрать value-taking option по общей long/short argv-грамматике."""

    if position >= len(words):
        return None
    word = words[position]
    value = word.value
    prefix = word.literal_prefix

    for long_name, short_name, canonical in _GH_COMMENT_VALUE_OPTIONS:
        if value in (long_name, short_name):
            operand = words[position + 1] if position + 1 < len(words) else None
            return _GhValueOption(canonical, operand, position + 2)

        long_marker = long_name + "="
        if (
            (value is not None and value.startswith(long_marker))
            or (value is None and prefix.startswith(long_marker))
        ):
            operand = _attached_option_value(
                source, word, long_name, short=False
            )
            return _GhValueOption(canonical, operand, position + 1)

        if (
            (
                value is not None
                and value.startswith(short_name)
                and len(value) > len(short_name)
            )
            or (
                value is None
                and prefix.startswith(short_name)
                and len(prefix) > len(short_name)
            )
        ):
            operand = _attached_option_value(
                source, word, short_name, short=True
            )
            return _GhValueOption(canonical, operand, position + 1)

    return None


def _publication_body(source, command, words, comment_end, bindings):
    body_seen = False
    final_body = None
    opaque_sources = []
    position = comment_end
    while position < len(words):
        word = words[position]
        value = word.value
        option = _gh_comment_value_option(source, words, position)
        if option is not None:
            if option.canonical == "body":
                body_seen = True
                final_body = option.value
            else:
                opaque_sources.append(option.canonical)
            position = option.next_position
            continue
        if value == "--edit-last":
            opaque_sources.append("edit_last")
        position += 1

    if opaque_sources:
        if body_seen or len(set(opaque_sources)) > 1:
            return None, "ambiguous_word"
        return None, opaque_sources[-1]
    if not body_seen:
        return None, "missing"
    if final_body is None:
        return None, "missing"
    return _body_from_word(source, command, final_body, bindings)


def _pr_number(source, words: list[_Word], comment_end: int) -> str | None:
    numbers = []
    position = comment_end
    while position < len(words):
        option = _gh_comment_value_option(source, words, position)
        if option is not None:
            break
        value = words[position].value
        if value == "--edit-last":
            break
        if value and value.isascii() and value.isdigit():
            numbers.append(value)
        position += 1
    return numbers[-1] if numbers else None


def _is_script_file_operand(word: _Word) -> bool:
    """Является ли слово путём файла, который оболочка прочитает сама.

    Такой запуск приравнен к запуску любой другой внешней программы, читающей
    файл (``python3 x.py``, ``npm run …``): разбор относится к ФОРМЕ
    shell-команды, а содержимое запускаемых программ в его предмет не входит.
    Это заявленный предел контракта той же семьи, что уже принятый предел
    commit-гейта. Без паритета самая частая команда разработчика получала другой
    вердикт, чем равносильный по возможностям запуск интерпретатора.

    Путём считается только точно известное непустое слово. Формы, где нагрузка
    может оказаться не файлом, сюда не относятся и разбираются прежним порядком:

    * значение не восстановлено дословно (переменная, подстановка, шаблон) —
      разбор не знает, что именно прочитает оболочка;
    * ``-`` и ``+`` — это указание читать стандартный вход, а не путь;
    * подстановка процесса в позиции файла — её тело оболочка исполняет здесь
      же, и оно относится к разбираемой команде, а не к внешней программе.
    """

    value = word.value
    if not value:
        return False
    if value in ("-", "+"):
        return False
    if "<(" in value or ">(" in value:
        return False
    return True


def _operand_execution(word: _Word) -> _Execution:
    """Вердикт для первого слова-операнда оболочки.

    Путь запускаемого файла даёт тот же вердикт, что запуск любой другой внешней
    программы: команда обычная. Остальные операнды разбираются прежним порядком.
    Признак «программа со стандартного входа» сюда не доходит: он решается раньше
    (флаг `-s`, отсутствие файла-операнда) и всегда непрозрачен.
    """

    if _is_script_file_operand(word):
        return _Execution(_EXECUTION_NO_EXEC)
    return _Execution(_EXECUTION_OPAQUE, carrier=word)


def _shell_payload_word(words: list[_Word], command_index: int) -> _Execution:
    wrapper = _executable_name(words[command_index])
    if wrapper not in _SHELL_EXECUTION_WRAPPERS:
        return _Execution(_EXECUTION_NO_EXEC)
    # Программа со стандартного ВХОДА непрозрачна по форме так же, как строка в
    # `-c`: разбор её не видит. Оболочка берёт программу из потока, когда явного
    # файла-операнда нет — при флаге `-s`, при одиночном `-`, при пустом argv (в
    # т.ч. в конце пайпа), при here-string/heredoc в позиции ввода. Во всех этих
    # случаях носитель непрозрачен, и гейт обязан считать вход недоказанным.
    stdin_carrier = words[command_index]
    position = command_index + 1
    while position < len(words):
        word = words[position]
        option = word.value
        if option is None:
            return _Execution(_EXECUTION_OPAQUE, carrier=word)
        if option in _SHELL_NO_EXEC_OPTIONS:
            return _Execution(_EXECUTION_NO_EXEC)
        if option == "--":
            carrier = words[position + 1] if position + 1 < len(words) else None
            if carrier is None:
                # Файла после `--` нет — программа приходит со стандартного входа.
                return _Execution(_EXECUTION_OPAQUE, carrier=stdin_carrier)
            return _operand_execution(carrier)
        if option in _SHELL_OPERAND_OPTIONS[wrapper]:
            if position + 1 >= len(words):
                return _Execution(_EXECUTION_NO_EXEC)
            position += 2
            continue
        if option in _SHELL_NO_OPERAND_OPTIONS[wrapper]:
            position += 1
            continue
        if option.startswith("--"):
            return _Execution(_EXECUTION_OPAQUE, carrier=word)
        if option[:1] in ("-", "+") and option not in ("-", "+"):
            flags = option[1:]
            if "c" in flags:
                payload = words[position + 1] if position + 1 < len(words) else None
                return _payload_execution(payload)
            if "s" in flags:
                # `-s` фиксирует источник программы — стандартный вход.
                return _Execution(_EXECUTION_OPAQUE, carrier=stdin_carrier)
            if all(flag in _SHELL_SHORT_FLAG_CHARS for flag in flags):
                position += 1
                continue
            return _Execution(_EXECUTION_OPAQUE, carrier=word)
        return _operand_execution(word)
    # argv кончился без файла-операнда: программа приходит со стандартного входа
    # (одиночный `bash`, в том числе замыкающий пайп; here-string/heredoc в
    # позиции ввода уже учтены как перенаправления).
    return _Execution(_EXECUTION_OPAQUE, carrier=stdin_carrier)


def _carried_execution_publications(command, execution, anchor, budget):
    if execution.state == _EXECUTION_NO_EXEC:
        return []
    if execution.state == _EXECUTION_OPAQUE:
        carrier = execution.carrier or anchor
        return [
            Publication(
                start=carrier.start,
                end=carrier.end,
                command_start=command.start,
                command_end=command.end,
                body=None,
                body_kind="ambiguous_word",
                ambiguous=True,
            )
        ]

    payload = execution.payload
    if payload is None:
        return []
    nested = analyze_shell(payload.value, _nested=True, _budget=budget.descend())
    lifted = []
    payload_width = max(payload.end - payload.start, 1)
    for publication in nested.publications:
        lifted.append(
            Publication(
                start=payload.start + min(publication.start, payload_width - 1),
                end=payload.start + min(max(publication.end, 1), payload_width),
                command_start=command.start,
                command_end=command.end,
                body=publication.body,
                body_kind=publication.body_kind,
                ambiguous=True,
                pr_number=publication.pr_number,
            )
        )
    return lifted


def _wrapper_publications(
    command, words, command_index, budget, *, scan_unknown=True
):
    executable = _executable_name(words[command_index])
    if executable in _SHELL_EXECUTION_WRAPPERS:
        execution = _shell_payload_word(words, command_index)
        return _carried_execution_publications(
            command, execution, words[command_index], budget
        )
    if executable in _PROVEN_DATA_COMMANDS or not scan_unknown:
        return []

    # Семантику произвольного carrier доказать нельзя. Проверяем каждый точный
    # literal argv как самостоятельный shell-payload и каждую точную argv-
    # последовательность, начинающуюся с ``gh``. Это закрывает КЛАСС carriers,
    # не перечисляя отдельные launchers. Непрозрачные/dynamic payload'ы здесь не
    # угадываются: hard gate — safety guard, а не полноценный shell sandbox.
    #
    # Отбор нагрузок идёт по НЕДОКАЗАННОСТИ инертности, а не по совпадению с
    # позитивным образцом: образец не переживает кавычек следующего уровня, и
    # его несовпадение раньше означало «пропустить». Теперь несовпадение
    # означает «разобрать»; отсеивается только доказанно инертный текст.
    payloads = []
    arguments = words[command_index + 1 :]
    for argument in arguments:
        if argument.value is not None and _may_carry_publication(argument.value):
            payloads.append(argument)
    for index, argument in enumerate(arguments):
        if _executable_name(argument) != "gh":
            continue
        exact_tail = []
        for tail_word in arguments[index:]:
            if tail_word.value is None:
                break
            exact_tail.append(tail_word.value)
        joined_tail = " ".join(exact_tail)
        if exact_tail and _LITERAL_PUBLICATION_LEXEME.search(joined_tail):
            payloads.append(
                _Word(
                    start=argument.start,
                    end=arguments[index + len(exact_tail) - 1].end,
                    value=joined_tail,
                    literal_prefix=joined_tail,
                    may_split=False,
                )
            )

    publications = []
    seen_payloads = set()
    for payload in payloads:
        key = (payload.start, payload.end, payload.value)
        if key in seen_payloads:
            continue
        seen_payloads.add(key)
        nested = analyze_shell(payload.value, _nested=True, _budget=budget.descend())
        payload_width = max(payload.end - payload.start, 1)
        for publication in nested.publications:
            publications.append(
                Publication(
                    start=payload.start + min(publication.start, payload_width - 1),
                    end=payload.start + min(max(publication.end, 1), payload_width),
                    command_start=command.start,
                    command_end=command.end,
                    body=publication.body,
                    body_kind=publication.body_kind,
                    ambiguous=True,
                    pr_number=publication.pr_number,
                )
            )
    return publications


def _merge_spans(spans) -> tuple[list[int], list[int]]:
    """Свести полуоткрытые интервалы в непересекающиеся отсортированные.

    Возвращает параллельные списки начал и концов. По ним проверка пересечения
    идёт бинарным поиском: интервалы упорядочены и не накладываются, поэтому
    достаточно проверить единственного кандидата слева от конца запроса.
    """
    ordered = sorted(spans)
    starts: list[int] = []
    ends: list[int] = []
    for span_start, span_end in ordered:
        if span_end <= span_start:
            continue
        if starts and span_start <= ends[-1]:
            if span_end > ends[-1]:
                ends[-1] = span_end
            continue
        starts.append(span_start)
        ends.append(span_end)
    return starts, ends


def analyze_shell(
    source: str,
    *,
    _nested=False,
    _budget: "_ParseBudget | None" = None,
    time_limit_seconds: float | None = None,
    max_depth: int | None = None,
) -> ShellAnalysis:
    """Одним stateful-проходом разобрать реальные top-level публикации.

    ``time_limit_seconds`` и ``max_depth`` — пределы разбора. Пока вызывающий их
    не задал, пределов нет и поведение прежнее. Блокирующий гейт обязан задавать
    их сам и не полагаться на предел внешнего диспетчера: снятый диспетчером
    обработчик кода выхода не возвращает, а блокирует только код 2 — то есть
    команда прошла бы при неразобранном вводе. По истечении предела разбор
    бросает ``ShellParseLimitExceeded``, и это блокировка, а не разрешение.
    """
    if _budget is not None:
        budget = _budget
    elif time_limit_seconds is None and max_depth is None:
        budget = _UNLIMITED_BUDGET
    else:
        budget = _ParseBudget(
            deadline=(
                None
                if time_limit_seconds is None
                else time.monotonic() + time_limit_seconds
            ),
            max_depth=(
                DEFAULT_MAX_SUBSTITUTION_DEPTH if max_depth is None else max_depth
            ),
        )
    budget.check_time()
    # Единая нормализация ДО разбора: убираем продолжение строки
    # (`\`+перевод строки) контекстно, как это делает оболочка. Иначе и разбиение
    # на слова, и литерал-backstop видели бы `gh \<LF>pr comment` как разорванные
    # слова и пропускали публикацию, которую оболочка склеивает в `gh pr comment`.
    # После нормализации ВЕСЬ дальнейший разбор — лексер, разбиение на слова,
    # backstop — идёт по тексту без продолжений строки. Правило и его heredoc-
    # зависимости живут в общем модуле `shell_grammar`, тот же источник у
    # commit-гейта.
    source = shell_grammar.splice_line_continuations(source)
    lexer = _Lexer(source, budget).scan()
    publications = []
    bindings = {}
    control_stack = []
    conditional_next = False
    structural_ambiguous = False

    for command_position, command in enumerate(lexer.commands):
        budget.checkpoint()
        words = _command_words(source, lexer.visible, command)
        command_index = _command_word_index(source, words)
        first_word = (
            words[command_index].value if command_index is not None else None
        )
        control_word = first_word in _CONTROL_WORDS
        opening = _CONTROL_OPENERS.get(first_word)
        closing = first_word if first_word in _CONTROL_CLOSERS else None
        invalid_closing = bool(
            closing and (not control_stack or control_stack[-1] != closing)
        )
        command_ambiguous = (
            conditional_next
            or bool(control_stack)
            or command.ambiguous
            or control_word
            or invalid_closing
            # ``!`` инвертирует статус gh, а background-list возвращает успех
            # до завершения gh. В обоих случаях итоговый Bash status не
            # доказывает, что комментарий действительно опубликован.
            or first_word == "!"
            or command.separator == "background"
        )
        command_publications = []
        for execution in _execution_sites(source, words, command):
            if execution.state == _EXECUTION_NO_EXEC:
                continue
            if execution.state == _EXECUTION_OPAQUE or execution.payload is not None:
                anchor = execution.carrier or execution.payload
                if anchor is not None:
                    command_publications.extend(
                        _carried_execution_publications(
                            command, execution, anchor, budget
                        )
                    )
                continue
            execution_index = execution.index
            if execution_index is None:
                continue
            # Начальный word ветки ``case`` — pattern перед ``)``, а не
            # executable. Внутренние execution boundaries всё равно разбираются.
            if (
                control_stack
                and control_stack[-1] == "esac"
                and execution_index == command_index
                and command.execution_boundaries
                and words[execution_index].end <= command.execution_boundaries[0]
            ):
                continue
            candidate = _candidate(words, execution_index)
            if candidate:
                comment_index, comment_end, uncertain = candidate
                body, body_kind = _publication_body(
                    source, command, words, comment_end, bindings
                )
                start = words[execution_index].start
                end = (
                    words[comment_index].end
                    if comment_index is not None
                    else words[execution_index].end
                )
                command_publications.append(
                    Publication(
                        start=start,
                        end=end,
                        command_start=command.start,
                        command_end=command.end,
                        body=body,
                        body_kind=body_kind,
                        ambiguous=(
                            _nested
                            or command_ambiguous
                            # PostToolUse подтверждает только итоговый статус всей
                            # Bash-команды. Если после публикации есть ещё команда,
                            # её успех может скрыть сбой отдельного ``gh`` (`|| true`,
                            # `; true`, второй вызов). Hard gate блокирует такой
                            # маршрут, consumer не записывает неподтверждённый state.
                            or command_position < len(lexer.commands) - 1
                            or uncertain
                            or body_kind == "ambiguous_word"
                        ),
                        pr_number=_pr_number(source, words, comment_end),
                    )
                )
            command_publications.extend(
                _wrapper_publications(
                    command,
                    words,
                    execution_index,
                    budget,
                    scan_unknown=(
                        candidate is None
                        and not (
                            command.execution_boundaries
                            and execution_index == command_index
                        )
                    ),
                )
            )

        if command_publications:
            publications.extend(command_publications)
            bindings.clear()
        elif not command_ambiguous:
            binding = _trusted_binding(source, command)
            if binding:
                bindings[binding[0]] = binding[1]
            elif _SIMPLE_ASSIGNMENT.fullmatch(source[command.start:command.end]):
                bindings.clear()
            else:
                bindings.clear()
        else:
            bindings.clear()

        if opening:
            control_stack.append(opening)
        elif closing:
            if invalid_closing:
                structural_ambiguous = True
            else:
                control_stack.pop()
        conditional_next = command.separator == "control"

    # Подстановки проверяются тем же lexer/token pipeline. Кандидат внутри них
    # реален или как минимум исполнимо подозреваем, но его достижимость и body
    # для внешнего вызова не доказаны, поэтому он всегда candidate-ambiguous.
    nested_publications = []
    for span_start, span_end in lexer.opaque_spans:
        budget.checkpoint()
        if span_end <= span_start:
            continue
        nested = analyze_shell(
            source[span_start:span_end], _nested=True, _budget=budget.descend()
        )
        for publication in nested.publications:
            nested_publications.append(
                Publication(
                    start=span_start + publication.start,
                    end=span_start + publication.end,
                    command_start=span_start + publication.command_start,
                    command_end=span_start + publication.command_end,
                    body=publication.body,
                    body_kind=publication.body_kind,
                    ambiguous=True,
                    pr_number=publication.pr_number,
                )
            )

    # Запасной вердикт (структурное закрытие класса «ручной разбор расходится с
    # грамматикой shell»). Умолчание смещено с «не доказано, что публикация —
    # пропускаем» на «не доказано, что инертно — блокируем». Если литерал
    # ``gh … pr … comment`` целиком лежит в АКТИВНОМ unquoted top-level коде
    # (``visible == 1`` — не в кавычках, не в комментарии, не в теле heredoc и не
    # в подстановке), но структурный разбор НЕ признал для него доказанную
    # публикацию, вхождение эскалируется в publication с ``ambiguous=True`` —
    # гейт блокирует. Разбор уже осмотрел этот участок как код команды, значит
    # расхождение с грамматикой скрыло реальную публикацию. Содержимое кавычек и
    # подстановок сюда не попадает: кавычки инертны, а подстановки разбираются
    # рекурсивно (их литерал эскалируется уже на своём уровне). Штатная инлайн-
    # публикация с извлечённым body покрыта доказанной публикацией и здесь НЕ
    # дублируется — информер петли продолжает её считать (ambiguous не меняется).
    # Признанные публикации сведены в НЕПЕРЕСЕКАЮЩИЕСЯ отсортированные интервалы:
    # проверка «совпадение backstop уже покрыто признанной публикацией» тогда
    # идёт бинарным поиском за O(log P), а не линейным просмотром за O(P) на
    # каждое совпадение. Прежний линейный просмотр давал квадратичную стоимость
    # O(M·P) на широком входе (много top-level команд) и выводил разбор за предел
    # времени обработчика.
    merged_span_starts, merged_span_ends = _merge_spans(
        (publication.start, publication.end)
        for publication in publications + nested_publications
    )

    def _overlaps_recognized(match_start: int, match_end: int) -> bool:
        # Интервалы непересекающиеся и отсортированы: кандидат на пересечение —
        # интервал с наибольшим началом строго левее конца совпадения.
        index = bisect.bisect_left(merged_span_starts, match_end) - 1
        return index >= 0 and merged_span_ends[index] > match_start

    backstop_publications = []
    visible = lexer.visible
    visible_length = len(visible)
    for match in _LITERAL_PUBLICATION_LEXEME.finditer(source):
        budget.checkpoint()
        match_start, match_end = match.start(), match.end()
        if match_end > visible_length or match_start >= match_end:
            continue
        if any(
            visible[position] != 1
            for position in range(match_start, match_end)
        ):
            continue
        if _overlaps_recognized(match_start, match_end):
            continue
        backstop_publications.append(
            Publication(
                start=match_start,
                end=match_end,
                command_start=match_start,
                command_end=match_end,
                body=None,
                body_kind="ambiguous_word",
                ambiguous=True,
            )
        )

    deduplicated = {}
    for publication in publications + nested_publications + backstop_publications:
        budget.checkpoint()
        key = (publication.start, publication.end, publication.command_start)
        deduplicated[key] = publication

    return ShellAnalysis(
        tuple(sorted(deduplicated.values(), key=lambda item: item.start)),
        lexer.global_ambiguous or structural_ambiguous or bool(control_stack),
    )
