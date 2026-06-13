#!/usr/bin/env python3
"""
Hook: блокировка фраз merge-readiness в `gh pr comment` вне /finalize-pr.

Принимает на stdin JSON с payload tool_input от Claude Code, извлекает команду
и проверяет, содержит ли она запрещённую формулировку («готов к merge» /
«ready to merge» / «merge-ready» и вариации) при отсутствии переменной
окружения FINALIZE_PR_TOKEN.

Защита от обхода:
- Case-insensitive по кириллице и латинице (re.IGNORECASE корректно работает
  с Unicode, в отличие от grep -i в локали C).
- Нормализация `_` и `-` в пробел, чтобы ловить `ready_to_merge`,
  `ready-to-merge`, `MERGE_READY`.
- Переносы строк отдельно не нормализуются: жадный `\\s*` между словами
  паттерна сам матчит пробелы, табы и переносы строк как whitespace.

Возвращает:
- exit 0  — команда разрешена (нет совпадения ИЛИ установлен FINALIZE_PR_TOKEN)
- exit 1  — блокировка (найдена запрещённая фраза)
"""
import json
import html
import os
import re
import sys
import unicodedata


# Паттерны маркера финального комментария readiness.
#
# GPT-5.4 external review (round 12) показал CRITICAL bypass прежнего
# H2-only варианта: `gh pr comment 1 --body 'ready to merge'` проходил.
# Теперь две стадии:
#
#   1) _MERGE_READY_CANDIDATE — ловит фразу на своей строке (с опциональным
#      ## и ✅). Разрешает префикс перед фразой на той же строке, чтобы не
#      расщеплять «The PR is ready to merge».
#   2) _NEGATION_WORDS — постфильтр: если префикс содержит отрицание / «почти»,
#      это обсуждение, не декларация готовности. Пропускаем.
#
# Терминатор фразы проверяется в is_forbidden через unicodedata.category
# (systemic Unicode approach, dolt-0di, Pass 2 G1+G2). Regex ловит только
# саму phrase + prefix; символ сразу после phrase (с пропуском horizontal
# whitespace + combining marks) проверяется на принадлежность категориям
# Po (Other punctuation) и Pf (Final quote) — минимальное семантически-
# корректное множество terminator punctuation. Pass 4 E-1 сузил класс с
# прежнего `startswith('P')`, потому что Ps (Open), Pi (Initial quote),
# Pe (Close), Pc (Connector), Pd (Dash) — не sentence terminators:
# `ready to merge (if CI passes)` / «после review» — narrative continuation,
# не declaration. Любая буква/цифра → narrative continuation (discussion,
# not declaration).
#
# Историю enumeration-подхода см. в `Addresses: dolt-ihl` / Copilot round 22
# (ASCII `.!?`) / big-heroes-ase (`,`) / big-heroes-nw5 (`;` + `…`). Все эти
# кейсы закрываются systemic-проверкой без конкретизации classа, вместе с
# 12+ symmetric Unicode terminators из Pass 2 Tester gate (ideographic comma,
# full-width colon/semicolon, Arabic comma/question/semicolon, Hebrew sof
# pasuq, Mongolian comma, Armenian full stop, Japanese middle dot,
# full-width period) и G2 combining diacritic bypass (нормализацией NFKD
# с последующим strip Mn/Mc/Me — см. is_forbidden для подробностей).
_MERGE_READY_CANDIDATE = re.compile(
    r"(?im)^(?P<prefix>[^\n]*?)"
    r"(?:##\s*(?:✅\s*)?)?"
    r"(?P<phrase>"
    r"готов[оа]?\s*к\s*merge"
    r"|ready\s*(?:to|for)\s*merge"
    r"|merge\s*ready"
    r"|merge\s*is\s*ready"
    r")",
)

# Слова-отрицания перед фразой — снимают блокировку. Покрывают частые паттерны
# обсуждений: «не готов», «not ready», «почти готов», «almost ready»,
# «still not», «PR будет готов», «not yet ready».
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


# Markdown blockquote — цитата из обсуждения/ревью, не декларация готовности.
# GPT-5.4 external review round 15: prefix `> ` перед фразой readiness выдавал
# false positive и блокировал легитимные review-комментарии, которые цитировали
# предыдущие вердикты или обсуждения («> Reviewer cited: ready to merge»).
#
# Два варианта blockquote:
#   1) Строка многострочного body начинается с `>` (опциональные пробелы, один
#      или несколько `>` для nested quotes, затем пробел).
#   2) Однострочный body, открывающийся сразу с blockquote: `--body '> ...`.
# Важно: is_forbidden работает на normalized строке, где `-_` уже заменены
# на пробелы. `--body` → `  body`, `--body=` → `  body=`. Поэтому в regex
# ищем литерал `body` без `--`, с разделителем `=`/пробел и кавычкой.
_BLOCKQUOTE_MARKER = re.compile(
    r"""
    ^\s*>+\s                          # строка-цитата в multi-line body
    |
    body(?:=|\s+)['"]\s*>+\s           # single-line body: кавычка + `>` + пробел
    """,
    re.VERBOSE,
)


class HookError(Exception):
    """Сигнал безопасной остановки hook'а с блокировкой команды."""


def extract_command(raw_stdin: str) -> str:
    """Получить текст команды из payload hook'а Claude Code.

    Fail-secure: если JSON невалиден, бросаем исключение → hook блокирует
    команду (exit 1). Отсутствие `tool_input.command` — тоже HookError:
    hook привязан matcher'ом `Bash(gh pr comment*)`, поэтому `command`
    обязан присутствовать. Пустая строка была бы fail-open при изменении
    формата payload.
    """
    try:
        payload = json.loads(raw_stdin)
    except json.JSONDecodeError as exc:
        raise HookError(
            f"check-merge-ready: невалидный JSON на stdin ({exc}). "
            "Hook блокирует команду fail-secure."
        ) from exc
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not command:
        raise HookError(
            "check-merge-ready: в payload отсутствует tool_input.command. "
            "Hook блокирует команду fail-secure."
        )
    return command


# Детект `gh pr comment` через regex по токенам с любыми whitespace
# между ними (пробелы, табы, переносы строк). Подстрочный поиск
# `"gh pr comment" in command` обходился через `gh\tpr\tcomment ...`,
# и hook пропускал команду без проверки --body-file / dangerous subst.
_GH_PR_COMMENT = re.compile(r"\bgh\s+pr\s+comment\b")


# Флаги gh pr comment, передающие body через файл или stdin — hook не может
# надёжно провалидировать содержимое файла. Блокируем их полностью вне
# /finalize-pr (защита инварианта hard gate от bypass'а).
_BODY_FILE_FLAGS = re.compile(
    r"(^|\s)(--body-file|-F)(\s|=|$)",
)

# Флаг --edit-last открывает редактор для последнего комментария —
# содержимое вводится вне строки команды и скрыто от hook'а.
# Copilot round 31: fail-secure блокировка.
_EDIT_LAST_FLAG = re.compile(
    r"(^|\s)--edit-last(\s|$)",
)

# Флаги, явно передающие body в командной строке: --body / -b.
# Используется для детекта «gh pr comment <N>» без body (editor mode).
_EXPLICIT_BODY_FLAGS = re.compile(
    r"(^|\s)(--body|-b)(\s|=|$)",
)


# Паттерны bash-subst, скрывающие реальное содержимое --body от hook'а.
# Legitimate heredoc `$(cat <<'EOF' ... EOF)` НЕ блокируется: содержимое
# инлайн в команде, hook его видит. А `$(cat /tmp/x)` и ``cat /tmp/x`` —
# block, потому что читают внешний файл, который hook не видит.
# Обычные markdown-backticks не блокируем: они легитимны в отчётах
# (inline-код в PR-комментариях встречается повсеместно).
#
# Why не блокируем `<<<` (here-string): `gh pr comment` не читает stdin без
# `--body-file -` (который уже блокируется выше _BODY_FILE_FLAGS). Значит
# `<<<` не создаёт реального bypass, а любая подстрока `<<<` в самом body
# (например, в обсуждении bash-синтаксиса) давала бы ложные блокировки.
_DANGEROUS_SUBST = re.compile(
    r"""(
        \$\(\s*cat\s+[^<\s]                      # $(cat /path/…) или $(cat  file)
        |
        \$\(\s*<                                 # $(<file) — file redirection
        |
        (?<!\\)`\s*cat\s+[^<\s`][^`]*(?<!\\)`    # `cat /path` — backtick subst с чтением файла
        |
        (?<!\\)`\s*<\s*[^`\s][^`]*(?<!\\)`       # `<file` — backtick subst с редиректом
    )""",
    re.VERBOSE,
)


# Bypass через переменную: `--body "$BODY"` / `--body $BODY` / `--body "${BODY}"`
# и конкатенации вроде `--body "Prefix: $BODY"`, `--body=foo$BODY`.
# Hook видит только литерал `$BODY`, не содержимое переменной, — запрещённая
# фраза «готов к merge» в $BODY останется невидимой, и блокировка не сработает.
# Блокируем любое double-quoted или unquoted значение флага --body, где
# встречается shell-переменная ($var, ${var}, ${var:-default}) В ЛЮБОЙ позиции.
# Command substitution `$(...)` НЕ матчится: после `$` regex ждёт `{` или
# букву/подчёркивание.
# Single-quoted аргументы НЕ матчим: в shell `'$BODY'` — литерал без раскрытия.
# Copilot round 24: расширен с «только начало» до «в любой позиции».
_OPAQUE_VAR_BODY = re.compile(
    r"""
    (?:^|\s)(?:--body|-b)(?:=|\s+)       # флаг --body/-b, затем `=` или пробел
    (?:
        "(?:[^"\\]|\\.)*?               # double-quoted: любой префикс до $
        |
        [^\s'"]*                         # unquoted: любой префикс (без кавычек/пробелов)
    )
    \$                                    # доллар — начало переменной
    (?:
        \{[^}]+\}                         # ${VAR} / ${VAR:-default}
        |
        [A-Za-z_]\w*                      # $VAR
    )
    """,
    re.VERBOSE,
)


# Извлечение имени переменной из --body "...$VAR..." / --body "${VAR}" / --body $VAR.
# Нужно для привязки heredoc-исключения к конкретной переменной (round 21 fix).
# Copilot round 24: расширен для поиска переменной в любой позиции (конкатенации).
_BODY_VAR_NAME = re.compile(
    r"""
    (?:^|\s)(?:--body|-b)(?:=|\s+)       # флаг --body/-b
    (?:
        "(?:[^"\\]|\\.)*?               # double-quoted: любой префикс до $
        |
        [^\s'"]*                         # unquoted: любой префикс
    )
    \$                                    # доллар
    (?:
        \{([A-Za-z_]\w*)                 # ${VAR} → группа 1
        |
        ([A-Za-z_]\w*)                    # $VAR → группа 2
    )
    """,
    re.VERBOSE,
)


def _body_var_has_heredoc(command: str) -> bool:
    """True если переменная из --body "$VAR" присвоена через heredoc $(cat <<TOKEN).

    Copilot round 21 CRITICAL: прежний глобальный _HEREDOC_PRESENT снимал
    opaque-блокировку при наличии ЛЮБОГО $(cat <<TOKEN) в команде. Bypass:
    X=$(cat <<'EOF'\ninnocent\nEOF\n)\ngh pr comment 1 --body "$BODY"
    — heredoc кормит X, а $BODY остаётся непрозрачным.

    Теперь проверяем, что heredoc присваивается ИМЕННО переменной из --body.
    """
    m = _BODY_VAR_NAME.search(command)
    if not m:
        return False
    var_name = m.group(1) or m.group(2)
    if not var_name:
        return False
    # Ищем VAR=$(cat <<TOKEN — heredoc присваивается именно этой переменной
    pattern = re.compile(
        rf"(?:^|\n)\s*{re.escape(var_name)}=\$\(\s*cat\b\s*<<-?\s*[\"']?[A-Za-z_][A-Za-z0-9_]*"
    )
    return bool(pattern.search(command))


# Heredoc-cat непосредственно в позиции --body: --body "$(cat <<'EOF'...)"
# Содержимое heredoc'а инлайн в команде — hook видит его через raw текст,
# is_forbidden проверит на запрещённые фразы.
_BODY_DIRECT_HEREDOC_CAT = re.compile(
    r"""
    (?:^|\s)(?:--body|-b)(?:=|\s+)       # флаг --body/-b
    "?\$\(\s*cat\b\s*                     # $(cat
    <<-?\s*[\"']?[A-Za-z_][A-Za-z0-9_]*  # heredoc-маркер
    """,
    re.VERBOSE,
)


# Bypass через ЛЮБОЙ command substitution `$(...)` в позиции --body:
# `--body "$(echo $BODY)"`, `--body "$(printf %s $BODY)"`, `--body "$(head
# /tmp/x)"`, `--body "$(tail /tmp/x)"`, и т.д. — всё что раскрывает
# содержимое через shell, скрыто от hook'а.
#
# Whitelist-подход: блокируем любой `$(` сразу после --body (с опциональной
# кавычкой). Heredoc-исключение: если --body сам является heredoc-cat
# (`--body "$(cat <<'EOF'...)"`) — содержимое видно hook'у инлайн,
# is_forbidden проверит. Посторонний heredoc для другой переменной
# НЕ снимает блокировку (Copilot round 21 CRITICAL fix).
#
# Это закрывает класс атак целиком (не только head/tail/sed/awk, но и
# echo $VAR, printf, process substitution, любой future command).
# Источник: GPT-5.3-Codex round 14 CRITICAL + D-02 из round 13 deferred.
# Copilot round 27: расширен с «только начало» до «в любой позиции» (аналог
# round 24 fix для _OPAQUE_VAR_BODY). `--body "Prefix $(head /tmp/x)"`
# раньше проходил, теперь блокируется.
_OPAQUE_COMMAND_SUBST_BODY = re.compile(
    r"""
    (?:^|\s)(?:--body|-b)(?:=|\s+)      # флаг --body/-b
    (?:
        "(?:[^"\\]|\\.)*?               # double-quoted: любой префикс до $(
        |
        [^\s'"]*                         # unquoted: любой префикс
    )
    \$\(                                  # $( — начало command substitution
    """,
    re.VERBOSE,
)


def uses_body_file(command: str) -> bool:
    """True — если команда gh pr comment передаёт body через файл/stdin."""
    if not _GH_PR_COMMENT.search(command):
        return False
    return bool(_BODY_FILE_FLAGS.search(command))


def uses_edit_last(command: str) -> bool:
    """True — если gh pr comment использует --edit-last (editor mode).

    Copilot round 31: --edit-last открывает редактор для последнего
    комментария, содержимое скрыто от hook'а — fail-secure блокировка.
    """
    if not _GH_PR_COMMENT.search(command):
        return False
    return bool(_EDIT_LAST_FLAG.search(command))


def uses_no_body(command: str) -> bool:
    """True — если gh pr comment вызван без --body / -b / --body-file / -F.

    Copilot round 31: без явного флага body gh открывает редактор —
    содержимое вводится интерактивно и скрыто от hook'а. Fail-secure
    блокировка.
    """
    if not _GH_PR_COMMENT.search(command):
        return False
    if _BODY_FILE_FLAGS.search(command):
        return False  # --body-file / -F: обрабатывается отдельно
    if _EXPLICIT_BODY_FLAGS.search(command):
        return False  # --body / -b: содержимое видно hook'у
    return True


def uses_dangerous_substitution(command: str) -> bool:
    """True — если команда gh pr comment использует file-read конструкции
    внутри command substitution, скрывающие реальное содержимое body.

    Закрывает bypass: `--body "$(cat /tmp/x)"` — hook видит только литерал
    `$(cat /tmp/x)`, не содержимое файла. Легитимный heredoc
    `$(cat <<'EOF' ... EOF)` остаётся разрешённым: содержимое инлайн в
    команде и попадает в regex `_MERGE_READY_CANDIDATE`.
    """
    if not _GH_PR_COMMENT.search(command):
        return False
    return bool(_DANGEROUS_SUBST.search(command))


def uses_opaque_variable_body(command: str) -> bool:
    """True — если `--body` получает значение из непрозрачной переменной.

    Закрывает bypass: `BODY="## ✅ Готов к merge"; gh pr comment 1 --body "$BODY"`.
    В payload tool_input.command виден только литерал `$BODY` — фраза «готов
    к merge» лежит в переменной и hook её не увидит. Чтобы hard gate
    оставался реальным, для `gh pr comment` без FINALIZE_PR_TOKEN запрещено
    подставлять body из переменной — допустимы только inline string или
    heredoc `$(cat <<'EOF' ... EOF)`, где содержимое физически в команде.

    Exception: heredoc в той же команде делает содержимое видимым hook'у
    (even через переменную — BODY=$(cat <<'EOF' ... EOF); --body "$BODY").
    Именно эту форму используют шаблоны review-pass в sprint-pr-cycle
    и external-review — без исключения hook ломает pipeline целиком.
    Фраза merge-ready в heredoc поймается is_forbidden по raw команде.
    """
    if not _GH_PR_COMMENT.search(command):
        return False
    if _body_var_has_heredoc(command):
        # Heredoc кормит ИМЕННО переменную из --body — содержимое видно hook'у.
        # Copilot round 21: привязка к имени переменной закрывает alien-heredoc bypass.
        return False
    return bool(_OPAQUE_VAR_BODY.search(command))


def uses_opaque_command_substitution_body(command: str) -> bool:
    """True — если `--body` получает значение из command substitution `$(...)`.

    Закрывает bypass через любую shell-команду, скрывающую содержимое:
    `$(echo $BODY)`, `$(printf %s $BODY)`, `$(head /tmp/x)`, `$(tail ...)`,
    `$(sed ...)`, `$(awk ...)`, `$(xxd ...)`, `$(perl ...)`, `$(python ...)`
    и любой будущий инструмент. Whitelist-подход: блокируем любой `$(`
    сразу после `--body`.

    Exception: --body "$(cat <<'EOF' ... EOF)" — heredoc-cat непосредственно
    в позиции --body, содержимое инлайн в команде, is_forbidden проверит.
    Посторонний heredoc для другой переменной НЕ снимает блокировку
    (Copilot round 21 CRITICAL fix).

    Источник: GPT-5.3-Codex round 14 CRITICAL + D-02 deferred.
    """
    if not _GH_PR_COMMENT.search(command):
        return False
    if _BODY_DIRECT_HEREDOC_CAT.search(command):
        # --body "$(cat <<TOKEN...)" — heredoc-cat IS the body, content visible.
        # Copilot round 21: посторонний heredoc для другой переменной НЕ снимает block.
        return False
    return bool(_OPAQUE_COMMAND_SUBST_BODY.search(command))


def is_forbidden(command: str) -> bool:
    """True — если команда содержит запрещённый заголовок readiness.

    Нормализуем только `_` и `-` в пробелы — это закрывает обход через
    `ready_to_merge`, `ready-to-merge`. Переносы строк НЕ нормализуем:
    паттерн использует multiline-якоря `^`/`$`, которые должны видеть
    реальные `\\n` в команде (shell-heredoc, multiline body).

    Copilot round 28: дополнительно удаляем zero-width символы и
    декодируем HTML entities, чтобы `ready&#x200b;to merge` и подобные
    обходы не проходили.

    dolt-0di (v3.5, Pass 2 G1+G2): NFKD normalization + strip Mn/Mc/Me +
    systemic terminator check через `unicodedata.category`. NFKD (в
    отличие от NFKC) декомпозирует compatibility forms и precomposed
    символы на base + combining marks (например `mergé` → `merge` +
    U+0301); последующий фильтр `category not in ("Mn","Mc","Me")`
    удаляет combining marks, возвращая чистую base-form phrase для
    regex. Post-match проверка: первый non-whitespace символ после
    phrase → если категория `Po` (Other punctuation) или `Pf` (Final
    quote) → terminator, declaration блокируется. Pass 4 E-1 сузил
    класс: Ps/Pi/Pe/Pc/Pd НЕ включаются как terminator (`(`, `[`, `{`,
    «, ', ), ], }, ‒, —, ‿ — narrative continuation, не sentence
    terminators). Letter/digit → narrative continuation, skip.
    Rationale NFKC → NFKD: NFKC *composes* base+mark обратно в
    precomposed codepoint (для `é` regex всё равно рассыпется, если в
    phrase есть combining), NFKD *decomposes* до атомов, что даёт
    возможность strip'нуть marks и привести phrase к каноничной
    base-форме. Это закрывает whole class Unicode-punctuation bypass'ов
    (12+ векторов) без enumeration terminator-символов, плюс G2
    orthographic bypass (combining accent на последней букве phrase).

    Двухстадийный matcher (см. комментарий к _MERGE_READY_CANDIDATE):
    candidate → проверка префикса на отрицание → True только если
    префикс чист И за phrase идёт terminator (punctuation/EOL/shell-quote).
    """
    # Декодируем HTML entities: &#x200b; → символ, &nbsp; → пробел и т.д.
    normalized = html.unescape(command)
    # Удаляем zero-width и невидимые Unicode символы, которые GitHub рендерит
    # как пустое место, но regex не видит.
    normalized = re.sub(r"[\u200b-\u200f\u2028-\u202f\ufeff\u00ad\u2060]", "", normalized)
    # NFKD + удаление combining marks: combining diacritics разносятся на
    # base + mark, затем Mn/Mc/Me вычищаются. `ready to merge\u0301:landing`
    # после NFKD = `ready to merge\u0301:landing`, после strip marks =
    # `ready to merge:landing` → regex матчит phrase, `:` триггерит
    # terminator. Без этого combining acute на последней `e` в `merge` (или
    # precomposed `mergé` после NFC) рассыпал regex — bypass (Pass 2 G2).
    # NFKD также нормализует compatibility forms: `\uFE55` (small colon) →
    # `:` (Po, уже terminator по unicodedata.category). Effect: G2 закрыт
    # whole class — любая комбинация base+mark в phrase сводится к base.
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        ch for ch in normalized if unicodedata.category(ch) not in ("Mn", "Mc", "Me")
    )
    normalized = re.sub(r"[_\-]+", " ", normalized)
    for match in _MERGE_READY_CANDIDATE.finditer(normalized):
        prefix = match.group("prefix") or ""
        if _NEGATION_WORDS.search(prefix):
            # «не готов к merge», «почти ready to merge», «PR будет готов…»
            # — это обсуждение, не декларация. Продолжаем искать другие
            # кандидаты в той же команде.
            continue
        if _BLOCKQUOTE_MARKER.search(prefix):
            # markdown blockquote (`> ...`) — цитата из ревью/обсуждения, не
            # объявление. Финальный комментарий /finalize-pr публикуется как
            # `## ✅ Готов к merge`, без blockquote — реального bypass не создаёт.
            continue
        # Systemic terminator check: что идёт сразу после phrase?
        tail = normalized[match.end():]
        # Пропускаем horizontal whitespace + combining/modifier codepoints.
        # Вертикальный whitespace (\n, \r) — terminator (EOL → declaration),
        # его пропускать нельзя. Всё остальное horizontal whitespace
        # (SPACE, TAB, NBSP U+00A0, em-space U+2003, и любая Zs-категория,
        # уцелевшая после NFKD) — безопасно пропустить.
        #
        # Pass 3 CP-1 (Copilot MEDIUM): прежний класс `c in " \t"` пропускал
        # только ASCII SPACE/TAB. После html.unescape `&nbsp;` → U+00A0;
        # NFKD обычно декомпозирует его в ` `, но defense-in-depth требует
        # explicit handling — любой Unicode horizontal whitespace должен
        # быть прозрачен для terminator-check'а, независимо от нормализации.
        # `c.isspace() and c not in "\n\r"` покрывает whole class Zs/Zl/Zp
        # плюс ASCII \t/\v/\f, исключая вертикальные separator'ы.
        #
        # Combining marks (Mn/Mc/Me) — «невидимые» диакритики, которые
        # visually сливаются с phrase и не являются sentence terminators.
        #
        # Pass 5 E-5 (WARNING): прежняя версия включала Sk (Symbol modifier)
        # и Lm (Letter modifier) в skip-set для покрытия G2 bypass через
        # U+00B4 (ACUTE ACCENT, Sk). Но backtick U+0060 — тоже Sk, и skip-
        # loop проглатывал closing backtick после phrase в легитимных
        # командах вроде `gh pr comment 1 --body 'Use \`ready to merge\`'`
        # (inline code span в обсуждении). После Sk-backtick скипался и
        # shell-quote `'` триггерил terminator-check → false block
        # легитимного comment.
        #
        # Теперь Sk/Lm НЕ включаются. G2 combining diacritic bypass всё
        # ещё закрыт через NFKD normalization выше: precomposed `mergé`
        # → `merge` + U+0301 (Mn) → strip marks → clean phrase, regex
        # match → terminator check видит чистое `:`/`.` после NFKD-
        # декомпозированного текста. U+00B4 acute accent под NFKD
        # декомпозируется в U+0020 + U+0301 → space+mark → после strip
        # marks остаётся space, который isspace() пропускает. Pathway
        # через нормализацию работает для всего класса G2 без включения
        # Sk в skip-set.
        i = 0
        n = len(tail)
        while i < n:
            c = tail[i]
            if c in "\n\r":
                # Вертикальный whitespace — terminator, выход из skip-loop.
                break
            if c.isspace():
                # Горизонтальный whitespace (ASCII + NBSP/em-space/прочее Zs).
                i += 1
                continue
            cat = unicodedata.category(c)
            # Только combining marks — семантически «невидимые» диакритики.
            # Spacing modifier symbols (Sk, включая backtick) и modifier
            # letters (Lm) НЕ skip — они могут быть legitimate delimiters
            # или закрывающими quotes в shell-команде.
            if cat in ("Mn", "Mc", "Me"):
                i += 1
                continue
            break
        if i >= n:
            # EOF сразу после phrase — declaration (no continuation possible).
            return True
        ch = tail[i]
        if ch in "\n\r":
            # Newline — declaration (phrase в конце строки).
            return True
        if ch in "\"'":
            # Закрывающая shell-quote — declaration (`--body 'ready to merge'`).
            return True
        # Unicode punctuation category — только closing/other punctuation
        # семантически отделяет declaration от продолжения. Opening punctuation
        # (Ps, Pi) начинает subordinate clause / цитату — narrative continuation.
        #
        # Pass 4 E-1 (WARNING): прежний `cat.startswith('P')` блокировал
        # легитимные `(`, `[`, `{`, `'`, `"`, `«` — фразы типа «ready to merge
        # (if CI passes)» ложно считались декларацией. Opening-bracket/quote
        # подкатегории Ps (Open punctuation) и Pi (Initial quote) —
        # openers clause, НЕ sentence terminators.
        #
        # v3.5 Option B revert (10cdf47 E-7 reverted): класс ограничен Po+Pf.
        # Pass 6 E-7 расширение до Po+Pf+Pe+Pd создало overmatch surface:
        #   - Pe overmatch: `(ready to merge)` closing `)` — legitimate, но
        #     в связке с Po (`:` в inline backtick quote) открыл bypass surface
        #     `big-heroes-16e` (E-14);
        #   - Pd overmatch: `/` и `.` внутри paths/branches — ASCII hyphen уже
        #     normalized pre-strip, Unicode en/em-dash `—` `–` в narrative
        #     «ready to merge — landing follows» остаётся ambiguous между
        #     declaration и narrative. Породил `big-heroes-3ed` (E-15).
        # Option B: вернули Po+Pf как минимальный proven-safe класс (Pass 4 E-1
        # baseline). Pe/Pd overmatch (E-7) и сопутствующие E-14/E-15 defer'ятся
        # до Python rewrite в v3.6 (`big-heroes-55m`, `big-heroes-ytx`).
        #
        # Включаем:
        #   Po — Other punctuation (`.`, `!`, `?`, `:`, `;`, CJK `。`, `、`,
        #        full-width `．`, `！`, `？`, `，`, Arabic `،`, `؛`, `؟`,
        #        Hebrew `׃`, Mongolian `᠂`, Armenian `։`, Japanese `・`);
        #   Pf — Final quote (`”`, `»`, `’`) — closing quote может быть
        #        terminator для narrative «цитата закончилась, continuation».
        #
        # НЕ включаем:
        #   Ps — Open punctuation (`(`, `[`, `{`) — начинает clause, narrative;
        #   Pi — Initial quote (`“`, `«`, `‘`) — открывающая цитата, narrative;
        #   Pe — Close punctuation (`)`, `]`, `}`) — reverted v3.5 Option B
        #        (E-7 tactical overfit → E-14 surface, deferred v3.6);
        #   Pd — Dash (`-`, `—`, `–`) — reverted v3.5 Option B (E-7 →
        #        E-15 surface, deferred v3.6);
        #   Pc — Connector (`_`, `‿`) — не sentence separator.
        #
        # Минимальный proven-safe terminator класс: Po + Pf (Pass 4 E-1 baseline).
        cat = unicodedata.category(ch)
        if cat in ("Po", "Pf"):
            return True
        # Letter, digit, space-like separator (Z*, но только Zs после strip
        # whitespace выше не должен появиться), symbol — narrative continuation.
        # `готов к merge after X` / `ready to merge in the future` — пропускаем.
        continue
    return False


def main() -> int:
    # Легитимный вызов из /finalize-pr — пропускаем
    if os.environ.get("FINALIZE_PR_TOKEN"):
        return 0

    raw = sys.stdin.read()

    try:
        command = extract_command(raw)
    except HookError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1

    # Блокируем --body-file / -F для gh pr comment вне /finalize-pr: body
    # передаётся файлом/stdin и hook не может надёжно проверить содержимое.
    # Это bypass hard gate (нашёл Copilot auto-reviewer). Для легитимных
    # длинных отчётов используется /finalize-pr с FINALIZE_PR_TOKEN.
    if uses_body_file(command):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` флаги --body-file / -F "
            "запрещены без FINALIZE_PR_TOKEN, потому что hook не может "
            "провалидировать содержимое файла.\n"
            "Используй inline --body '...' ИЛИ /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    # Блокируем --edit-last: редактирует последний комментарий через
    # интерактивный редактор, содержимое скрыто от hook'а.
    # Copilot round 31: fail-secure блокировка.
    if uses_edit_last(command):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` флаг --edit-last запрещён "
            "без FINALIZE_PR_TOKEN — содержимое редактируется вне "
            "командной строки и hook не может его проверить.\n"
            "Используй inline --body '...' ИЛИ /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    # Блокируем вызов без явного --body / -b / --body-file / -F:
    # gh открывает интерактивный редактор, содержимое скрыто от hook'а.
    # Copilot round 31: fail-secure блокировка editor mode.
    if uses_no_body(command):
        sys.stderr.write(
            "БЛОКИРОВКА: `gh pr comment` без флага --body / -b / "
            "--body-file / -F запрещён без FINALIZE_PR_TOKEN — "
            "gh откроет редактор и hook не сможет проверить содержимое.\n"
            "Используй inline --body '...' ИЛИ /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    # Блокируем command substitution, скрывающие реальное содержимое body
    # от hook'а: `$(cat /file)`, `$(<file)`, backticks с чтением файла.
    # Legitimate heredoc `$(cat <<'EOF' ... EOF)` остаётся разрешённым
    # (содержимое инлайн, regex его видит). Here-string `<<<` НЕ блокируется
    # отдельно: `gh pr comment` не читает stdin без `--body-file -`,
    # который уже блокируется выше.
    if uses_dangerous_substitution(command):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` запрещены конструкции, "
            "скрывающие содержимое body от hook'а: "
            "`$(cat file)`, `$(<file)`, backticks `cat file`.\n"
            "Используй inline --body '...', heredoc `$(cat <<'EOF' ... EOF)` "
            "или /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    # Блокируем `--body "$VAR"` / `--body $VAR` / `--body "${VAR}"` —
    # body берётся из переменной, hook видит только литерал имени переменной,
    # а реальный текст ему недоступен. Это bypass: запрещённая фраза легко
    # прячется в переменную (`BODY="## ✅ Готов к merge"; gh pr comment 1 --body "$BODY"`).
    if uses_opaque_variable_body(command):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` нельзя подставлять body из "
            "переменной (`--body \"$VAR\"`, `--body ${VAR}`): hook видит "
            "только имя переменной, не её содержимое.\n"
            "Используй inline --body '...', heredoc `$(cat <<'EOF' ... EOF)` "
            "или /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    # Блокируем любой command substitution `$(...)` в позиции --body:
    # `$(echo $VAR)`, `$(printf ...)`, `$(head file)`, `$(awk ...)` и т.д.
    # Закрывает класс bypass'ов через shell-инструменты (Codex round 14 CR-1 + D-02).
    # Исключение — heredoc (BODY=$(cat <<'EOF'...EOF)) — обрабатывается внутри функции.
    if uses_opaque_command_substitution_body(command):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` нельзя подставлять body через "
            "command substitution (`--body \"$(...)\"`): hook видит только "
            "литерал подстановки, не её результат.\n"
            "Используй inline --body '...', heredoc `BODY=$(cat <<'EOF' ... EOF)` "
            "+ `--body \"$BODY\"` (heredoc содержимое видно hook'у), "
            "или /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    if is_forbidden(command):
        sys.stderr.write(
            "БЛОКИРОВКА: фразы 'готов к merge' / 'ready to merge' / 'merge-ready' "
            "разрешены только через /finalize-pr "
            "(см. .claude/skills/finalize-pr/SKILL.md).\n"
            "Используй /finalize-pr <PR_NUMBER>.\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
