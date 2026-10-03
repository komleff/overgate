#!/usr/bin/env python3
"""Единое правило shell-грамматики «где начинается слово и где комментарий».

Причина существования: правило было продублировано в двух разборщиках пакета —
`shell_comment_parser.py` (гейт публикации) и `commit_command_classifier.py`
(гейт коммита). Наборы метасимволов разошлись: у первого стоял `;|&(){}`, у
второго `;&|()<>`. Оболочка согласна со вторым — закрывающая фигурная скобка
границей слова НЕ является, поэтому запись вида `${x}#y` решётку комментарием не
делает, и остаток строки исполняется. Разошедшаяся копия гасила этот остаток
вместе с публикацией, то есть гейт пропускал запись, которую живой bash
исполняет.

Вторая причина: круглая скобка МНОГОЗНАЧНА. Закрывающая скобка подстановки
(`$( )`, `$(( ))`, `<( )`, `>( )`) остаётся частью СЛОВА: решётка сразу за ней
комментария не открывает, и оболочка исполняет остаток строки. Закрывающая
скобка настоящей подоболочки — конец команды, и решётка за ней комментарий
открывает. Правило, которое видит только сам символ, эти случаи различить не
может, поэтому позиции «слово продолжается» оно принимает вторым входом.
Вычисляет их либо вызывающий разборщик (он ведёт контекст сам), либо общий
сканер `comment_spans` ниже.

Правило живёт здесь в одном экземпляре. `shell_comment_parser.py` и
`commit_command_classifier.py` ИМПОРТИРУЮТ его напрямую; собственных копий
набора или функции у них нет. Единственность источника проверяется тестом
`scripts/tests/shell-grammar-single-source.test.sh`.

Расширять набор нельзя: каждый лишний символ превращает исполняемую запись в
«доказанно инертную» и открывает пропуск. Сужать — тоже нельзя: пропадёт
распознавание настоящего комментария, и в разбор попадёт мусор.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Container, List, Optional, Set, Tuple

# Метасимволы shell, после которых начинается новое слово. Ровно этот набор
# (плюс пробельные символы и начало строки) открывает комментарий.
#
# Проверка на живом bash: `;` `&` `|` `(` `)` `<` `>` разделяют слова, поэтому
# `echo a;#b` печатает `a`, а решётка начинает комментарий. Фигурные скобки
# метасимволами НЕ являются: `echo ${x}#y` печатает `#y`, то есть решётка после
# `}` — обычный символ слова, а не начало комментария.
COMMENT_START_METACHARACTERS = frozenset(";&|()<>")

# Начала конструкций, чья закрывающая круглая скобка остаётся ВНУТРИ слова.
# Подстановка команды и арифметическая подстановка начинаются одинаково (`$(`),
# поэтому отдельной записи для `$((` не нужно: внутренняя скобка учитывается
# общим счётом вложенности, а слово завершает внешняя.
#
# Extglob-шаблоны (`@( ?( *( +( !(`) — тоже часть слова: `echo @(a|b)#c` печатает
# `@(a|b)#c`, то есть решётка сразу за закрывающей скобкой шаблона комментария не
# открывает. Их закрывающая скобка обрабатывается так же, как у подстановок.
_EXTGLOB_OPENERS = ("@(", "?(", "*(", "+(", "!(")
_WORD_LEVEL_OPENERS = ("$(", "<(", ">(") + _EXTGLOB_OPENERS

# Внутри двойных кавычек подстановка команды работает, а подстановка процесса и
# extglob — нет: `"<(x)"` и `"@(x)"` оболочка считает обычным текстом.
_WORD_LEVEL_OPENERS_IN_DOUBLE_QUOTES = ("$(",)


def is_comment_start(
    text: str, index: int, *, word_continuations: Container[int] = frozenset()
) -> bool:
    """Начинает ли символ по индексу `index` комментарий shell.

    Ответ утвердительный только когда символ — решётка И стоит в начале слова:
    в начале текста, после пробельного символа или после метасимвола из
    `COMMENT_START_METACHARACTERS`.

    `word_continuations` — индексы символов, которые по написанию выглядят
    метасимволом, но в разобранном контексте остались частью слова. Сегодня это
    закрывающие скобки подстановок. Позиция в этом наборе снимает вердикт
    «начало комментария»: слово продолжается, значит остаток строки оболочка
    ИСПОЛНИТ, и разбор обязан его увидеть.

    Ошибка в сторону «это комментарий» ослепляет гейт: остаток строки, который
    оболочка ИСПОЛНЯЕТ, разбор молча отбрасывает. Поэтому сомнительные формы
    (`foo#bar`, `X=#value`, `${#var}`) комментарием не считаются и доходят до
    разбора как код.

    Кавычки, экранирование и тела heredoc этой функции не видны — их обязан
    учитывать вызывающий: внутри кавычек и в теле heredoc решётка комментарий
    не открывает.
    """

    if index < 0 or index >= len(text) or text[index] != "#":
        return False
    if index == 0:
        return True
    if index - 1 in word_continuations:
        return False
    previous = text[index - 1]
    return previous.isspace() or previous in COMMENT_START_METACHARACTERS


def comment_end(text: str, index: int) -> int:
    """Конец комментария — перевод строки, который сам ОСТАЁТСЯ в потоке.

    Перевод строки разделяет команды: съев его вместе с комментарием, разбор
    склеил бы комментарий со следующей строкой и потерял её как команду.
    """

    line_end = text.find("\n", index)
    return len(text) if line_end < 0 else line_end


def comment_spans(text: str) -> List[Tuple[int, int]]:
    """Границы комментариев shell по общему сканеру (см. `_scan`)."""

    return _scan(text)[0]


def word_continuation_positions(text: str) -> Set[int]:
    """Позиции закрывающих скобок подстановок — там слово продолжается.

    Нужны сканерам, которые ведут собственный обход текста (поиск heredoc,
    склейка переносов) и потому не могут воспользоваться готовыми границами
    комментариев, но обязаны отвечать на вопрос «комментарий ли это» тем же
    правилом.
    """

    return _scan(text)[1]


def _scan(text: str) -> Tuple[List[Tuple[int, int]], Set[int]]:
    """Единственный сканер комментариев и границ слова в пакете.

    Сканер ведёт три вещи разом, потому что порознь они дают неверный ответ:

    * кавычки — внутри одинарных и двойных решётка комментария не открывает;
    * вложенность круглых скобок с различением «подстановка» и «подоболочка» —
      закрывающая скобка подстановки остаётся внутри слова;
    * сами комментарии — внутри комментария кавычка состояние не меняет,
      поэтому комментарий перескакивается целиком, как это делает оболочка.

    Внутри подстановки разбор идёт заново: кавычки снаружи на её тело не
    действуют, а по закрытии прежнее состояние кавычек восстанавливается.

    Тела heredoc сканер не знает: их обязан замаскировать вызывающий, иначе
    решётка в данных команды будет принята за комментарий.
    """

    spans: List[Tuple[int, int]] = []
    word_continuations: Set[int] = set()
    # Стек открытых скобок: (это_подстановка, состояние_кавычек_снаружи).
    stack: List[Tuple[bool, Optional[str]]] = []
    quote: Optional[str] = None
    escaped = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if char == "'" and quote is None:
            quote = "'"
            index += 1
            continue
        if char == "'" and quote == "'":
            quote = None
            index += 1
            continue
        if char == '"' and quote is None:
            quote = '"'
            index += 1
            continue
        if char == '"' and quote == '"':
            quote = None
            index += 1
            continue

        if quote != "'":
            openers = (
                _WORD_LEVEL_OPENERS
                if quote is None
                else _WORD_LEVEL_OPENERS_IN_DOUBLE_QUOTES
            )
            opener = next(
                (item for item in openers if text.startswith(item, index)), None
            )
            if opener is not None:
                stack.append((True, quote))
                quote = None
                index += len(opener)
                continue

        if quote is None:
            if char == "(":
                stack.append((False, None))
                index += 1
                continue
            if char == ")":
                if stack:
                    substitution, outer_quote = stack.pop()
                    quote = outer_quote
                    if substitution:
                        word_continuations.add(index)
                index += 1
                continue
            if is_comment_start(text, index, word_continuations=word_continuations):
                end = comment_end(text, index)
                spans.append((index, end))
                index = end
                continue

        index += 1

    return spans, word_continuations


# ---------------------------------------------------------------------------
# Продолжение строки и границы тел heredoc — общая нормализация на пакет.
#
# Оболочка убирает пару «обратная косая черта + перевод строки» ещё ДО разбиения
# на слова, поэтому такая запись — одна команда, а не две. Оба разборщика пакета
# (гейт коммита и гейт публикации через `analyze_shell`) обязаны выполнять эту
# нормализацию первым шагом, иначе перевод строки читается как разделитель
# команд и связка `gh ... pr ... comment` / `git ... commit` распадается — а это
# ПРОПУСК публикации мимо гейта, не лишняя блокировка. Правило и его heredoc-
# зависимости живут здесь в одном экземпляре; оба разборщика их импортируют.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeredocSpan:
    """Границы тела heredoc и признак раскрытия его содержимого."""

    body_start: int
    body_end: int
    end: int
    expands: bool


def read_heredoc_word(text: str, start: int) -> Tuple[str, int, bool, bool]:
    """Снять кавычки с разделителя heredoc без раскрытия.

    Возвращает (разделитель, индекс за ним, был ли он в кавычках, точен ли он).
    Разделитель в кавычках делает тело heredoc нераскрываемым; неточный (с
    незавершённой парой) переводит разбор в неопределённость.
    """

    value: List[str] = []
    quoted = False
    single = False
    double = False
    index = start
    while index < len(text):
        char = text[index]
        if not single and not double and (char.isspace() or char in ";|&()<>"):
            break
        if char == "'" and not double:
            quoted = True
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            quoted = True
            double = not double
            index += 1
            continue
        if char == "\\" and not single:
            quoted = True
            if index + 1 >= len(text) or text[index + 1] == "\n":
                return "".join(value), index, quoted, False
            value.append(text[index + 1])
            index += 2
            continue
        value.append(char)
        index += 1
    return "".join(value), index, quoted, not single and not double and bool(value)


def heredoc_spans(command: str) -> Tuple[List[HeredocSpan], bool]:
    """Найти тела heredoc, чтобы их строки не принимались за shell-команды."""

    spans: List[HeredocSpan] = []
    pending: List[Tuple[str, bool, bool]] = []
    uncertain = False
    single = False
    double = False
    escaped = False
    index = 0
    # Решётка за закрывающей скобкой подстановки комментария не открывает —
    # позиции берутся у общего сканера, отдельного представления здесь нет.
    continuations = word_continuation_positions(command)
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

        # Комментарий распознаётся ДО метки heredoc: внутри комментария метка
        # инертна, и следующие строки остаются командами, а не данными.
        if not single and not double and is_comment_start(
            command, index, word_continuations=continuations
        ):
            index = comment_end(command, index)
            continue

        if not single and not double and command.startswith("<<", index) \
                and not command.startswith("<<<", index):
            cursor = index + 2
            strip_tabs = False
            if cursor < len(command) and command[cursor] == "-":
                strip_tabs = True
                cursor += 1
            while cursor < len(command) and command[cursor] in " \t":
                cursor += 1
            delimiter, end, quoted, exact = read_heredoc_word(command, cursor)
            if not exact:
                uncertain = True
            else:
                pending.append((delimiter, strip_tabs, not quoted))
            index = max(end, cursor + 1)
            continue

        if char == "\n" and pending and not single and not double:
            cursor = index + 1
            for delimiter, strip_tabs, expands in pending:
                body_start = cursor
                found = False
                while cursor <= len(command):
                    line_end = command.find("\n", cursor)
                    if line_end < 0:
                        line_end = len(command)
                    line = command[cursor:line_end].rstrip("\r")
                    comparable = line.lstrip("\t") if strip_tabs else line
                    if comparable == delimiter:
                        terminator_end = line_end + (1 if line_end < len(command) else 0)
                        spans.append(
                            HeredocSpan(body_start, cursor, terminator_end, expands)
                        )
                        cursor = terminator_end
                        found = True
                        break
                    if line_end >= len(command):
                        break
                    cursor = line_end + 1
                if not found:
                    spans.append(
                        HeredocSpan(body_start, len(command), len(command), expands)
                    )
                    uncertain = True
                    cursor = len(command)
                    break
            pending.clear()
            index = cursor
            continue
        index += 1

    if pending:
        uncertain = True
    return spans, uncertain


def splice_line_continuations(command: str) -> str:
    """Убрать продолжение строки (`\\`+перевод строки) КОНТЕКСТНО, до разбора.

    Роль обратной косой черты оболочка определяет по контексту, и проход
    повторяет его ровно, иначе состояние кавычек разъезжается:

    * вне кавычек — перед переводом строки склеивает, перед любым другим
      символом экранирует его (пара проходит целиком, и, в частности, ``\\'``
      строку не открывает);
    * в двойных кавычках — перед переводом строки склеивает, иначе пара проходит
      целиком; важно, что ``\\"`` двойные кавычки не закрывает;
    * в одинарных кавычках — БУКВАЛЬНА: ничего не экранирует и склейки не даёт, а
      строку закрывает первая же одинарная кавычка;
    * в комментарии — обратная косая черта в его конце его НЕ продлевает: строка
      после комментария исполняется, склеивать её с комментарием нельзя;
    * в теле heredoc — данные команды: кавычка там состояние не меняет и склейки
      нет; границы тел даёт общий сканер `heredoc_spans`.

    Поддержаны оба вида перевода строки. Экранированная обратная косая черта (две
    подряд) переносом не является и сохраняется.
    """

    bodies = {span.body_start: span.body_end for span in heredoc_spans(command)[0]}

    result: List[str] = []
    index = 0
    length = len(command)
    single = False
    double = False
    in_comment = False
    continuations = word_continuation_positions(command)
    while index < length:
        char = command[index]
        body_end = bodies.get(index)
        if body_end is not None and body_end > index:
            result.append(command[index:body_end])
            index = body_end
            # Тело heredoc идёт сразу за завершённой командной строкой: кавычки
            # закрыты, комментарий закончен. Состояние сбрасывается явно.
            single = False
            double = False
            in_comment = False
            continue
        if in_comment:
            if char == "\n":
                in_comment = False
            result.append(char)
            index += 1
            continue
        if single:
            if char == "'":
                single = False
            result.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < length:
            following = command[index + 1]
            if following == "\n":
                index += 2
                continue
            if (
                following == "\r"
                and index + 2 < length
                and command[index + 2] == "\n"
            ):
                index += 3
                continue
            # Экранированный символ переносом не является: сохраняем пару целиком.
            result.append(char)
            result.append(following)
            index += 2
            continue
        if char == "'" and not double:
            single = True
        elif char == '"':
            double = not double
        elif not double and is_comment_start(
            command, index, word_continuations=continuations
        ):
            in_comment = True
        result.append(char)
        index += 1
    return "".join(result)
