#!/usr/bin/env python3
"""Семантическая классификация Bash-команд для commit test-gate.

Публичный API: ``classify_command(command)`` возвращает один из трёх классов:
``ordinary``, ``commit`` или ``ambiguous``. Последние два обязаны запускать гейт.
CLI ``classify-hook`` дополнительно разбирает payload PreToolUse, чтобы shell-handler
не держал вторую реализацию распознавания команды.
"""

from __future__ import annotations

import os
import sys

# Каталог обработчиков не имеет права участвовать в разрешении имён модулей.
# Python сам ставит каталог запускаемого скрипта первым в sys.path, поэтому
# одноимённый файл рядом подменяет модуль стандартной библиотеки, а подменённый
# предикат отключается молча — с кодом «пропустить». Убираем каталог из пути ДО
# первого импорта стандартной библиотеки; соседние модули пакета грузятся ниже
# по явному пути файла. При импорте в качестве библиотеки (тесты) sys.path не
# трогаем: там разрешение имён — забота вызывающего.
#
# Сверка идёт по разрешённым путям: интерпретатор кладёт в пути поиска путь с
# раскрытыми символьными ссылками, а `abspath` их сохраняет.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if __name__ == "__main__":
    _EXCLUDED_DIR = os.path.realpath(_HOOK_DIR)
    sys.path[:] = [
        entry
        for entry in sys.path
        if os.path.realpath(entry or os.getcwd()) != _EXCLUDED_DIR
    ]

import importlib.util  # noqa: E402 — только после очистки sys.path
import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from enum import Enum  # noqa: E402
from typing import Iterable, List, Optional, Sequence, Tuple  # noqa: E402


def _load_sibling(name: str):
    """Загрузить соседний модуль пакета обработчиков по явному пути файла.

    Отказ загрузки обязан быть громким: молчаливое отключение предиката —
    это пропуск. Исключение поднимается наружу и превращается в блокировку
    вызывающим гейтом.
    """

    path = os.path.join(_HOOK_DIR, name + ".py")
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


# Правило «где начинается слово и где комментарий» — общее на пакет и живёт
# ровно в одном экземпляре. Классификатор его ИМПОРТИРУЕТ; собственной копии
# набора метасимволов или функции у него нет.
shell_grammar = _load_sibling("shell_grammar")
word_continuation_positions = shell_grammar.word_continuation_positions

# Нормализация продолжения строки и границы тел heredoc — тоже общие на пакет:
# гейт публикации (`analyze_shell`) и гейт коммита выполняют их из одного
# источника, иначе класс «перенос строки распадается на две команды» был бы
# закрыт на одном гейте из двух. Собственных копий у классификатора нет.
_HeredocSpan = shell_grammar.HeredocSpan
_read_heredoc_word = shell_grammar.read_heredoc_word
_heredoc_spans = shell_grammar.heredoc_spans
_splice_line_continuations = shell_grammar.splice_line_continuations


class CommandClass(str, Enum):
    ORDINARY = "ordinary"
    COMMIT = "commit"
    AMBIGUOUS = "ambiguous"


_CLASS_PRIORITY = {
    CommandClass.ORDINARY: 0,
    CommandClass.AMBIGUOUS: 1,
    CommandClass.COMMIT: 2,
}

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DYNAMIC = re.compile(r"[$`*?\[\]{}]")
_LITERAL_CODE_WORD = re.compile(r"[A-Za-z0-9_./=@:+-]+")
_CONTROL_PREFIXES = {"if", "then", "elif", "while", "until", "do", "else", "!", "{"}
_COMMAND_SEPARATORS = set(";&|()\n")

_GIT_NO_VALUE_OPTIONS = {
    # `--version` печатает версию и подкоманду не запускает: при `git --version
    # <подкоманда>` git печатает версию и подкоманду игнорирует. Поэтому дальше
    # по циклу разбора команда остаётся без подкоманды и получает ordinary.
    # `--help` сюда НЕ входит: с ним git открывает просмотрщик справки, заданный
    # конфигурацией (U2-i3woa). `-h` тоже не входит — он разбирается отдельной
    # веткой в `_classify_git`, потому что признаётся чтением только терминально.
    "--version",
    "-p",
    "--paginate",
    "-P",
    "--no-pager",
    "--no-replace-objects",
    "--bare",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-optional-locks",
}
_GIT_VALUE_OPTIONS = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
}
_GIT_VALUE_PREFIXES = (
    "-C",
    "-c",
    "--git-dir=",
    "--work-tree=",
    "--namespace=",
    "--super-prefix=",
    "--config-env=",
    "--exec-path=",
)

# Git aliases не могут перекрыть встроенную подкоманду. Доверяем только узкому
# переносимому ядру builtins, которое использует U2 workflow; optional porcelain
# (scalar/svn/p4), внешние ``git-<name>`` и новые команды сюда не добавляются.
# Неизвестное имя может быть alias из local/global/system config или
# GIT_CONFIG_COUNT и потому обязано запускать test-gate fail-closed.
# Стабильные встроенные подкоманды git: их alias затенить НЕ может (git
# игнорирует alias, совпадающий с именем builtin), поэтому риска «alias -> commit»
# нет и полный test-gate им не нужен. Сюда НЕ входят:
#   - подкоманды, создающие коммит на текущей ветке (`commit`, `cherry-pick`,
#     `revert`);
#   - подкоманды-НОСИТЕЛИ произвольных вложенных команд: `submodule foreach …` и
#     `bisect run …` исполняют переданную им команду; `git grep -O<cmd>` /
#     `--open-files-in-pager=<cmd>` исполняет команду через shell и может создать
#     коммит на ТЕКУЩЕЙ ветке. В allowlist их нет (обычный `grep` как
#     самостоятельная команда носителем не является и остаётся в non-carrier).
# Для них гейт остаётся консервативным (ambiguous -> прогон тестов).
# Опции sed, доказанно не дающие ни записи, ни запуска команд. Всё, чего здесь
# нет, отменяет доказательство целиком: `-f`/`--file` прячет текст программы,
# `-i`/`--in-place` пишет файл, `-s`/`--separate` и прочее остаётся
# консервативным по принципу fail-closed.
_SED_PROVEN_READONLY_OPTIONS = {
    "-n",
    "--quiet",
    "--silent",
    "-E",
    "-r",
    "--regexp-extended",
    "-z",
    "--null-data",
    "--posix",
}
# Те же короткие флаги буквами — для слипшейся формы вида `-nE`.
_SED_PROVEN_READONLY_SHORT = set("nErz")
# Символы, из которых может состоять НЕ закавыченная программа sed, чтобы её
# нельзя было раскрыть shell'ом: цифры, адресный `$`, разделители и команды
# whitelist'а. `$` здесь безопасен только потому, что вся строка сверяется
# грамматикой ниже: `$` допускается лишь как адрес последней строки.
_SED_INERT_BARE_PROGRAM_CHARS = set("0123456789$,;pdq= ")

_STABLE_BUILTIN_GIT_SUBCOMMANDS = {
    "add",
    "apply",
    "blame",
    "branch",
    "cat-file",
    "check-ref-format",
    "checkout",
    "clean",
    "clone",
    "config",
    "describe",
    "diff",
    "fetch",
    "for-each-ref",
    "gc",
    "hash-object",
    "init",
    "log",
    "ls-files",
    "ls-remote",
    "ls-tree",
    "merge",
    "mv",
    "pull",
    "push",
    "rebase",
    "reflog",
    "remote",
    "reset",
    "restore",
    "rev-list",
    "rev-parse",
    "rm",
    "show",
    "show-ref",
    "stash",
    "status",
    "switch",
    "symbolic-ref",
    "tag",
    "update-index",
    "update-ref",
    "worktree",
    "write-tree",
    # Подкоманды только для чтения (U2-e5d9a, K-1/K-2). Критерий добавления:
    # подкоманда не создаёт коммит и не исполняет внешнюю команду ни одной
    # своей опцией. `grep` (`-O`), `submodule` (`foreach`), `bisect` (`run`),
    # `difftool`/`mergetool` критерию не отвечают и намеренно остаются вне
    # списка. Исполнение через глобальный `-c` критерием не покрывается — это
    # отдельный, пре-существующий класс (`U2-i3woa`). Блок стоит отдельно от
    # алфавитного ядра выше намеренно: так видно, что добавил именно этот PR.
    "check-attr",
    "check-ignore",
    "check-mailmap",
    "count-objects",
    "merge-base",
    "name-rev",
    "patch-id",
    "show-branch",
    "stripspace",
    "var",
    "version",
}
_SHELL_NO_EXEC_OPTIONS = {"--help", "--version"}
_SHELL_OPERAND_OPTIONS = {"--init-file", "--rcfile", "-O", "+O", "-o", "+o"}
_SHELL_NO_OPERAND_OPTIONS = {
    "--norc",
    "--noprofile",
    "--posix",
    "--restricted",
    "--verbose",
}
_SHELL_SHORT_FLAG_CHARS = set("abefhkmnptuvxBCEHPTlrsD")

# Команды из этого списка потребляют операнды как данные и не используют их как
# локальную shell-команду. Им разрешены динамические аргументы без ложного
# запуска полного test-gate. Для любого другого неизвестного executable действует
# candidate-scoped граница: literal payload'ы и суффиксы, которые могут быть
# вложенной командой, проверяются fail-closed (nice/sudo/xargs/будущие wrappers
# не нужно перечислять). Обычный динамический data-аргумент сам по себе не
# запускает полный test-gate.
#
# ``awk``/``sed`` сюда НЕ входят: они НОСИТЕЛИ произвольных команд. sed остаётся
# opaque carrier из-за ``e``-команды. Для awk есть узкий proof ниже: только ПРЯМОЙ
# вызов с literal single-quoted program без ``system()``, pipe/coprocess, ``getline``
# и ``@load`` считается ordinary. Все остальные awk-формы остаются fail-closed.
# Это позволяет обычный ``awk '{print $1}'`` без превращения awk в data-only allowlist.
_NON_CARRIER_COMMANDS = {
    ":",
    "[",
    "basename",
    "cat",
    "cmp",
    "cut",
    "date",
    "df",
    "diff",
    "dirname",
    "du",
    "echo",
    "false",
    "file",
    "grep",
    "head",
    "id",
    "jq",
    "ls",
    "md5",
    "md5sum",
    "pwd",
    "printf",
    "readlink",
    "realpath",
    "rg",
    "shasum",
    "sha256sum",
    "sort",
    "stat",
    "tail",
    "tee",
    "test",
    "tr",
    "true",
    "uname",
    "uniq",
    "wc",
    # `which` печатает путь к файлу и аргумент НЕ исполняет, поэтому слово `git`
    # в его argv не является вложенной командой. Пополнение списка одновременно
    # выключает скан guard'а на литеральную мутацию в аргументах (`which 'gh pr
    # merge 1'` → allow) — это разрешённое ослабление по плану U2-e5d9a §3.1,
    # верное ровно потому, что аргумент не исполняется.
    "which",
    "whoami",
}


def _starts_comment(text: str, index: int, continuations=frozenset()) -> bool:
    """Начинает ли ``#`` по индексу комментарий shell (вызывать вне кавычек).

    Правило живёт не здесь, а в общем модуле пакета ``shell_grammar``: обе
    копии уже расходились, и расхождение читалось как «пропустить». Обёртка
    оставлена только ради имени, привычного остальным сканерам файла.

    ``continuations`` — позиции закрывающих скобок подстановок, за которыми
    слово продолжается и решётка комментария НЕ открывает. Вычисляются один раз
    на текст через ``shell_grammar.word_continuation_positions``.
    """

    return shell_grammar.is_comment_start(
        text, index, word_continuations=continuations
    )


def _comment_end(text: str, index: int) -> int:
    """Конец комментария по общему правилу пакета."""

    return shell_grammar.comment_end(text, index)


def _comment_spans(text: str) -> List[Tuple[int, int]]:
    """Границы комментариев shell по общему сканеру пакета.

    Сканер учитывает кавычки, вложенность скобок и сами комментарии. Тела
    heredoc он не знает: их обязан замаскировать вызывающий, иначе решётка в
    данных команды будет принята за комментарий.
    """

    return shell_grammar.comment_spans(text)


def _blank_ranges(source: str, ranges: Iterable[Tuple[int, int]]) -> str:
    """Затирает диапазоны пробелами, сохраняя переводы строки-разделители."""

    masked = list(source)
    for start, end in ranges:
        for index in range(max(start, 0), min(end, len(masked))):
            if masked[index] not in "\r\n":
                masked[index] = " "
    return "".join(masked)


def _merge(classes: Iterable[CommandClass]) -> CommandClass:
    result = CommandClass.ORDINARY
    for candidate in classes:
        if _CLASS_PRIORITY[candidate] > _CLASS_PRIORITY[result]:
            result = candidate
    return result


def _classify_proven_inert_awk(command: str) -> Optional[CommandClass]:
    """Узкий fast-path для прямого literal awk без запуска внешних команд.

    Generic opaque-classifier правильно считает awk carrier'ом: awk умеет
    `system()`, pipe/coprocess и command-|getline. Но из-за этого обычное
    single-quoted поле `$1` выглядит shell-динамикой и становилось ambiguous.

    Здесь доказывается только узкая форма:
    - один прямой awk/gawk/mawk/nawk invocation;
    - программа — ОДИН single-quoted shell token (никакой shell expansion);
    - нет -f/--file и неизвестных options;
    - в программе нет известных execution primitives.

    Любая неопределённость возвращает None и уходит в общий fail-closed путь.
    """

    try:
        lexer = shlex.shlex(
            command, posix=False, punctuation_chars=";&|()<>\n"
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return None

    if not words:
        return None
    if any(
        token and set(token).issubset(_COMMAND_SEPARATORS | set("<>"))
        for token in words
    ):
        return None

    executable = _basename(words[0])
    if executable not in {"awk", "gawk", "mawk", "nawk"}:
        return None

    index = 1
    while index < len(words):
        option = words[index]
        if option == "--":
            index += 1
            break
        if option in ("-f", "--file") or option.startswith(("-f", "--file=")):
            return CommandClass.AMBIGUOUS
        if option in ("-F", "-v"):
            if index + 1 >= len(words):
                return CommandClass.AMBIGUOUS
            index += 2
            continue
        if option.startswith("-F") and option != "-F":
            index += 1
            continue
        if option.startswith("-v") and option != "-v":
            index += 1
            continue
        if option.startswith("-"):
            return None
        break

    if index >= len(words):
        return CommandClass.AMBIGUOUS

    raw_program = words[index]
    if len(raw_program) < 2 or not (
        raw_program.startswith("'") and raw_program.endswith("'")
    ):
        return None
    program = raw_program[1:-1]

    # Conservative execution surface. A bare pipe is blocked even inside an awk
    # regexp (e.g. /a|b/): false block is preferable to missing print|command.
    if re.search(r"(?<![A-Za-z0-9_])system\s*\(", program):
        return CommandClass.AMBIGUOUS
    if "|" in program:
        return CommandClass.AMBIGUOUS
    if re.search(r"(?<![A-Za-z0-9_])getline(?![A-Za-z0-9_])", program):
        return CommandClass.AMBIGUOUS
    if re.search(r"(^|[^A-Za-z0-9_])@load(?![A-Za-z0-9_])", program):
        return CommandClass.AMBIGUOUS

    # Program is proven not to have an external-execution primitive. Remaining
    # operands are awk data/assignments; active command substitutions outside
    # the single-quoted program are rejected before this proof is used.
    return CommandClass.ORDINARY


def _sed_program_is_proven_inert(program: str) -> bool:
    """Узкая доказуемо-инертная грамматика sed-программы.

    Доказывается НЕ «в программе нет опасного», а «программа целиком состоит из
    разрешённого». Перечислять опасное у sed нельзя: синтаксис контекстно
    зависим (адреса, произвольный разделитель у ``s``, фигурные блоки), и любой
    перечень «запрещённых букв» обходится сменой разделителя. Поэтому здесь
    whitelist: адрес плюс одна из команд печати/пропуска, ничего больше.

    Разрешено: ``p``, ``d``, ``q``, ``=`` с необязательным адресом ``N``,
    ``N,M``, ``$``, ``N,$``; несколько таких команд через ``;`` или перевод
    строки. Всё остальное — включая ``s///`` в любой форме, ``e``, ``w``/``W``,
    ``r``/``R``, фигурные блоки и отрицание ``!`` — доказательству не подлежит
    и уходит в общий консервативный путь.
    """

    parts = re.split(r"[;\n]", program)
    if not parts:
        return False
    for part in parts:
        if not re.fullmatch(
            r"\s*(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?\s*[pdq=]\s*", part
        ):
            return False
    return True


def _classify_proven_inert_sed(command: str) -> Optional[CommandClass]:
    """Узкий fast-path для прямого read-only sed без записи и запуска команд.

    Generic opaque-classifier правильно считает sed carrier'ом: у sed есть
    команда ``e`` и флаг ``s///e`` (запуск команды), ``w``/``W`` и флаг
    ``s///w`` (запись файла), ``r``/``R`` (чтение файла) и ``-i`` (правка на
    месте). Из-за этого обычное чтение диапазона строк — ``sed -n '1,5p'`` —
    становилось ambiguous, и после введения безусловного блока ambiguous любое
    чтение скрипта через sed перестало исполняться (Code Review PR #759, C-2).

    Здесь доказывается только узкая форма:
    - один прямой sed/gsed invocation, без разделителей команд и редиректов;
    - программа — ОДИН литеральный token без shell-раскрытия (single-quoted либо
      заведомо инертный набор символов), заданный операндом или через ``-e``;
    - программа целиком укладывается в whitelist ``_sed_program_is_proven_inert``;
    - из опций разрешены только заведомо read-only; ``-f``/``--file`` (текст
      программы не виден), ``-i``/``--in-place`` (запись), ``-s``/``--separate``
      и любая неизвестная опция доказательству не подлежат.

    Любая неопределённость возвращает ``None`` и уходит в общий fail-closed путь.
    Функция умеет только переводить ambiguous -> ordinary и никогда не ослабляет
    более сильный вердикт: ``CommandClass.COMMIT`` отсюда вернуться не может.
    """

    try:
        lexer = shlex.shlex(
            command, posix=False, punctuation_chars=";&|()<>\n"
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return None

    if not words:
        return None
    if any(
        token and set(token).issubset(_COMMAND_SEPARATORS | set("<>"))
        for token in words
    ):
        return None

    if _basename(words[0]) not in {"sed", "gsed"}:
        return None

    programs: List[str] = []
    operands: List[str] = []
    index = 1
    end_of_options = False
    while index < len(words):
        word = words[index]
        if end_of_options or not word.startswith("-") or word == "-":
            operands.append(word)
            index += 1
            continue
        if word == "--":
            end_of_options = True
            index += 1
            continue
        if word in ("-e", "--expression"):
            if index + 1 >= len(words):
                return None
            programs.append(words[index + 1])
            index += 2
            continue
        if word.startswith("--expression="):
            programs.append(word[len("--expression=") :])
            index += 1
            continue
        if word in _SED_PROVEN_READONLY_OPTIONS:
            index += 1
            continue
        if word.startswith("--"):
            return None
        # Слипшиеся короткие флаги: каждая буква обязана быть из доказанного
        # read-only набора. Одна незнакомая буква отменяет доказательство целиком.
        if not set(word[1:]) or not set(word[1:]).issubset(_SED_PROVEN_READONLY_SHORT):
            return None
        index += 1

    if not programs:
        if not operands:
            return None
        programs.append(operands.pop(0))

    for raw_program in programs:
        if _is_dynamic(raw_program):
            return None
        if len(raw_program) >= 2 and raw_program[0] == "'" and raw_program[-1] == "'":
            program = raw_program[1:-1]
            if "'" in program:
                return None
        elif set(raw_program).issubset(_SED_INERT_BARE_PROGRAM_CHARS):
            program = raw_program
        else:
            return None
        if not _sed_program_is_proven_inert(program):
            return None

    for operand in operands:
        if _is_dynamic(operand):
            return None

    # Программа доказанно состоит только из печати/пропуска строк, запись и
    # запуск команд ей недоступны, операнды — обычные пути без shell-раскрытия.
    return CommandClass.ORDINARY


def _basename(word: str) -> str:
    name = os.path.basename(word.rstrip("/"))
    # Git Bash выполняет имена через регистронезависимый Windows lookup как с
    # явным ``.exe``, так и без него. Нормализуем оба измерения вместе, иначе
    # ``GIT commit`` обходит классификатор, хотя запускает тот же git.exe.
    normalized = name.lower()
    return normalized[:-4] if normalized.endswith(".exe") else normalized


def _is_dynamic(word: str) -> bool:
    return bool(_DYNAMIC.search(word))


def _read_parenthesized(text: str, opening: int) -> Tuple[str, int, bool]:
    """Возвращает содержимое ``(...)``, индекс после него и признак закрытия."""

    depth = 0
    single = False
    double = False
    escaped = False
    index = opening
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not single:
            escaped = True
            index += 1
            continue
        if char == "'" and not double:
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            double = not double
            index += 1
            continue
        if single:
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index], index + 1, True
        index += 1
    return text[opening + 1 :], len(text), False


def _active_substitutions(command: str) -> Tuple[List[str], bool]:
    """Извлекает исполняемые ``$()``, backticks и process substitutions.

    Одинарные кавычки отключают подстановки; двойные — нет. Арифметическая
    подстановка ``$((...))`` исполняемой shell-командой не считается.
    """

    payloads: List[str] = []
    uncertain = False
    single = False
    double = False
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not single:
            escaped = True
            index += 1
            continue
        if char == "'" and not double:
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            double = not double
            index += 1
            continue
        if single:
            index += 1
            continue

        if command.startswith("$(", index):
            payload, end, closed = _read_parenthesized(command, index + 1)
            # Арифметика — только при смежном закрытии ``))``; ``$( (cmd) )`` с
            # несмежным закрытием оболочка исполняет как подстановку команды.
            arithmetic = command.startswith("$((", index) and _is_arithmetic_close(
                command, end
            )
            if arithmetic:
                # `$((` — всегда арифметика: shell ВЫЧИСЛЯЕТ выражение, а не
                # исполняет его как команду. Голое выражение (`w*h`, `2**8`)
                # командой не является, поэтому в общий список носителей НЕ
                # добавляется — иначе метасимвол `*` читался бы как glob и делал
                # обычную команду `x=$((w*h))` неоднозначной. Вложенные РЕАЛЬНЫЕ
                # подстановки внутри арифметики исполняются — их извлекаем.
                inner_payloads, inner_uncertain = _active_substitutions(payload)
                payloads.extend(inner_payloads)
                uncertain = uncertain or inner_uncertain
            else:
                payloads.append(payload)
            uncertain = uncertain or not closed
            index = end
            continue
        if char in "<>" and index + 1 < len(command) and command[index + 1] == "(":
            payload, end, closed = _read_parenthesized(command, index + 1)
            payloads.append(payload)
            uncertain = uncertain or not closed
            index = end
            continue
        if char == "`":
            end = index + 1
            tick_escaped = False
            while end < len(command):
                if tick_escaped:
                    tick_escaped = False
                elif command[end] == "\\":
                    tick_escaped = True
                elif command[end] == "`":
                    break
                end += 1
            if end >= len(command):
                uncertain = True
                index = len(command)
            else:
                payloads.append(command[index + 1 : end])
                index = end + 1
            continue
        index += 1
    return payloads, uncertain


def _mask_spans(source: str, spans: Sequence[_HeredocSpan]) -> str:
    return _blank_ranges(source, ((span.body_start, span.end) for span in spans))


def _arithmetic_spans(source: str) -> List[Tuple[int, int]]:
    """Границы арифметических раскрытий ``$((…))`` вне одинарных кавычек.

    Оболочка вычисляет содержимое ``$((…))`` как арифметику, а не исполняет его
    как команду, поэтому перед токенизацией такие участки затираются: иначе
    ``$((w*h))`` распалось бы на токены ``((``/``w*h``/``))`` и метасимвол ``*``
    читался бы как glob неизвестной команды. Реальные вложенные подстановки
    внутри арифметики извлекаются отдельно (`_active_substitutions`) ДО
    затирания, поэтому спрятанная в арифметике команда не теряется.
    """

    spans: List[Tuple[int, int]] = []
    single = False
    double = False
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not single:
            escaped = True
            index += 1
            continue
        if char == "'" and not double:
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            double = not double
            index += 1
            continue
        if not single and source.startswith("$((", index):
            _, end, closed = _read_parenthesized(source, index + 1)
            if closed and _is_arithmetic_close(source, end):
                spans.append((index, end))
                index = end
                continue
        index += 1
    return spans


def _is_arithmetic_close(source: str, end: int) -> bool:
    """Закрыта ли запись ``$((…))`` смежными ``))`` (тогда это арифметика).

    Оболочка исполняет ``$( (cmd) )`` (несмежное закрытие) как подстановку
    команды, а ``$((EXPR))`` со смежными ``))`` — как арифметику (невалидную —
    как синтаксическую ошибку, без запуска команды). ``end`` — индекс сразу за
    последней закрывающей скобкой.
    """

    return end >= 2 and source[end - 1] == ")" and source[end - 2] == ")"


def _heredoc_substitutions(body: str) -> Tuple[List[str], bool]:
    """Command substitutions раскрываемого heredoc; кавычки в body не защищают."""

    payloads: List[str] = []
    uncertain = False
    escaped = False
    index = 0
    while index < len(body):
        char = body[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if body.startswith("$(", index):
            payload, end, closed = _read_parenthesized(body, index + 1)
            arithmetic = body.startswith("$((", index) and _is_arithmetic_close(
                body, end
            )
            if arithmetic:
                # `$((` — всегда арифметика (shell вычисляет, не исполняет), в
                # том числе в раскрываемом heredoc. Голое выражение носителем не
                # является; извлекаем только вложенные реальные подстановки.
                inner_payloads, inner_uncertain = _heredoc_substitutions(payload)
                payloads.extend(inner_payloads)
                uncertain = uncertain or inner_uncertain
            else:
                payloads.append(payload)
            uncertain = uncertain or not closed
            index = end
            continue
        if char == "`":
            end = index + 1
            tick_escaped = False
            while end < len(body):
                if tick_escaped:
                    tick_escaped = False
                elif body[end] == "\\":
                    tick_escaped = True
                elif body[end] == "`":
                    break
                end += 1
            if end >= len(body):
                uncertain = True
                index = len(body)
            else:
                payloads.append(body[index + 1 : end])
                index = end + 1
            continue
        index += 1
    return payloads, uncertain
def _tokenize(command: str) -> Optional[List[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _segments(tokens: Sequence[str]) -> Iterable[List[str]]:
    current: List[str] = []
    for token in tokens:
        if token and set(token).issubset(_COMMAND_SEPARATORS):
            if current:
                yield current
                current = []
            continue
        current.append(token)
    if current:
        yield current


def _strip_prefixes(words: Sequence[str]) -> List[str]:
    """Снять служебные слова перед именем команды сегмента.

    `time` в набор `_CONTROL_PREFIXES` намеренно НЕ входит и здесь не снимается:
    он уходит в общий путь неизвестной обёртки исполнения, а тот консервативен —
    `time git commit -m x` классифицируется как `ambiguous`, то есть гейт всё равно
    запускается. Снимать `time` как управляющий префикс значило бы объявлять
    `time <что угодно>` обычной командой на основании догадки о синтаксисе
    конкретной оболочки (у bash-ключевого слова `time`, например, есть `-p`, но нет
    `--`), то есть ослаблять классификацию ради косметики.
    """
    result = list(words)
    while result:
        head = result[0]
        if head in _CONTROL_PREFIXES:
            result.pop(0)
            continue
        if _ASSIGNMENT.match(head):
            result.pop(0)
            continue
        if head in ("<", ">", "<<", ">>", "<>", ">&", "<&"):
            result = result[2:] if len(result) >= 2 else []
            continue
        if head.isdigit() and len(result) >= 2 and result[1].startswith(("<", ">")):
            result = result[3:] if len(result) >= 3 else []
            continue
        break
    return result


def _classify_command_wrapper(arguments: Sequence[str]) -> CommandClass:
    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option == "--":
            index += 1
            break
        if not option.startswith("-") or option == "-":
            break
        if _is_dynamic(option):
            return CommandClass.AMBIGUOUS
        if "v" in option[1:] or "V" in option[1:]:
            return CommandClass.ORDINARY
        if set(option[1:]).issubset({"p"}):
            index += 1
            continue
        return CommandClass.AMBIGUOUS
    return _classify_simple(arguments[index:])


def _split_env_string(value: str) -> Optional[List[str]]:
    if _is_dynamic(value):
        return None
    return _tokenize(value)


def _classify_env_wrapper(arguments: Sequence[str]) -> CommandClass:
    expanded = list(arguments)
    index = 0
    while index < len(expanded):
        word = expanded[index]
        if _ASSIGNMENT.match(word):
            index += 1
            continue
        if word == "--":
            index += 1
            break
        if not word.startswith("-") or word == "-":
            break
        if _is_dynamic(word):
            return CommandClass.AMBIGUOUS
        if word in ("-S", "--split-string"):
            if index + 1 >= len(expanded):
                return CommandClass.AMBIGUOUS
            split = _split_env_string(expanded[index + 1])
            if split is None:
                return CommandClass.AMBIGUOUS
            expanded = expanded[:index] + split + expanded[index + 2 :]
            continue
        if word.startswith("--split-string="):
            split = _split_env_string(word.split("=", 1)[1])
            if split is None:
                return CommandClass.AMBIGUOUS
            expanded = expanded[:index] + split + expanded[index + 1 :]
            continue
        if word in ("-u", "--unset", "-C", "--chdir"):
            if index + 1 >= len(expanded):
                return CommandClass.AMBIGUOUS
            index += 2
            continue
        if word.startswith(("--unset=", "--chdir=")):
            index += 1
            continue
        if word in ("-i", "--ignore-environment", "-0", "--null", "-v", "--debug"):
            index += 1
            continue
        if word.startswith("-") and set(word[1:]).issubset({"i", "0", "v"}):
            index += 1
            continue
        return CommandClass.AMBIGUOUS
    return _classify_simple(expanded[index:])


def _classify_exec_wrapper(arguments: Sequence[str]) -> CommandClass:
    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option == "--":
            index += 1
            break
        if not option.startswith("-") or option == "-":
            break
        if _is_dynamic(option):
            return CommandClass.AMBIGUOUS
        if option == "-a":
            if index + 1 >= len(arguments):
                return CommandClass.AMBIGUOUS
            index += 2
            continue
        if set(option[1:]).issubset({"c", "l"}):
            index += 1
            continue
        return CommandClass.AMBIGUOUS
    return _classify_simple(arguments[index:])


def _classify_builtin_wrapper(arguments: Sequence[str]) -> CommandClass:
    """Разрешает Bash ``builtin`` по семантике исполняющего builtin-target."""

    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option == "--":
            index += 1
            break
        if not option.startswith("-") or option == "-":
            break
        if _is_dynamic(option):
            return CommandClass.AMBIGUOUS
        if option == "-s":
            index += 1
            continue
        return CommandClass.AMBIGUOUS
    if index >= len(arguments):
        return CommandClass.ORDINARY

    target = arguments[index]
    if _is_dynamic(target):
        return CommandClass.AMBIGUOUS
    name = _basename(target)
    payload = arguments[index + 1 :]
    if name == "command":
        return _classify_command_wrapper(payload)
    if name == "exec":
        return _classify_exec_wrapper(payload)
    if name == "eval":
        return classify_command(" ".join(payload)) if payload else CommandClass.ORDINARY
    if name == "builtin":
        return _classify_builtin_wrapper(payload)
    return CommandClass.ORDINARY


def _classify_shell_carrier(arguments: Sequence[str]) -> CommandClass:
    if any(argument.startswith("<") for argument in arguments):
        return CommandClass.AMBIGUOUS

    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option == "--":
            return (
                CommandClass.ORDINARY
                if index + 1 < len(arguments)
                else CommandClass.AMBIGUOUS
            )
        if _is_dynamic(option):
            return CommandClass.AMBIGUOUS
        if not option.startswith(("-", "+")) or option in ("-", "+"):
            return CommandClass.ORDINARY
        if option in _SHELL_NO_EXEC_OPTIONS:
            return CommandClass.ORDINARY
        if option in _SHELL_OPERAND_OPTIONS:
            if index + 1 >= len(arguments):
                return CommandClass.AMBIGUOUS
            index += 2
            continue
        if option in _SHELL_NO_OPERAND_OPTIONS:
            index += 1
            continue
        if option.startswith("--"):
            return CommandClass.AMBIGUOUS
        flags = option[1:]
        if "c" in flags:
            payload_index = index + 1
            if payload_index < len(arguments) and arguments[payload_index] == "--":
                payload_index += 1
            if payload_index >= len(arguments):
                return CommandClass.AMBIGUOUS
            payload = arguments[payload_index]
            if payload.startswith(("$", "`")):
                return CommandClass.AMBIGUOUS
            return classify_command(payload)
        if "s" in flags:
            return CommandClass.AMBIGUOUS
        if not flags or not all(flag in _SHELL_SHORT_FLAG_CHARS for flag in flags):
            return CommandClass.AMBIGUOUS
        index += 1
    return CommandClass.AMBIGUOUS


def _git_config_value(option: str, following: Optional[str]) -> Tuple[Optional[str], int]:
    if option == "-c":
        return following, 2
    if option.startswith("-c") and option != "-c":
        return option[2:], 1
    return None, 0


def _alias_from_config(config: str) -> Optional[Tuple[str, str]]:
    if "=" not in config:
        return None
    key, value = config.split("=", 1)
    if not key.lower().startswith("alias."):
        return None
    return key[6:], value


def _alias_from_config_env(config: str) -> Optional[str]:
    if "=" not in config or _is_dynamic(config):
        return None
    key, environment_name = config.split("=", 1)
    if not environment_name or not key.lower().startswith("alias."):
        return None
    return key[6:]


def _classify_git(arguments: Sequence[str]) -> CommandClass:
    aliases = {}
    unknown_alias_values = set()
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if _is_dynamic(word):
            return CommandClass.AMBIGUOUS
        if word == "--":
            index += 1
            break
        config, consumed = _git_config_value(
            word, arguments[index + 1] if index + 1 < len(arguments) else None
        )
        if consumed:
            if config is None:
                return CommandClass.AMBIGUOUS
            alias = _alias_from_config(config)
            if alias:
                name, value = alias
                aliases[name] = value
                if _is_dynamic(value):
                    unknown_alias_values.add(name)
            index += consumed
            continue
        if word == "--config-env" or word.startswith("--config-env="):
            if word == "--config-env":
                if index + 1 >= len(arguments):
                    return CommandClass.AMBIGUOUS
                config_env = arguments[index + 1]
                consumed = 2
            else:
                config_env = word.split("=", 1)[1]
                consumed = 1
            if _is_dynamic(config_env) or "=" not in config_env:
                return CommandClass.AMBIGUOUS
            alias_name = _alias_from_config_env(config_env)
            if alias_name:
                unknown_alias_values.add(alias_name)
            index += consumed
            continue
        # `-h` признаётся чтением только терминально: сам по себе он печатает
        # краткую справку, но `git -h <подкоманда>` ведёт себя как `git help
        # <подкоманда>` и запускает просмотрщик справки из конфигурации. Форма с
        # остатком уходит ниже в общий отказ по неизвестной опции — ровно то
        # поведение, что было до этой правки (Code Review, BLOCKER 1).
        if word == "-h" and index + 1 >= len(arguments):
            index += 1
            continue
        if word in _GIT_NO_VALUE_OPTIONS:
            index += 1
            continue
        if word in _GIT_VALUE_OPTIONS:
            if index + 1 >= len(arguments):
                return CommandClass.AMBIGUOUS
            index += 2
            continue
        if word.startswith(_GIT_VALUE_PREFIXES):
            index += 1
            continue
        if word == "--exec-path":
            index += 1
            continue
        if word.startswith("-"):
            return CommandClass.AMBIGUOUS
        break

    if index >= len(arguments):
        return CommandClass.ORDINARY
    subcommand = arguments[index]
    if _is_dynamic(subcommand):
        return CommandClass.AMBIGUOUS
    if subcommand == "commit":
        return CommandClass.COMMIT
    if subcommand in unknown_alias_values:
        return CommandClass.AMBIGUOUS
    if subcommand in aliases:
        expansion = aliases[subcommand]
        if expansion.startswith("!"):
            return classify_command(expansion[1:])
        expanded = _tokenize(expansion)
        if expanded is None:
            return CommandClass.AMBIGUOUS
        return _classify_git(expanded + list(arguments[index + 1 :]))
    if subcommand in _STABLE_BUILTIN_GIT_SUBCOMMANDS:
        return CommandClass.ORDINARY
    if _is_non_commit_sequencer_form(subcommand, arguments[index + 1 :]):
        return CommandClass.ORDINARY
    return CommandClass.AMBIGUOUS


def _is_non_commit_sequencer_form(
    subcommand: str, rest: Sequence[str]
) -> bool:
    """Формы секвенсора git, которые заведомо НЕ создают коммит.

    `cherry-pick`/`revert`/`am` держатся вне allowlist потому, что в обычной
    форме создают коммит на текущей ветке, а `bisect` — потому что
    `bisect run <cmd>` исполняет переданную команду. Но `--abort`/`--quit` и
    `bisect reset` коммита не создают и ничего не исполняют: это выход из уже
    начатой операции. До этой правки единственная штатная команда выхода из
    конфликта была недоступна — агент, попавший в конфликт cherry-pick/am/revert,
    не мог из него выйти (Code Review PR #759, C-2).

    Доказательство узкое и позиционное: ровно один аргумент нужной формы и
    ничего больше. `--continue` и `--skip` продолжают операцию и коммит создать
    могут — они здесь НЕ перечислены и остаются консервативными.
    """

    tail = list(rest)
    if len(tail) != 1:
        return False
    argument = tail[0]
    if _is_dynamic(argument):
        return False
    if subcommand in {"cherry-pick", "revert", "am"}:
        return argument in {"--abort", "--quit"}
    if subcommand == "bisect":
        return argument == "reset"
    return False


def _classify_execution_candidates(words: Sequence[str]) -> CommandClass:
    """Проверяет только позиции, похожие на вложенный executable/payload."""

    for index in range(len(words)):
        head = words[index]
        if _is_dynamic(head):
            tail = words[index + 1 :]
            git_tail = _classify_git(tail)
            if git_tail is CommandClass.COMMIT or (
                git_tail is CommandClass.AMBIGUOUS
                and any(_is_dynamic(word) or word == "commit" for word in tail)
            ):
                return CommandClass.AMBIGUOUS
            continue
        nested = _classify_simple(words[index:], inspect_opaque=False)
        if nested is not CommandClass.ORDINARY:
            return CommandClass.AMBIGUOUS
        if _basename(head) == "git" and _classify_git(
            list(words[index + 1 :]) + ["$U2_UNKNOWN_SUBCOMMAND"]
        ) is CommandClass.AMBIGUOUS:
            return CommandClass.AMBIGUOUS
    return CommandClass.ORDINARY


def _classify_embedded_git_literal(payload: str) -> CommandClass:
    """Находит literal Git-команду внутри непрозрачного исполняемого payload.

    Кавычки, скобки и запятые разных языков считаются разделителями. Это
    закрывает один класс для Python/Node/Ruby и будущих code carriers без
    перечисления интерпретаторов; известные data-only команды не доходят до
    opaque scan.
    """

    words = _LITERAL_CODE_WORD.findall(payload)
    for index, word in enumerate(words):
        if _basename(word) != "git":
            continue
        nested = _classify_git(words[index + 1 :])
        if nested is not CommandClass.ORDINARY:
            return CommandClass.AMBIGUOUS
    return CommandClass.ORDINARY


def _classify_xargs_wrapper(arguments: Sequence[str]) -> CommandClass:
    """Xargs может добавить argv из stdin; dynamic utility потому непрозрачна."""

    if any(_is_dynamic(argument) for argument in arguments):
        return CommandClass.AMBIGUOUS

    replacements = []
    payload_words = []
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "-i":
            replacements.append("{}")
            index += 1
            continue
        if word.startswith("-i") and len(word) > 2:
            replacements.append(word[2:])
            index += 1
            continue
        if word in ("-I", "-J"):
            if index + 1 >= len(arguments) or not arguments[index + 1]:
                return CommandClass.AMBIGUOUS
            replacements.append(arguments[index + 1])
            index += 2
            continue
        if (word.startswith("-I") or word.startswith("-J")) and len(word) > 2:
            replacements.append(word[2:])
            index += 1
            continue
        if word == "--replace":
            replacements.append("{}")
            index += 1
            continue
        if word.startswith("--replace="):
            replacement = word.split("=", 1)[1]
            if not replacement:
                return CommandClass.AMBIGUOUS
            replacements.append(replacement)
            index += 1
            continue
        payload_words.append(word)
        index += 1

    if any(
        replacement in word
        for replacement in replacements
        for word in payload_words
    ):
        return CommandClass.AMBIGUOUS
    return _classify_opaque_wrapper(arguments)


def _classify_opaque_wrapper(arguments: Sequence[str]) -> CommandClass:
    """Ищет возможную вложенную команду в операндах неизвестного executable.

    Формат опций неизвестен, поэтому нельзя надёжно выбрать единственную точку
    начала команды. Проверяются отдельные literal payload'ы (включая значение
    после ``option=``) и literal суффиксы argv. Динамический data-аргумент после
    доказанного subcommand не является кандидатом; dynamic executable прямо
    перед ``commit`` остаётся fail-closed. Git без subcommand тоже кандидат:
    xargs может дописать ``commit`` через stdin. Вложенный opaque-scan для
    суффиксов выключен, чтобы произвольные слова не рекурсировали.
    """

    for argument in arguments:
        payloads = [(argument, False)]
        if "=" in argument:
            payloads.append((argument.split("=", 1)[1], True))
        for payload, option_value in payloads:
            if not payload:
                continue
            dynamic = _is_dynamic(payload)
            if _classify_embedded_git_literal(payload) is not CommandClass.ORDINARY:
                return CommandClass.AMBIGUOUS
            if not dynamic and classify_command(payload) is not CommandClass.ORDINARY:
                return CommandClass.AMBIGUOUS
            shell_payload = option_value or any(
                character.isspace() or character in ";&|()\n"
                for character in payload
            )
            if not shell_payload:
                continue
            payload_tokens = _tokenize(payload)
            if payload_tokens is None:
                if not dynamic:
                    return CommandClass.AMBIGUOUS
                continue
            payload_class = _merge(
                _classify_execution_candidates(segment)
                for segment in _segments(payload_tokens)
            )
            if payload_class is not CommandClass.ORDINARY:
                return CommandClass.AMBIGUOUS

    if _classify_execution_candidates(arguments) is not CommandClass.ORDINARY:
        return CommandClass.AMBIGUOUS
    return CommandClass.ORDINARY


def _classify_simple(
    words: Sequence[str], *, inspect_opaque: bool = True
) -> CommandClass:
    command = _strip_prefixes(words)
    if not command:
        return CommandClass.ORDINARY

    executable = command[0]
    if _is_dynamic(executable):
        return CommandClass.AMBIGUOUS
    name = _basename(executable)
    arguments = command[1:]

    if name == "command":
        return _classify_command_wrapper(arguments)
    if name == "env":
        return _classify_env_wrapper(arguments)
    if name == "exec":
        return _classify_exec_wrapper(arguments)
    if name == "builtin":
        return _classify_builtin_wrapper(arguments)
    if name == "xargs":
        return _classify_xargs_wrapper(arguments)
    if name == "git":
        return _classify_git(arguments)
    if name == "eval":
        if not arguments:
            return CommandClass.ORDINARY
        return classify_command(" ".join(arguments))
    if name.endswith("sh"):
        return _classify_shell_carrier(arguments)
    if name in _NON_CARRIER_COMMANDS or not inspect_opaque:
        return CommandClass.ORDINARY
    return _classify_opaque_wrapper(arguments)


def _inert_free_text(command: str, heredocs: Sequence[_HeredocSpan]) -> str:
    """Оставить текст, который разбор НЕ доказал инертным.

    Доказанно инертны только три вида содержимого: строка в одинарных кавычках
    (никаких раскрытий), комментарий shell и тело heredoc (данные команды; его
    подстановки классифицируются отдельным проходом). Всё остальное остаётся,
    даже если разбор счёл его безвредным.

    Разбор идёт по тексту с УЖЕ замаскированными телами heredoc — тем же и в том
    же порядке, что на основном пути. Иначе кавычка или решётка в данных команды
    сбивали бы состояние разбора, и запасной вердикт расходился бы с основным
    путём в том, что считать комментарием.
    """

    source = _mask_spans(command, heredocs)
    masked = list(source)

    def blank(start: int, end: int):
        for position in range(start, min(end, len(masked))):
            if masked[position] not in "\r\n":
                masked[position] = " "

    # Границы комментариев берутся из единственного сканера файла, а не
    # вычисляются здесь заново: расхождение двух представлений о комментарии и
    # было причиной, по которой основной путь разбора и запасной вердикт
    # расходились в том, что считать инертным.
    comments = dict(_comment_spans(source))

    single_start = None
    double = False
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if single_start is not None:
            if char == "'":
                blank(single_start, index + 1)
                single_start = None
            index += 1
            continue
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == '"':
            double = not double
            index += 1
            continue
        if char == "'" and not double:
            single_start = index
            index += 1
            continue
        if index in comments:
            end = comments[index]
            blank(index, end)
            index = end
            continue
        index += 1
    if single_start is not None:
        blank(single_start, len(source))

    # Отдельного прохода по телам heredoc не требуется: ``_mask_spans`` уже
    # затёр их вместе с завершителем.
    return "".join(masked)


def _residual_commit_candidate(text: str) -> bool:
    """Признак связки ``git``+``commit`` в тексте, не доказанном инертным.

    Запасной признак намеренно грубый: он смотрит на исходный текст, а не на
    результат разбора, поэтому не зависит от того, совпал ли разбор с shell.
    Срабатывание сужено до подкоманды ``commit`` (в том числе через inline-alias
    и глобальные опции Git): неизвестная подкоманда сюда не попадает, её
    разбирает основной проход. Иначе обычный текст со словом «git» давал бы
    лишние прогоны.
    """

    words = _LITERAL_CODE_WORD.findall(text)
    for index, word in enumerate(words):
        if _basename(word) != "git":
            continue
        if _classify_git(words[index + 1 :]) is CommandClass.COMMIT:
            return True
    return False


def classify_command(command: str) -> CommandClass:
    """Классифицирует полный Bash command string без исполнения shell."""

    if not command.strip():
        return CommandClass.ORDINARY

    # Shell склеивает перенос строки обратной косой чертой до разбора — та же
    # нормализация выполняется первой, иначе связка команды распадалась бы.
    command = _splice_line_continuations(command)

    # Границы heredoc ищутся по источнику с ЗАТЁРТОЙ арифметикой: оператор сдвига
    # ``<<`` внутри ``$((x<<2))`` иначе принимается за начало heredoc. Затирание
    # сохраняет длины и позиции, поэтому найденные границы применимы к исходному
    # тексту; сама арифметика в исходнике сохраняется для извлечения вложенных
    # подстановок ниже.
    arithmetic_blanked = _blank_ranges(command, _arithmetic_spans(command))
    heredocs, uncertain_heredoc = _heredoc_spans(arithmetic_blanked)
    shell_source = _mask_spans(command, heredocs)
    # Комментарии затираются ПОСЛЕ маскирования тел heredoc и ДО извлечения
    # подстановок и токенизации. Порядок обязателен: тела heredoc уже обнулены,
    # поэтому решётка в данных команды не будет принята за комментарий, а разбор
    # дальше видит ровно тот текст, который shell исполняет. Без этого шага
    # ``#`` доходил до токенизации отдельным словом и становился неизвестным
    # носителем команды: безобидный комментарий давал вердикт ambiguous и гонял
    # тесты. Перевод строки сохраняется — он разделитель команд.
    shell_source = _blank_ranges(shell_source, _comment_spans(shell_source))
    substitutions, uncertain_substitution = _active_substitutions(shell_source)
    for heredoc in heredocs:
        if not heredoc.expands:
            continue
        payloads, uncertain = _heredoc_substitutions(
            command[heredoc.body_start : heredoc.body_end]
        )
        substitutions.extend(payloads)
        uncertain_substitution = uncertain_substitution or uncertain
    nested = [classify_command(payload) for payload in substitutions]
    if uncertain_substitution or uncertain_heredoc:
        nested.append(CommandClass.AMBIGUOUS)

    # Narrow awk fast-path is valid only when no active nested execution was
    # discovered outside its single-quoted program.
    if not substitutions and not uncertain_substitution and not uncertain_heredoc:
        awk_proof = _classify_proven_inert_awk(shell_source)
        if awk_proof is not None:
            return awk_proof
        sed_proof = _classify_proven_inert_sed(shell_source)
        if sed_proof is not None:
            return sed_proof

    # Арифметика затирается ПОСЛЕ извлечения вложенных подстановок и ДО
    # токенизации: её голое выражение командой не является, а спрятанные в ней
    # реальные подстановки уже разобраны через ``substitutions``/``nested``.
    tokenize_source = _blank_ranges(shell_source, _arithmetic_spans(shell_source))
    tokens = _tokenize(tokenize_source)
    if tokens is None:
        return _merge(nested + [CommandClass.AMBIGUOUS])
    direct = [_classify_simple(segment) for segment in _segments(tokens)]
    verdict = _merge(nested + direct)

    # Запасной вердикт: разбор вручную никогда не совпадёт с полной грамматикой
    # shell, поэтому умолчание смещено с «не доказано, что это commit —
    # пропускаем» на «не доказано, что инертно — проверяем». Если разбор пришёл
    # к ordinary, но связка git+commit осталась в тексте, не доказанном
    # инертным, вердикт становится ambiguous и гейт прогоняет тесты. Цена
    # расхождения разбора с shell — лишний прогон, а не пропущенный commit.
    if verdict is CommandClass.ORDINARY and _residual_commit_candidate(
        _inert_free_text(command, heredocs)
    ):
        return CommandClass.AMBIGUOUS
    return verdict


def _command_from_hook_payload(raw: str) -> str:
    payload = json.loads(raw)
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        raise ValueError("tool_input.command отсутствует или не является строкой")
    return tool_input["command"]


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("classify", "classify-hook"):
        print("usage: commit_command_classifier.py classify|classify-hook", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    try:
        command = _command_from_hook_payload(raw) if argv[1] == "classify-hook" else raw
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"не удалось разобрать вход commit-gate: {error}", file=sys.stderr)
        return 2
    print(classify_command(command).value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
