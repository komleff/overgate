#!/usr/bin/env python3
"""Единая политика запрета деклараций merge-readiness вне finalize-pr.

Два инварианта, оплаченные разбором дефектов:

1. **Фаза ограничена по времени.** Проверка формулировки — отдельная фаза после
   разбора команды, и раньше она шла без предела. Стоимость росла квадратично по
   числу кандидатов в одной строке, поэтому длинный вход съедал бюджет
   обработчика целиком: диспетчер снимал обработчик, а снятый обработчик кода
   выхода не возвращает и блокирует только код 2. Теперь фаза принимает дедлайн,
   а его истечение — исключение, которое вызывающий обязан трактовать как
   блокировку. Заодно проход по кандидатам сделан линейным: границы строки,
   маркер цитаты и начало клаузы считаются нарастающим итогом, а не пересчётом
   всего префикса строки на каждом кандидате.

2. **Декларация запрещена НЕЗАВИСИМО от продолжения после «merge».** Прежний
   набор терминаторов сначала был узок (только пунктуация Po/Pf), из-за чего
   заголовок отчёта с галочкой/тире/эмодзи проходил гейт; затем маятник качнулся
   в другую сторону — «продолжение словом снимает декларацию» — и «ready to merge
   into main» / «branch main» / «готов к merge после CI» стали пропускаться
   (fail-open, реальные декларации готовности этого PR). Итоговое правило:
   «ready to merge» / «готов к merge» запрещены независимо от того, что идёт после
   «merge» (into main / branch main / после CI / конец / пунктуация). Не
   запрещаются только: отрицание перед фразой («not ready to merge»), markdown-
   цитата и обсуждение МЕХАНИКИ слияния — слово-объект слияния сразу за фразой
   («ready to merge conflicts», «готов к merge конфликтам»), где готовность PR не
   декларируется.
"""

import html
import re
import unicodedata
import time
from typing import Optional


class ReadinessCheckLimitExceeded(Exception):
    """Проверка формулировки не уложилась в отведённый предел.

    Вердикта «запрещённой формулировки нет» в этом случае не существует:
    проверка не закончена, значит доказательства нет. Вызывающий обязан
    трактовать исключение как блокировку, а не как разрешение.
    """


_MERGE_READY_CANDIDATE = re.compile(
    r"(?i)(?:##\s*(?:✅\s*)?)?"
    r"(?:"
    r"готов[оа]?\s*к\s*merge"
    r"|ready\s*(?:to|for)\s*merge"
    r"|merge\s*ready"
    r"|merge\s*is\s*ready"
    r")",
)

_NEGATION_WORDS = re.compile(
    r"(?i)\b("
    r"не(?:\s+ещё|\s+еще)?"
    r"|нет"
    r"|почти"
    r"|not(?:\s+yet)?"
    r"|still\s+not"
    r"|almost"
    r"|будет"
    r"|yet\s+to"
    r")\b"
)

# Маркер markdown-цитаты в начале строки. Якорь ``^`` здесь НЕ ставится: шаблон
# применяется через ``match`` с явной позицией, а ``^`` без флага MULTILINE
# срабатывает только в позиции 0 и молча погасил бы проверку на всех строках,
# кроме первой.
_BLOCKQUOTE_MARKER = re.compile(r"\s*>+\s")

_CLAUSE_CONJUNCTION = re.compile(
    r"(?i)\b(?:"
    r"and|or|but|however|nevertheless|nonetheless"
    r"|и|или|но|а|однако|зато|тем\s+не\s+менее"
    r")\b"
)

# Невидимые управляющие и форматирующие символы. Перечень заменён на КАТЕГОРИЮ:
# точечный список уже отставал от Unicode, а каждая пропущенная позиция — это
# формулировка, которую человек читает, а проверка нет. Значимые разделители
# (перевод строки, возврат каретки, табуляция) сохраняются: на них держатся
# границы строки и клаузы.
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Cc"})
_PRESERVED_CONTROLS = frozenset("\n\r\t")

# Комбинирующие знаки удаляются целиком: после NFKD они отделяются от буквы и
# служат только тому, чтобы развести одинаково выглядящий текст.
_COMBINING_CATEGORIES = frozenset({"Mn", "Mc", "Me"})


def _normalize(text: str) -> str:
    """Свести текст к виду, в котором сравнение отражает то, что видит человек."""

    normalized = html.unescape(text)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        char
        for char in normalized
        if not (
            unicodedata.category(char) in _COMBINING_CATEGORIES
            or (
                unicodedata.category(char) in _INVISIBLE_CATEGORIES
                and char not in _PRESERVED_CONTROLS
            )
        )
    )
    return re.sub(r"[_\-]+", " ", normalized)


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ReadinessCheckLimitExceeded(
            "проверка формулировки не уложилась в предел времени"
        )


# Слова-объекты слияния, после которых «ready to merge …» обсуждает МЕХАНИКУ
# слияния (что-то сливают), а не декларирует готовность ЭТОГО PR. Список узкий
# намеренно: каждое лишнее слово превращает реальную декларацию в пропуск
# (fail-open). Сравнение по префиксу покрывает падежи («конфликтам», «conflicts»).
_MERGE_OBJECT_PREFIXES = ("conflict", "конфликт")


def _following_word(text: str, position: int) -> str:
    """Слово (буквенный ран) сразу за позицией, в нижнем регистре; иначе пусто."""

    end = position
    length = len(text)
    while end < length and text[end].isalpha():
        end += 1
    return text[position:end].lower()


def _is_merge_mechanics(word: str) -> bool:
    """Обсуждает ли слово-продолжение механику слияния, а не готовность PR."""

    return any(word.startswith(prefix) for prefix in _MERGE_OBJECT_PREFIXES)


def is_forbidden(text: str, *, deadline: Optional[float] = None) -> bool:
    """True, если текст содержит финальную декларацию готовности к merge.

    ``deadline`` — абсолютный момент ``time.monotonic``, после которого проверка
    прекращается исключением ``ReadinessCheckLimitExceeded``. Без него предела
    нет и поведение прежнее (так информер петли ревью, fail-open по своему классу
    риска, не меняет поведения); блокирующий гейт предел задаёт сам.

    Декларацией считается фраза, за которой не продолжается слово; отрицание в
    той же клаузе и markdown-цитата срабатывание снимают.
    """

    _check_deadline(deadline)
    normalized = _normalize(text)
    _check_deadline(deadline)

    previous_candidate_end: Optional[int] = None
    line_start = 0
    scanned_to = 0
    marker = _BLOCKQUOTE_MARKER.match(normalized, 0)
    marker_end = marker.end() if marker else None

    for match in _MERGE_READY_CANDIDATE.finditer(normalized):
        _check_deadline(deadline)
        phrase_start = match.start()

        # Начало строки ищется только в ещё не просмотренном куске: окна
        # соседних кандидатов не пересекаются, и весь проход остаётся линейным.
        boundary = max(
            normalized.rfind("\n", scanned_to, phrase_start),
            normalized.rfind("\r", scanned_to, phrase_start),
        )
        scanned_to = phrase_start
        if boundary >= 0:
            line_start = boundary + 1
            marker = _BLOCKQUOTE_MARKER.match(normalized, line_start)
            marker_end = marker.end() if marker else None

        # Окно клаузы начинается либо со строки, либо с конца предыдущей
        # декларации: отрицание первой декларации не тянется через вторую.
        window_start = line_start
        if previous_candidate_end is not None and previous_candidate_end > window_start:
            window_start = previous_candidate_end
        previous_candidate_end = match.end()

        if marker_end is not None and marker_end <= phrase_start:
            continue

        clause_start = window_start
        for index in range(window_start, phrase_start):
            if unicodedata.category(normalized[index]).startswith("P"):
                clause_start = index + 1
        # Союз ищется в том же окне. Совпадение, начавшееся ДО окна и
        # закончившееся после него, невозможно: между словами союза стоят только
        # пробельные символы, а граница окна — конец предыдущей декларации,
        # то есть непробельный текст.
        for conjunction in _CLAUSE_CONJUNCTION.finditer(
            normalized, window_start, phrase_start
        ):
            if conjunction.end() > clause_start:
                clause_start = conjunction.end()

        # Отрицание ищется по границам окна, без копирования среза: срез на
        # каждом кандидате давал бы лишнюю линейную работу на длинном входе.
        if _NEGATION_WORDS.search(normalized, clause_start, phrase_start):
            continue

        # Хвост после фразы просматривается ПО ИНДЕКСУ, без копирования суффикса
        # (копия на каждом кандидате давала квадратичную стоимость). Пропускаются
        # только пробельные символы той же строки; перевод строки НЕ пропускается.
        length = len(normalized)
        position = match.end()
        while position < length:
            char = normalized[position]
            if char in "\n\r":
                break
            if char.isspace():
                position += 1
                continue
            break

        # «ready to merge» / «готов к merge» — декларация готовности ЭТОГО PR
        # НЕЗАВИСИМО от того, что идёт после «merge» (into main / branch main /
        # после CI / в main / конец строки / пунктуация). Единственное
        # исключение — обсуждение МЕХАНИКИ слияния: слово-объект слияния сразу за
        # фразой («ready to merge conflicts», «готов к merge конфликтам») готовность
        # PR не декларирует. Отрицание и цитата сняты выше.
        #
        # Знак вопроса терминатором-исключением НАМЕРЕННО не сделан: пунктуация
        # `.!?` осознанно завершает декларацию и блокирует (защита от обхода через
        # «ready to merge?», Copilot round 22). Отделить легитимный вопрос («Is
        # this ready to merge?») от мягкой декларации-вопроса («PR is ready to
        # merge?») по одному знаку нельзя, поэтому вопрос остаётся консервативно
        # заблокированным — снятие требует отдельного решения (U2, F4-вопрос).
        if position < length and normalized[position].isalpha():
            if _is_merge_mechanics(_following_word(normalized, position)):
                continue
        return True
    return False
