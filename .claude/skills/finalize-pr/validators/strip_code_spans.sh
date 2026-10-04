#!/usr/bin/env bash
# strip_code_spans.sh — предобработка тела review-pass для validate_review_pass_body.
#
# Зачем: validator Шаг 5 в SKILL.md использует `grep -qE` по `CHANGES_REQUESTED`
# и `APPROVED` с word-boundary regex. Бэктики попадают в non-[A-Z_] boundary,
# и narrative-текст с цитатой `CHANGES_REQUESTED` внутри code span ложно
# блокирует hard gate (infrastructure false positive v3.4 #14).
#
# Что делаем: заменяем содержимое code spans (inline `...` и fenced блоки)
# на пустоту ДО того, как validator grep'ает слова. Реальные вердикты в
# plain text остаются, narrative-цитаты из code spans — нет.
#
# CommonMark coverage (Pass 2 class-coverage fix, big-heroes-nw5):
#   - fenced blocks: opener/closer — тройной бэктик ``` ИЛИ тильда ~~~;
#   - indent tolerance: 0-3 leading spaces перед маркером (CommonMark spec);
#   - fence type matching: ``` закрывается только ```, ~~~ только ~~~;
#   - mismatched marker (``` внутри ~~~ fence или наоборот) — игнорируется,
#     fence остаётся открытым до реального closer того же типа;
#   - backtick-fence info-string НЕ содержит ` (Pass 3 Copilot D-1):
#     CommonMark §4.5 запрещает backtick в info-string после ```-opener'а
#     (для ~~~ разрешено). Нарушение → opener НЕ открывает fence,
#     строка идёт как inline. Без проверки adversarial `` ``` `fake-info` ``
#     открывал ложный fence и проглатывал CHANGES_REQUESTED в хвосте.
#
# CommonMark fence length symmetry (Pass 1 external F-2-fence, big-heroes-2iw):
#   - opener run length N ≥ 3 (3+ последовательных маркеров одного типа);
#   - closer run length M ≥ N (CommonMark: closer может быть длиннее opener);
#   - closer короче opener (M < N) НЕ закрывает fence — остаёмся внутри блока.
#   До fix: opener матчился через `^[ ]{0,3}```` (≥3), closer требовал ровно 3
#   → fence с opener ≥4 никогда не закрывался симметричным маркером, остаток
#   до EOF проглатывался, реальные вердикты после блока пропадали → ложный
#   APPROVED. GPT-5.3-Codex + Copilot independent repro. Fail-secure:
#   «неправильный» closer (M < N) НЕ закрывает fence — безопасный default,
#   хвост не попадает в validator как plain text.
#
# Pass 4 E-3 (escaped backticks): CommonMark §2.4 backslash escape — `\`` это
# literal backtick, НЕ code span delimiter. Прежний inline-scanner матчил
# любой run ` как delimiter, игнорируя backslash перед ним. Bypass:
# `\`CHANGES_REQUESTED\`` полностью стрипался как span (backslash + backtick
# трактовались как opener/closer), реальный вердикт CR в escaped form
# становился невидим. Fix: считаем run backslashes ПЕРЕД backtick-run'ом;
# нечётное число → первый backtick экранирован → не участвует в span.
# Чётное (включая 0) → backticks обычные, span-логика работает.
# Edge: `\\` (двойной backslash) — literal backslash + следующий backtick
# НЕ экранирован (чётное количество).
#
# v3.5 Option B revert (bc6fe35 E-2 reverted): multi-line inline scanner
# удалён. E-2 paragraph-level accumulation через sentinel \x01 joining дал
# CommonMark §6.1 alignment, но paragraph state-machine surface породил
# E-10 (blockquote terminator, big-heroes-36d), E-11 (setext heading,
# big-heroes-42a), E-12 (HTML block, big-heroes-zhe). Каждый tactical fix
# в paragraph-state вскрывал новые CRITICAL findings — overfitting cycle.
# Option B (big-heroes-nw5): возврат к per-line inline scan (proven минимум
# pre-bc6fe35). Trade-off: multi-line inline span внутри одного paragraph
# больше не стрипается — safe default (лучше ложный block, чем hidden CR).
# Systemic Python rewrite — big-heroes-55m (P1 v3.6 sprint-opener).
#
# НЕ покрыто (v3.5 known limitations, см. SKILL.md Шаг 5 Known Limitations):
#   - multiline inline spans через newline — big-heroes-55m (v3.6 rewrite);
#   - blockquote-prefixed fences / blockquote paragraph terminator —
#     big-heroes-wz6 / big-heroes-36d;
#   - setext heading / HTML block terminators — big-heroes-42a / big-heroes-zhe;
#   - structural-line inline strip (ATX/list с backticks) — big-heroes-6bp;
#   - indented code blocks (4+ spaces без маркера) — редкий случай в
#     review-pass, safe default: остаётся plain text, validator блокирует.
#
# Поток: читаем stdin, пишем stdout.
# Зависимости: bash, awk (POSIX). Без внешних тулов.
#
# Edge cases (покрыты тестами в test_validate_review_pass.sh):
#   - fenced с language hint (```bash, ```diff, ```ts и т.п.);
#   - CRLF — нормализуем через tr перед awk;
#   - inline backticks внутри fenced блока — fenced strip работает первым
#     и удаляет весь блок целиком, внутренние ` не ломают логику;
#   - непарный run backticks — best-effort: весь run + хвост строки идут в out
#     как plain text (safe default: не прячем потенциальный CHANGES_REQUESTED);
#   - множественные inline spans на одной строке — run-length matcher;
#   - N-backtick inline spans (``content``, ```content``` и т.п., CommonMark
#     F-2-inline, Pass 1 external dolt-cet): opener/closer одинаковой
#     run-length N, содержимое между ними стрипается целиком;
#   - escaped backticks `\`` — literal, не span delimiter (opener only, Pass 4 E-3);
#   - per-line inline scanning (v3.5 Option B revert: multi-line E-2 отключён).

set -u

# Двухстадийный pipeline:
#
# Стадия 1 (awk fence-stripper): читает stdin, удаляет fenced blocks,
# на stdout пишет «не-fence» строки (как есть, inline ещё не обработан).
# Fail-safe для lone opener (Pass 2 G3) — буферизация с восстановлением
# pending в output при EOF без closer.
#
# Стадия 2 (awk inline-stripper): per-line run-length matcher (v3.5 Option B).
# Для каждой не-fence строки проходим слева направо, ищем парный run
# одинаковой длины N в пределах той же строки. Escape handling (E-3):
# backslash-prefix перед opener-run — нечётное количество → первый backtick
# литерал, span не открывается. В scan-loop (closer) escape НЕ применяется
# (CommonMark §6.1, E-8 semantics сохранена и в per-line модели).
# Structural lines (ATX heading / list item / thematic break, E-9) — emit
# raw без inline scan: они представляют block-level элементы, в которых
# code spans по семантике review-pass не появляются (known limitation,
# big-heroes-6bp).
tr -d '\r' | awk '
  # Подсчёт длины run-а маркера (marker = "`" или "~") на opener-строке.
  # Возвращает длину run-а (≥3), если строка — валидный opener
  # (0-3 leading spaces + run маркеров длиной ≥3), иначе 0.
  # Вся не-whitespace часть до маркера запрещена (CommonMark).
  #
  # D-1 (Pass 3 Copilot): для BACKTICK-маркера info-string (хвост строки
  # после run-а) НЕ должен содержать backtick. CommonMark §4.5: «A fenced code
  # block begins with a code fence, followed by an optional info string …
  # If the info string comes after a backtick fence, it cannot contain
  # any backtick characters». Нарушение этого правила — opener НЕ
  # открывает fence (строка трактуется как inline-текст). Для TILDE-
  # маркера такого ограничения нет. Без валидации adversarial opener
  # `` ``` `not-a-lang` `` открывает «fence», проглатывая хвост с
  # CHANGES_REQUESTED, и validator ложно видит APPROVED.
  function fence_open_run(line, marker,   i, n, indent, run, c, info) {
    n = length(line)
    # Пропустить 0-3 ведущих пробела; tab запрещён как indent CommonMark.
    indent = 0
    for (i = 1; i <= n && indent < 4; i++) {
      c = substr(line, i, 1)
      if (c == " ") { indent++; continue }
      break
    }
    if (indent > 3) return 0
    # Теперь i указывает на первый не-пробельный символ.
    # Считаем run-length маркера.
    run = 0
    while (i <= n && substr(line, i, 1) == marker) { run++; i++ }
    if (run < 3) return 0
    # После run-а допускается info-string (language hint) для backtick; для
    # tilde тоже. CommonMark §4.5: backtick-fence info-string НЕ может
    # содержать `. D-1 fix: если marker="`" и в info-string есть backtick —
    # fence НЕ открывается (adversarial `` ``` `fake-info` `` bypass).
    # Для tilde-fence backticks в info допустимы — валидация не нужна.
    if (marker == "`") {
      info = substr(line, i, n - i + 1)
      if (index(info, "`") > 0) return 0
    }
    return run
  }

  # Проверка, является ли строка валидным closer того же типа для fence с
  # open_len маркеров. Closer: 0-3 leading spaces + marker-run длиной >= open_len +
  # только trailing whitespace (info string у closer запрещена CommonMark).
  function fence_close_matches(line, marker, open_len,   i, n, indent, run, c, j) {
    n = length(line)
    indent = 0
    for (i = 1; i <= n && indent < 4; i++) {
      c = substr(line, i, 1)
      if (c == " ") { indent++; continue }
      break
    }
    if (indent > 3) return 0
    run = 0
    while (i <= n && substr(line, i, 1) == marker) { run++; i++ }
    if (run < open_len) return 0
    # После closer-run допускается только whitespace до конца строки.
    for (j = i; j <= n; j++) {
      c = substr(line, j, 1)
      if (c != " " && c != "\t") return 0
    }
    return 1
  }

  BEGIN { in_fence = ""; fence_len = 0; pending_count = 0 }
  {
    line = $0

    if (in_fence == "") {
      # Не внутри fence — проверить, это ли opener.
      # CommonMark: 0-3 leading spaces, затем ``` / ~~~ (run length ≥3).
      open_run = fence_open_run(line, "`")
      if (open_run >= 3) {
        in_fence = "BACKTICK"
        fence_len = open_run
        # Fail-safe для lone opener (Pass 2 G3, dolt-xn3):
        # буферизуем opener + все последующие строки до closer. Если closer
        # не найден до EOF (lone opener / fence-injection), END-блок сбросит
        # буфер обратно в output как plain text — validator увидит реальный
        # CHANGES_REQUESTED в хвосте, и hard gate не пропустит ложный APPROVED.
        # Прежний код делал `next` без буферизации, что стирало всё после
        # opener молча.
        pending_count = 1
        pending_lines[pending_count] = line
        next
      }
      open_run = fence_open_run(line, "~")
      if (open_run >= 3) {
        in_fence = "TILDE"
        fence_len = open_run
        pending_count = 1
        pending_lines[pending_count] = line
        next
      }
      # Не-fence строка — печатаем как есть, inline обрабатывается в Стадии 2.
      print line
    } else {
      # Внутри fence — ищем close ТОГО ЖЕ типа и длиной >= opener.
      # Mismatched marker (~~~ внутри BACKTICK или vice versa) игнорируется,
      # closer короче opener (M < fence_len) тоже игнорируется (CommonMark F-2-fence).
      #
      # Pass 5 E-4 (fence strip paragraph boundary leak): при закрытии fence
      # эмитируем blank line, чтобы Stage 2 (inline scanner) трактовал
      # pre-fence и post-fence контент как разные параграфы. Без blank line
      # Stage 2 видел непрерывный поток non-fence строк и inline opener-
      # backtick ДО fence мог сматчиться с closer-backtick ПОСЛЕ fence,
      # стрипая реальный CHANGES_REQUESTED между ними. CommonMark §4.5:
      # fenced code block — это block element, он всегда отделён от
      # окружающего текста paragraph boundary. Blank line — канонический
      # способ передать это Stage 2 через stream-based interface.
      if (in_fence == "BACKTICK" && fence_close_matches(line, "`", fence_len)) {
        in_fence = ""
        fence_len = 0
        # Closer найден — pending успешно стриплен, очищаем буфер.
        pending_count = 0
        print ""   # emit blank line = paragraph break для Stage 2 (E-4)
        next
      }
      if (in_fence == "TILDE" && fence_close_matches(line, "~", fence_len)) {
        in_fence = ""
        fence_len = 0
        pending_count = 0
        print ""   # emit blank line = paragraph break для Stage 2 (E-4)
        next
      }
      # Внутри fence — содержимое добавляется в pending buffer (не печатается).
      # Если closer не найдётся до EOF, END-блок восстановит этот буфер как
      # plain text (fail-safe против lone opener).
      pending_count++
      pending_lines[pending_count] = line
      next
    }
  }
  END {
    # Fail-safe для lone opener (Pass 2 G3, dolt-xn3): если EOF достигнут
    # при in_fence != "" (opener без closer того же типа), restore pending
    # buffer в output как plain text. Это защищает validator от fence-injection,
    # когда attacker пишет ```\nInjected CHANGES_REQUESTED\n(без closer) —
    # прежний код съедал хвост до EOF, пряча реальный вердикт в plain text,
    # и validator ложно видел только APPROVED выше.
    if (in_fence != "") {
      for (k = 1; k <= pending_count; k++) {
        print pending_lines[k]
      }
    }
  }
' | awk '
  # Стадия 2: per-line inline code span matcher (v3.5 Option B revert).
  #
  # v3.5 Option B (big-heroes-nw5): возврат к per-line scanning pre-bc6fe35.
  # CommonMark §6.1 допускает multi-line inline spans через newlines в рамках
  # параграфа, но paragraph-accumulation через sentinel \x01 (bc6fe35 E-2)
  # создал state-machine surface, в которую каждый tactical fix
  # E-10/E-11/E-12 (blockquote/setext/HTML-block terminators) вскрывал новые
  # CRITICAL findings. Proven минимум — per-line scan. Trade-off: multi-line
  # inline span внутри одного параграфа (opener на N-й строке, closer на N+1)
  # более не стрипается — safe default (validator видит opener + closer как
  # unmatched backticks → best-effort fallback ниже). Systemic CommonMark
  # покрытие — big-heroes-55m (Python rewrite, v3.6 sprint-opener).
  #
  # E-9 structural lines (ATX heading / list item / thematic break) — emit raw
  # без inline-сканирования: семантически structural-line не содержит code
  # spans в review-pass форматах (big-heroes-6bp: known limitation, если
  # reviewer поместит `CR` в ATX-heading — он проскочит как plain, validator
  # заблокирует real CR в plain path).
  #
  # Алгоритм per-span (E-3 escape + F-2-inline run-length):
  #   1. Найти backtick-run длины N в строке.
  #   2. Посчитать backslash-run ПЕРЕД ним. Нечётное число backslash-symbols →
  #      первый backtick экранирован (E-3); откусываем один backtick как
  #      literal, остаток run-а длиной N-1 продолжает span-поиск.
  #   3. Если effective run-length N ≥ 1 — ищем closer того же run-length N
  #      в пределах ТОЙ ЖЕ строки (per-line revert). В scan-loop escape
  #      НЕ учитывается (CommonMark §6.1: backslash escape не работают
  #      внутри code span content; E-8 semantics сохранена).
  #   4. Closer не найден в строке — opener + tail идут как plain text
  #      (safe default: лучше ложный block, чем hidden CR).
  function process_line(line,    n, out, i, c, bs, k, N, start,
                                 found_close_start, close_end, j, M, rj) {
    n = length(line)
    out = ""
    i = 1
    while (i <= n) {
      c = substr(line, i, 1)
      if (c != "`") {
        out = out c
        i++
        continue
      }
      # Нашли backtick-run. Считаем backslash-run перед ним (escape check, E-3).
      bs = 0
      k = i - 1
      while (k >= 1 && substr(line, k, 1) == "\\") { bs++; k-- }
      N = 0
      start = i
      while (i <= n && substr(line, i, 1) == "`") { N++; i++ }
      # Если нечётное число backslash перед — первый backtick экранирован.
      if ((bs % 2) == 1) {
        # Literal backtick (escaped): добавить в out один `.
        out = out "`"
        N--
        start++
      }
      if (N == 0) {
        # Полностью escaped (run был длины 1, после decrement 0). Продолжаем.
        continue
      }
      # Ищем closer — run ровно длины N в пределах этой же строки.
      # E-8 (CommonMark §6.1): escape НЕ применяется в scan-loop.
      found_close_start = 0
      close_end = 0
      j = i
      while (j <= n) {
        if (substr(line, j, 1) != "`") { j++; continue }
        M = 0
        rj = j
        while (rj <= n && substr(line, rj, 1) == "`") { M++; rj++ }
        if (M == N) {
          found_close_start = j
          close_end = rj - 1
          break
        }
        j = rj
      }
      if (found_close_start > 0) {
        # Валидный span — ни opener, ни content, ни closer не сохраняем.
        i = close_end + 1
      } else {
        # Closer не нашёлся в пределах строки — восстановим opener + остаток
        # строки как plain. Safe default: лучше ложно показать хвост и дать
        # validator-grep блокировать, чем съесть реальный CHANGES_REQUESTED.
        out = out substr(line, start, n - start + 1)
        i = n + 1
      }
    }
    return out
  }

  {
    # E-9 structural lines (CommonMark §4.1-4.4, §5.2/5.3): ATX heading,
    # bullet/ordered list item, thematic break — emit raw без inline scan.
    # Code spans в structural-line строках redki в review-pass output;
    # трактуются как plain text (known limitation, big-heroes-6bp).
    if ($0 ~ /^[ ]{0,3}#{1,6}([ \t]|$)/ ||
        $0 ~ /^[ ]{0,3}[-*+][ \t]/ ||
        $0 ~ /^[ ]{0,3}[0-9]+[.)][ \t]/ ||
        $0 ~ /^[ ]{0,3}(\*[ \t]*){3,}$/ ||
        $0 ~ /^[ ]{0,3}(-[ \t]*){3,}$/ ||
        $0 ~ /^[ ]{0,3}(_[ \t]*){3,}$/) {
      print $0
      next
    }
    print process_line($0)
  }
'
