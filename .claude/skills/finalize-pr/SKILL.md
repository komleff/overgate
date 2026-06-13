---
name: finalize-pr
description: Hard gate перед merge. Единственный разрешённый способ объявить PR готовым к merge. Проверяет commit binding (verify, internal review, external review для Sprint Final, статусы замечаний). Используй: /finalize-pr <PR_NUMBER> [--force] [--pre-landing]
user-invocable: true
---

# Finalize PR — hard gate перед merge

`/finalize-pr <PR_NUMBER>` — **единственный разрешённый способ** объявить PR готовым к merge. Чеклист «PM обязан проверить» в v2 был soft constraint и игнорировался — `/finalize-pr` превращает его в hard gate с привязкой к commit hash.

> ⛔ Прямой комментарий «готов к merge» / «ready to merge» в PR заблокирован hook-ом из `settings.json`. Используй только этот скилл.

## Аргументы

- `PR_NUMBER` — номер PR (обязательный)
- `--force` — emergency override **только по явной команде оператора** или при подтверждённой ошибке самого скилла. PM не имеет права инициировать `--force` самостоятельно.
- `--pre-landing` — explicit маркер **первого** вызова Sprint Final PR (до landing commit). Skill добавит строку `⏳ Pre-merge landing commit впереди — жди второй /finalize-pr, не мерджи сейчас.` в финальный комментарий — operator видит сигнал не мержить до второго вызова. Без флага — обычный merge-ready комментарий. PM передаёт `--pre-landing` для первого Sprint Final вызова, без флага — для второго (после landing commit). Detection explicit, без runtime autodetect (см. Dual-invocation pattern).

## Фаза 1: hard-проверки (commit + verify + review)

### Шаг 1: Зафиксировать HEAD commit hash

> Оборачивай все вызовы `gh pr view` в `timeout 10` — защита от зависания при медленном GitHub API.

```bash
HEAD_COMMIT=$(timeout 10 gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid' 2>/dev/null)

# null-guard: PR может быть закрыт/удалён/недоступен между шагами
if [ -z "$HEAD_COMMIT" ] || [ "$HEAD_COMMIT" = "null" ]; then
  echo "СТОП: не удалось получить HEAD commit PR #<PR_NUMBER>."
  echo "Возможные причины: PR закрыт/удалён, нет прав, API недоступен или таймаут."
  exit 1
fi

echo "Финализируем PR #<PR_NUMBER> на commit $HEAD_COMMIT"
```

Все дальнейшие проверки идут против **этого** commit. Если PR сменит HEAD во время выполнения скилла — придётся запускать заново.

### Шаг 2: Проверка `/verify` на текущем commit

Цель — убедиться, что build + test зелёные именно на $HEAD_COMMIT, а не на каком-то предыдущем.

```bash
# Локальный HEAD должен совпадать с PR HEAD
LOCAL_HEAD=$(git rev-parse HEAD)
if [ "$LOCAL_HEAD" != "$HEAD_COMMIT" ]; then
  echo "СТОП: локальный HEAD ($LOCAL_HEAD) не совпадает с PR HEAD ($HEAD_COMMIT)."
  echo "Выполни: gh pr checkout <PR_NUMBER>"
  exit 1
fi
```

Запусти `/verify`. Если упал — **СТОП**, скилл не публикует финальный комментарий, оператор получает ошибку.

### Шаг 3: Internal review-pass привязан к $HEAD_COMMIT?

PM публикует review-отчёты с двумя маркерами commit binding:
1. **Строка `Commit: <hash>`** в теле отчёта (под заголовком) — человекочитаемый маркер для оператора.
2. **JSON-метаданные** в HTML-комментарии (см. `PM_ROLE.md` секция 2.2): `<!-- {"reviewer": "...", "commit": "<hash>", ...} -->` — машинный маркер.

Скилл ищет **последний по времени** internal review-pass с `commit == $HEAD_COMMIT` через `jq` (сортировка по `createdAt`):

```bash
LAST_INTERNAL=$(timeout 10 gh pr view <PR_NUMBER> --json comments \
  | jq -r --arg head "$HEAD_COMMIT" '
      [ .comments[]
        | select(.body | test("review-pass|Внутреннее ревью"; "i"))
        | select(.body | test("\"commit\":\\s*\"" + $head + "\"|Commit:\\s*`?" + $head; "s"))
      ]
      | sort_by(.createdAt)
      | last
      | .body // empty
    ')

if [ -z "$LAST_INTERNAL" ]; then
  echo "СТОП: Internal review-pass отсутствует для commit $HEAD_COMMIT."
  echo "Запусти /sprint-pr-cycle для нового review-pass."
  exit 1
fi
echo "$LAST_INTERNAL" | head -30
```

> Используем `jq sort_by(.createdAt) | last` вместо `head -50`: при нескольких review-pass на одном commit (например, CHANGES_REQUESTED → APPROVED в одном цикле) берём именно последний, не первый.

Если последний review-pass на этом commit — **OK**.

### Шаг 4: External review для Sprint Final

Tier определяется автоматически из PR-метаданных, чтобы hard gate не зависел от ручной интерпретации. Sprint Final — это PR, который завершает спринт и готовится к merge в main. Признаки (любой ⇒ `sprint-final`):
- Метка `sprint-final` на PR;
- В описании PR (`body`) встречается строка `Tier: Sprint Final` (case-insensitive).

```bash
PR_META=$(timeout 10 gh pr view <PR_NUMBER> --json labels,body 2>/dev/null)

# null-guard: PR может быть закрыт/удалён между шагами
if [ -z "$PR_META" ]; then
  echo "СТОП: не удалось получить метаданные PR #<PR_NUMBER> (labels/body)."
  exit 1
fi

HAS_LABEL=$(echo "$PR_META" | jq -r '.labels[]?.name | select(. == "sprint-final")' | head -1)
# Любой `Tier:` в body — Sprint Final, Critical, Standard, Light.
# Наличие маркера (для обязательной эскалации при его отсутствии):
TIER_BODY_LINE=$(echo "$PR_META" | jq -r '.body // ""' | grep -iE '^Tier:[[:space:]]*(Sprint Final|Critical|Standard|Light)([[:space:]]|$)' | head -1)
# Sprint Final ищем среди ВСЕХ Tier-строк, а не только первой.
# Bug: `head -1` на общем grep прятал Sprint Final, если в body раньше
# встречался `Tier: Standard` (двойной маркер, старая строка + новая, цитата
# чужого PR). Silent downgrade → Sprint Final тихо классифицировался как
# standard и external review пропускался. Class: regression от round 1 fix.
HAS_SPRINT_FINAL_BODY=$(echo "$PR_META" | jq -r '.body // ""' | grep -iE '^Tier:[[:space:]]*Sprint Final([[:space:]]|$)' | head -1)

# Критический случай: нет НИ label, НИ строки Tier в body. Прежде чем
# молча классифицировать как standard (и пропустить external review),
# требуем явной эскалации. Это CRITICAL из external review GPT-5.4 round 12.
if [ -z "$HAS_LABEL" ] && [ -z "$TIER_BODY_LINE" ]; then
  echo "СТОП: PR #<PR_NUMBER> не маркирован tier'ом — нет ни label 'sprint-final',"
  echo "ни строки 'Tier: <Sprint Final|Critical|Standard|Light>' в body."
  echo "Добавь маркер через редактирование PR body (см. шаблон в"
  echo ".claude/skills/sprint-pr-cycle/SKILL.md шаг 1.3) и перезапусти /finalize-pr."
  echo "Тихая классификация как 'standard' запрещена — возможен пропуск external review."
  exit 1
fi

if [ -n "$HAS_LABEL" ] || [ -n "$HAS_SPRINT_FINAL_BODY" ]; then
  TIER="sprint-final"
elif echo "$PR_META" | jq -r '.body // ""' | grep -qiE '^Tier:[[:space:]]*Critical([[:space:]]|$)'; then
  TIER="critical"   # Critical без Sprint Final: второй проход обязателен, external опционален
else
  TIER="standard"  # явно маркирован как Standard/Light — и iteration 2, и external опциональны
fi
echo "Tier для финализации: $TIER"

# Hard gate: iteration >= 2 для Critical и Sprint Final.
# AGENT_ROLES.md и sprint-pr-cycle.md требуют два прохода внутреннего ревью
# для Critical tier (первый — полный, второй — adversarial с фокусом на
# пропущенном/регрессиях). GPT-5.4 round 14 CRITICAL #3: без этой проверки
# workflow требует два прохода, но hard gate верифицирует только один.
# Критерий: в META JSON последнего internal review-pass поле iteration >= 2.
if [ "$TIER" = "critical" ] || [ "$TIER" = "sprint-final" ]; then
  ITERATION=$(echo "$LAST_INTERNAL" \
    | grep -oE '"iteration"[[:space:]]*:[[:space:]]*[0-9]+' \
    | head -1 \
    | grep -oE '[0-9]+$')
  if [ -z "$ITERATION" ] || [ "$ITERATION" -lt 2 ]; then
    echo "СТОП: tier=$TIER требует iteration >= 2 для internal review (adversarial second pass)."
    echo "Текущий iteration в META: '${ITERATION:-не найден}'."
    echo "Запусти второй проход через /sprint-pr-cycle шаг 2.4 (Critical — второй проход)."
    echo "Каждый повторный review-pass увеличивает iteration в META JSON."
    exit 1
  fi
  echo "iteration check: ✅ (iteration=$ITERATION >= 2)"
fi
```

> Memory Bank как источник tier здесь **не используется**: hard gate должен опираться только на воспроизводимые PR-метаданные, иначе локальные расхождения дадут ложный пропуск external review.
>
> Канонический способ маркировать Sprint Final — строка `Tier: Sprint Final` в body PR. Шаблон создания PR в `.claude/skills/sprint-pr-cycle/SKILL.md` шаг 1.3 включает обязательное поле `Tier:`. Без этого маркера (и без label `sprint-final`) hard gate ошибочно классифицирует PR как `standard` и не потребует external review. Если PR создан вручную без `Tier:` — это эскалация к оператору, а не «finalize по тихому».

Если `TIER == sprint-final`:
```bash
LAST_EXTERNAL=$(timeout 10 gh pr view <PR_NUMBER> --json comments \
  | jq -r --arg head "$HEAD_COMMIT" '
      [ .comments[]
        | select(.body | test("Внешнее ревью"; "i"))
        | select(.body | test("\"commit\":\\s*\"" + $head + "\"|Commit:\\s*`?" + $head; "s"))
      ]
      | sort_by(.createdAt)
      | last
      | .body // empty
    ')

if [ -z "$LAST_EXTERNAL" ]; then
  echo "СТОП: External review обязателен для Sprint Final на commit $HEAD_COMMIT."
  echo "Запусти /external-review <PR_NUMBER>."
  exit 1
fi
```

- Если внешний review-pass на $HEAD_COMMIT есть — **OK**.
- `N/A` для Sprint Final **не допускается** — внешнее ревью обязательно.

> Используем тот же `jq sort_by(.createdAt) | last` паттерн: ищем маркер `Commit: <hash>` (человекочитаемый в теле) ИЛИ `"commit": "<hash>"` (в META JSON HTML-комментария). Оба варианта гарантированно присутствуют в шаблоне `external-review/SKILL.md` после обновления раунда фиксов Copilot.

**Hard gate на метку Degraded/Manual mode (инвариант 6 → честный audit trail):**

Если в тексте последнего `external review-pass` найден маркер режима `C` или `D` (degraded режимы), в теле комментария **обязана** присутствовать метка:
- Для режима C: `⚠️ Degraded mode`
- Для режима D: `⚠️ Manual emergency mode`

Здесь hard gate опирается именно на содержимое `$LAST_EXTERNAL`. Отдельного парсинга HTML-комментария META нет, поэтому учитываются только те маркеры, которые реально матчатся в тексте комментария (`Режим: C/D` как стабильный заголовок из шаблона `external-review` или `Mode: C/D` / `"mode": "C"` как fallback, если PM дополнительно включил машинный маркер в тело).

Без метки Sprint Final ложно маркируется как cross-model review. Финализация заблокирована:

```bash
# $LAST_EXTERNAL уже содержит тело последнего external review-pass на $HEAD_COMMIT
# Матчим допустимые текстовые маркеры режима в самом комментарии:
#   1) человекочитаемый заголовок «Режим: C» / «Режим: D» (всегда в шаблоне external-review)
#   2) машинный маркер «Mode: C» / `"mode": "C"`, если он присутствует в тексте комментария
#
# Copilot round 26: сначала убираем HTML-комментарии, чтобы grep не матчился на
# неактивные шаблонные метки `⚠️ ...` внутри <!-- ... --> (после round 25
# обе строки по умолчанию внутри HTML-комментария).
VISIBLE_EXTERNAL=$(echo "$LAST_EXTERNAL" | sed '/<!--/,/-->/d')
if echo "$VISIBLE_EXTERNAL" | grep -qE '(Режим|Mode)[:"]*[[:space:]]*"?[CD]([[:space:]]|"|$)'; then
  # Degraded/Manual режим — нужна метка
  if ! echo "$VISIBLE_EXTERNAL" | grep -qE '⚠️ (Degraded mode|Manual emergency mode)'; then
    echo "СТОП: external review в режиме C/D без обязательной метки '⚠️ Degraded mode' / '⚠️ Manual emergency mode'."
    echo "PM должен опубликовать новый external review-pass с меткой."
    exit 1
  fi
fi
```

> **Почему два маркера.** Шаблон `external-review/SKILL.md` использует человекочитаемый заголовок «**Режим: [A/B/C/D]**» — это стабильный якорь (проверено Copilot в раунде 2: предыдущий паттерн `mode: C|D` не матчился ни с одним реальным отчётом). Регексп с альтернативой `(Режим|Mode)` закрывает оба варианта — включая случай, когда PM дополнительно включает `Mode: C` в META JSON.

Если `TIER != sprint-final` — external review **опционален**. Если он есть на $HEAD_COMMIT — отметить, если нет — `N/A`.

### Шаг 5: Повторный review после CHANGES_REQUESTED

Если внешний review (или внутренний) когда-либо возвращал `CHANGES_REQUESTED`, после фиксов **обязателен** повторный review-pass на $HEAD_COMMIT с APPROVED — **отдельно для каждого канала** (internal и external).

> ⛔ **Нельзя проверять один общий «последний» review-pass среди internal+external.** Более поздний internal `APPROVED` может скрыть актуальный external `CHANGES_REQUESTED` на том же commit, и hard gate даст ложный пропуск. Каждый канал валидируется независимо: `LAST_INTERNAL` (из шага 3) и `LAST_EXTERNAL` (из шага 4).

```bash
# Хелпер: hard gate по одному review-pass-каналу на $HEAD_COMMIT.
# Проверяет два условия (см. round 8 finding):
#   1) в теле НЕТ ни одного CHANGES_REQUESTED (иначе один из аспектов
#      или ревьюеров сигналит CHANGES_REQUESTED, скрытый поздним APPROVED);
#   2) в теле есть хотя бы один APPROVED.
#
# Предобработка strip_code_spans.sh (Sprint v3.5, big-heroes-nw5):
# вхождения CHANGES_REQUESTED и APPROVED внутри inline code spans
# (парные одиночные бэктики) и fenced code blocks (тройные бэктики)
# — это historical/narrative цитаты в review-pass комментариях,
# они НЕ должны матчиться regex'ом. Раньше бэктики попадали в
# non-[A-Z_] boundary и давали infrastructure false positive
# (v3.4 PR #14: narrative «оснований для `CHANGES_REQUESTED` не
# вижу» блокировал hard gate при реальном Вердикт: APPROVED).
# Stripper читает тело из stdin и возвращает текст с вырезанными
# code spans, затем grep работает на plain text. Реальные вердикты
# в plain text продолжают блокировать/пропускать как раньше.
# Unit-тесты: .claude/skills/finalize-pr/validators/test_validate_review_pass.sh.
validate_review_pass_body() {
  local review_kind="$1"   # "internal" | "external"
  local review_body="$2"

  if [ -z "$review_body" ]; then
    echo "СТОП: не найден ${review_kind} review-pass на $HEAD_COMMIT."
    echo "Hard gate требует отдельный review-pass на текущем commit для каждого обязательного канала."
    exit 1
  fi

  # Mask code spans перед regex-проверкой (strip_code_spans.sh — stdin→stdout).
  # Pass 3 Copilot CP-3 (закрывает dolt-hta): используем absolute path через
  # git rev-parse --show-toplevel. Прежний relative путь ломался если
  # /finalize-pr вызывался из subdirectory (cwd != repo root) → stripper
  # не найден → fail-secure fallback на raw grep, где backtick-wrapped
  # CHANGES_REQUESTED снова триггерит infrastructure false positive.
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "СТОП: не удалось определить корень git-репозитория для strip_code_spans."
    echo "Повтори запуск /finalize-pr из git-репозитория."
    exit 1
  }

  local stripper_path="${repo_root}/.claude/skills/finalize-pr/validators/strip_code_spans.sh"
  if [ ! -f "$stripper_path" ]; then
    echo "СТОП: не найден stripper по пути: $stripper_path"
    echo "Убедись, что .claude/skills/finalize-pr/validators/ присутствует в репо."
    exit 1
  fi

  # Pass 4 CX-2: fail-secure exit-code проверка stripper'а.
  # Прежняя форма `stripped_body=$(... | bash "$stripper_path")` игнорировала
  # exit code stripper'а — при segfault/ошибке переменная получала пустую
  # строку, grep не находил ни CHANGES_REQUESTED ни APPROVED, validator
  # fall-through на «нет APPROVED → СТОП». Это корректный fail-secure, но
  # маскирует реальную ошибку: оператор видит «нет APPROVED», а не «stripper
  # упал». Явная if-guard: если stripper упал — немедленная остановка
  # с диагностикой, без попыток grep'ать мусор.
  local stripped_body
  if ! stripped_body=$(printf '%s' "$review_body" | bash "$stripper_path"); then
    echo "СТОП: strip_code_spans.sh завершился с ошибкой при проверке ${review_kind} review-pass."
    echo "Это fail-secure остановка: sanitizer review-pass не отработал, поэтому продолжать проверку небезопасно."
    exit 1
  fi

  if printf '%s\n' "$stripped_body" | grep -qE '(^|[^A-Z_])CHANGES_REQUESTED([^A-Z_]|$)'; then
    echo "СТОП: в последнем ${review_kind} review-pass на $HEAD_COMMIT есть CHANGES_REQUESTED по одному из аспектов/ревьюеров."
    echo "После CHANGES_REQUESTED обязателен повторный ${review_kind} review-pass с APPROVED по всем аспектам на текущем commit."
    exit 1
  fi

  if ! printf '%s\n' "$stripped_body" | grep -qE '(^|[^A-Z_])APPROVED([^A-Z_]|$)'; then
    echo "СТОП: в последнем ${review_kind} review-pass не найден APPROVED."
    echo "Проверь, что отчёт публикуется по шаблону sprint-pr-cycle и содержит явный 'Вердикт: APPROVED'."
    exit 1
  fi
}

# Internal review-pass обязателен всегда (LAST_INTERNAL получен в шаге 3).
validate_review_pass_body "internal" "$LAST_INTERNAL"

# External review-pass обязателен ТОЛЬКО для Sprint Final
# (LAST_EXTERNAL получен в шаге 4 и пустой при TIER != sprint-final).
if [ "$TIER" = "sprint-final" ]; then
  validate_review_pass_body "external" "$LAST_EXTERNAL"
fi
```

### Known limitations (v3.5, deferred to v3.6)

Awk-based CommonMark stripper покрывает базовый subset spec:
- Fenced code blocks (backtick/tilde, 0-3 indent, info-string validation для backtick-fences);
- Inline code spans (N-backtick run-length matching, per-line scanning, backslash-escape для opener);
- Structural line recognition (ATX heading `#`, list item `-*+`, thematic break `---`/`***`/`___`) — emit raw без inline-scan.

**Не покрыто (deferred до Python rewrite — `big-heroes-55m` P1 v3.6 sprint-opener):**

1. **Multiline inline spans** (opener на строке N, closer на строке N+1) — `big-heroes-55m`. v3.5 Option B revert per-line scanning; multi-line спаны трактуются как unmatched backticks → safe default (fallback в plain text, validator блокирует).
2. **Blockquote** (`>` prefix) как paragraph terminator — `big-heroes-36d`.
3. **Setext heading** (`===` / `---` underline) как paragraph terminator — `big-heroes-42a`.
4. **HTML block** (`<div>`, `<details>`, CommonMark §4.6 block tags) как terminator — `big-heroes-zhe`.
5. **Structural-line inline strip** — ATX heading / list item lines emit raw; inline `` `CR` `` в structural-line survives — `big-heroes-6bp` (P2, theoretical false APPROVED).
6. **Ellipsis U+2026 terminator** — оставлено для hook (уже покрыто), не stripper-concern.
7. **Hook Po overmatch:** `:` в backtick quote (`big-heroes-16e`), `/` `.` в paths/branches (`big-heroes-3ed`), `Pe`/`Pd` broad categories (`big-heroes-ytx`).

Low exploitability: требуют malicious reviewer с specific markdown construct. Systemic Python rewrite в v3.6 (`big-heroes-55m`) решает все пункты вместе, на единой AST-based реализации с полным CommonMark-покрытием.

### Debug / regression helpers

Помощники для отладки stripper'а и проверки регрессий — запускаются вручную PM'ом при подозрении на infrastructure false positive / false negative, не вызываются автоматически из hard gate.

- `.claude/skills/finalize-pr/validators/test_validate_review_pass.sh` — unit-тесты stripper'а; актуальный набор кейсов и их число смотри в самом скрипте.
- `.claude/skills/finalize-pr/validators/regression_pr183.sh` — regression prove на реальной истории PR #183 U2 (VC-5; baseline сменён с big-heroes PR #14 при импорте в U2). Требует `$COMMENTS_DIR` с раскладкой `c*.txt` (см. docstring скрипта). Запуск:
  ```bash
  mkdir -p /tmp/pr183_comments
  for i in $(seq 0 24); do
    gh pr view 183 --json comments -q ".comments[$i].body" > /tmp/pr183_comments/c$i.txt
  done
  bash .claude/skills/finalize-pr/validators/regression_pr183.sh
  ```

## Фаза 2: triage-проверки

> Активируется автоматически после внедрения triage-протокола (план v3.3 шаг 1.4 — реализован в `PM_ROLE.md` секция 2.3 и `AGENT_ROLES.md`). До внедрения триажа фаза 2 пропускается, публикуется шаблон фазы 1.

### Шаг 6: статус каждого замечания

> ⚠️ **Гибридный gate (часть автоматически, часть PM-вручную).** В отличие от фаз 1.1–1.5 (полностью bash+jq), здесь автоматика проверяет только **наличие и формат Beads ID** для строк-таблиц с `defer to Beads` и **наличие текста-обоснования** для `reject with rationale`. Связь fix-now-замечания с конкретным закрывающим APPROVED-аспектом, как и распознавание «обоснование не пустое», PM выполняет вручную — это явный manual-check, не автоматический hard gate. Не считай фазу 2 безусловным предохранителем.

Каждое замечание из internal/external review должно иметь явный статус, проставленный PM:

| Статус | Валидация |
|--------|-----------|
| **fix now** | Должен быть закрыт (повторный review-pass на $HEAD_COMMIT с APPROVED для затронутого аспекта) — **проверяет PM вручную** |
| **defer to Beads** | **Обязателен Beads ID** (автопроверка: `bd show <id>` приоритет, fallback regex `[A-Za-z][A-Za-z0-9-]+-[a-z0-9]+` — case-insensitive prefix покрывает `U2-*` и `big-heroes-*`) |
| **reject with rationale** | **Обязательно обоснование** в PR comment — **проверяет PM вручную** (автоматика только убеждается, что в той же строке таблицы есть непустой текст после статуса) |

**Минимальная автоматика для defer/reject (выполняется скиллом):**

```bash
# Извлекаем все строки markdown-таблиц с triage-статусами из review-pass на $HEAD_COMMIT.
# Шаблон reviewer.md фиксирует формат:
#   | # | Severity | Заголовок | Файл:строка | Статус | Beads ID / Обоснование |
# Regex допускает пробелы вокруг статуса (шаблон в reviewer.md публикует
# `| fix now |` именно с пробелами — строгое сопоставление даёт silent skip).
# ⚠️ Перед grep/split снимаем экранирование `\|` → ASCII 0x1F (Unit Separator).
# Reviewer'ы пишут `\|` в ячейках, чтобы markdown-рендер не ломал таблицу
# (шаблон в reviewer.md это явно разрешает). Без предобработки IFS='|'
# расщепляет строку по самому `|` из `\|` и колонки сдвигаются
# (status → path:1, payload → «defer to Beads») — это parser-contract bypass
# (GPT-5.4 round 32 CRITICAL). 0x1F выбран как не-печатаемый управляющий
# символ (Record Separator area), никогда не встречающийся в содержимом
# markdown-комментария. После IFS-split восстанавливаем в каждой колонке.
# SEP передаётся переменной, чтобы не полагаться на GNU-специфичный `\x1f`
# в replacement-части sed (BSD/macOS sed его не поддерживает).
SEP=$(printf '\037')
TRIAGE_ROWS=$(timeout 10 gh pr view <PR_NUMBER> --json comments \
  | jq -r --arg head "$HEAD_COMMIT" '
      .comments[]
      | select(.body | test("review-pass|Внутреннее ревью|Внешнее ревью"; "i"))
      | select(.body | test("\"commit\":\\s*\"" + $head + "\"|Commit:\\s*`?" + $head; "s"))
      | .body
    ' \
  | sed "s/\\\\|/${SEP}/g" \
  | grep -E '^\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|[[:space:]]*(fix now|defer to Beads|reject with rationale)[[:space:]]*\|' || true)

# Каждая строка triage: проверь пятую колонку (Статус) и шестую (Beads ID / Обоснование).
#
# ⚠️ Используем here-string `<<<`, не pipe `echo "$TRIAGE_ROWS" |`, чтобы
# `exit 1` завершал родительский процесс скилла, а не только subshell
# pipeline'а. Pipe-форма создаёт subshell → `exit 1` внутри while
# выходит ТОЛЬКО из subshell, skill продолжает выполнение и публикует
# `## ✅ Готов к merge` несмотря на невалидный Beads ID / пустой rationale.
# Это fake gate (GPT-5.4 round 13 CRITICAL).
TRIAGE_FAILED=0
while IFS='|' read -r _ num severity title loc status payload _; do
  [ -z "$num" ] && continue   # пропускаем пустые строки (шапки/separators)
  # Восстанавливаем экранированные `|` в каждой колонке (см. sed выше).
  status=$(printf '%s' "$status" | tr '\037' '|' | xargs)   # trim + unescape
  payload=$(printf '%s' "$payload" | tr '\037' '|' | xargs)

  case "$status" in
    "defer to Beads")
      # 1) Приоритет: проверка существования через bd show (с timeout — защита от зависания)
      if command -v bd >/dev/null 2>&1; then
        if ! timeout 10 bd show "$payload" >/dev/null 2>&1; then
          bd_exit=$?
          if [ "$bd_exit" -eq 124 ]; then
            echo "СТОП: defer-замечание #$num — timeout при проверке Beads ID '$payload'. Проверь окружение Beads и повтори /finalize-pr."
            TRIAGE_FAILED=1
          else
            echo "СТОП: defer-замечание #$num ссылается на Beads ID '$payload', но bd show не находит задачу."
            TRIAGE_FAILED=1
          fi
        fi
      # 2) Fallback: regex без хардкода префикса
      elif ! echo "$payload" | grep -qE '^[A-Za-z][A-Za-z0-9-]+-[a-z0-9]+$'; then
        echo "СТОП: defer-замечание #$num имеет невалидный Beads ID '$payload' (regex fallback)."
        TRIAGE_FAILED=1
      fi
      ;;
    "reject with rationale")
      # Пустое обоснование = неразрешённое замечание
      if [ -z "$payload" ] || [ "$payload" = "—" ] || [ "$payload" = "-" ]; then
        echo "СТОП: reject-замечание #$num не имеет обоснования в шестой колонке."
        TRIAGE_FAILED=1
      fi
      ;;
  esac
done <<< "$TRIAGE_ROWS"

if [ "$TRIAGE_FAILED" = "1" ]; then
  exit 1
fi
```

**PM-вручную (после автопроверок выше):**

- Для каждого `fix now` пройдись по review-pass на `$HEAD_COMMIT` и убедись, что аспект, к которому относится замечание, имеет `APPROVED` (это ловит регрессии: фикс «починил архитектуру», но reviewer вернул `CHANGES_REQUESTED` по гигиене).
- Для каждого `reject with rationale` прочитай payload и убедись, что обоснование осмысленное, а не «no» / «later». Автопроверка ловит только пустоту/прочерк.

> **Почему не хардкодим `bd-*`:** в репозитории фактические Beads ID имеют префикс `U2-*` (см. `.memory-bank/activeContext.md`, в исходном big-heroes префикс был `big-heroes-*`). Regex `bd-[a-z0-9]+` прошлой версии не покрывал их — все defer были бы ложно отвергнуты как «без ID». Правильный порядок проверки:
> 1. Попробовать `bd show <id>` (если доступен) → если issue существует → OK.
> 2. Если `bd` недоступен → regex `[A-Za-z][A-Za-z0-9-]+-[a-z0-9]+` как fallback (case-insensitive проверка формата, не существования; покрывает `U2-*` и `big-heroes-*`).
> 3. Если ни то, ни другое не прошло → замечание считается неразрешённым.

Если хотя бы одно замечание без статуса/ID/обоснования — **СТОП**:
```
СТОП: замечание #N («<краткая цитата>») не имеет статуса.
Допустимые: fix now / defer to Beads (с ID) / reject with rationale.
```

### Шаг 7: warning при defer-abuse (>50%)

Подсчитай долю замечаний со статусом `defer`:
```
defer_ratio = count(deferred) / count(all_findings)
```

Если `defer_ratio > 0.5` — **warning** (не блокировка):
```
⚠️ ВНИМАНИЕ: >50% замечаний отложены в Beads. Это сигнал defer-abuse —
PR может быть откладывается «на потом» вместо реальных фиксов.
Оператор: проверь Beads issues перед merge.
```

Warning публикуется в финальном комментарии и в чат оператору. Не блокирует merge — это сигнал для оператора, не hard gate (план v3.3 секция 1.4 «Защита от defer-abuse»).

### Сбор данных для финального шаблона

```bash
UNRESOLVED=$(...)              # 0 при штатном ходе после фазы 2
DEFERRED_LIST="bd-001, bd-042" # ID из таблицы триажа
DEFER_RATIO=42                 # % defer от общего числа замечаний
```

## Финальный комментарий

> **Безопасность токена:** `FINALIZE_PR_TOKEN` передаётся как **inline-переменная** в один вызов `gh pr comment` и живёт только для этого процесса. Не используй `export` + `unset` — если скилл упадёт между ними, токен останется в окружении, и следующий ручной `gh pr comment --body "готов к merge"` обойдёт блокировку. Inline-форма `VAR=val cmd ...` устанавливает переменную только для подпроцесса `cmd`, это гарантия очистки без `trap`.

### Re-check HEAD перед публикацией (защита от race condition)

> ⛔ Между шагами 1–5 (фиксация HEAD + проверки) и публикацией финального комментария может пройти 5–30 секунд. За это время в ветку PR может попасть новый commit (параллельный push, force-push, rebase). Если этого не проверить — финальный комментарий объявит `Готов к merge` для commit, который уже не является HEAD-ом.

Перед публикацией финального комментария **обязательно** перепроверь HEAD:

```bash
HEAD_NOW=$(timeout 10 gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid' 2>/dev/null)

if [ "$HEAD_NOW" != "$HEAD_COMMIT" ]; then
  echo "СТОП: HEAD изменился во время выполнения /finalize-pr."
  echo "  Был при старте: $HEAD_COMMIT"
  echo "  Текущий:        $HEAD_NOW"
  echo "Запусти /finalize-pr <PR_NUMBER> заново на новом commit."
  exit 1
fi
```

Если HEAD не изменился — переходи к публикации. Если изменился — **СТОП**, нужен новый запуск скилла на актуальном commit.

### Dual-invocation pattern (pre-merge landing, v3.4+)

> С v3.4 skill вызывается **дважды** за жизненный цикл PR Sprint Final:
>
> 1. Первый вызов — на HEAD после review cycle. Hard gate APPROVED →
>    публикация первого `## ✅ Готов к merge`.
> 2. PM в той же ветке делает `chore(landing):` commit (`.memory-bank/activeContext.md` + plan archive
>    + bd close + memory entry — см. `sprint-pr-cycle/SKILL.md` Фаза 4.5).
>    HEAD меняется.
> 3. Второй вызов — на новом HEAD (landing commit). Hard gate прогоняется
>    заново; existing HEAD re-check (шаг 1 + protection re-check перед публикацией)
>    корректно обрабатывает смену SHA.
>
> Второй вызов требует **свежего review-pass** на landing commit — это
> Фаза 4.5.6 в sprint-pr-cycle (doc-only Light tier review).

Skill поддерживает dual-invocation **без специальной логики**: каждый запуск
строит hard gate с нуля от `HEAD_COMMIT = gh pr view --json headRefOid`. Если
ветка сменила HEAD между вызовами — второй запуск видит новый commit как
«текущий», все 5 шагов (verify + internal + external + triage + re-check)
работают штатно.

**Что это НЕ означает:**

- НЕ означает, что skill должен «запомнить» первый вызов. Второй запуск
  идемпотентен в смысле гейта, не в смысле state.
- НЕ означает, что landing commit освобождает от external review для
  Sprint Final. Если tier = sprint-final, external review обязателен **и на
  landing HEAD тоже** (хотя изменения чисто документация, допустима degraded
  Mode A-hybrid / A-legacy / C / D с operator-approved rationale).

См. `.claude/skills/sprint-pr-cycle/SKILL.md` Фаза 4.5 для полного flow
landing commit.

### Pre-landing warning (для `--pre-landing` флага)

Если skill вызван с `--pre-landing`, в шаблон финального комментария добавляется строка-предупреждение, чтобы оператор не мержил PR до landing commit + второго `/finalize-pr`:

```bash
# Argument parsing: set PRE_LANDING=1, если флаг --pre-landing передан.
# По умолчанию 0 — warning не печатается.
# Обрабатываем список аргументов из slash-command invocation
# (`/finalize-pr 14 --pre-landing` → $@ = "14 --pre-landing").
PRE_LANDING=0
for arg in "$@"; do
  if [ "$arg" = "--pre-landing" ]; then
    PRE_LANDING=1
    break
  fi
done

if [ "$PRE_LANDING" = "1" ]; then
  LANDING_WARNING="⏳ Pre-merge landing commit впереди — жди второй /finalize-pr, не мерджи сейчас. См. .claude/skills/sprint-pr-cycle/SKILL.md Фаза 4.5."
else
  LANDING_WARNING=""
fi
```

Подстановка через bash `${VAR:+...}` — текст печатается только если переменная не пуста.

### Шаблон фазы 1 (до внедрения triage-протокола)

```bash
FINALIZE_PR_TOKEN=1 gh pr comment <PR_NUMBER> --body "## ✅ Готов к merge

Commit: $HEAD_COMMIT
Verify: ✅
Internal review: ✅ (commit $HEAD_COMMIT)
External review: <✅ (commit $HEAD_COMMIT) | N/A>${LANDING_WARNING:+

$LANDING_WARNING}

— PM (Claude Opus 4.6), /finalize-pr"
```

### Шаблон фазы 2 (после внедрения triage-протокола)

```bash
FINALIZE_PR_TOKEN=1 gh pr comment <PR_NUMBER> --body "## ✅ Готов к merge

Commit: $HEAD_COMMIT
Verify: ✅
Internal review: ✅ (commit $HEAD_COMMIT)
External review: <✅ (commit $HEAD_COMMIT) | N/A>
Unresolved findings: $UNRESOLVED
Deferred to Beads: $DEFERRED_LIST${LANDING_WARNING:+

$LANDING_WARNING}

<если defer_ratio > 50%>
⚠️ ВНИМАНИЕ: $DEFER_RATIO% замечаний отложены в Beads. Проверь перед merge.
</если>

— PM (Claude Opus 4.6), /finalize-pr"
```

Этот вызов обходит hook блокировки «ready to merge» только для одной команды. После завершения `gh pr comment` переменная автоматически исчезает из окружения — гарантия, которой `export`/`unset` не даёт при сбое между ними.

## Emergency override `--force`

Инвокация:
```
/finalize-pr <PR_NUMBER> --force
```

Условия использования:
- **Только** по явной команде оператора в чате («запусти /finalize-pr 42 --force»);
- ИЛИ при зафиксированной ошибке самого скилла (например, GitHub API не отвечает).

PM **не имеет права** инициировать `--force` самостоятельно.

При `--force`:
1. Скилл **не пропускает** проверки 1–5, а **публикует их состояние вручную**:
   ```bash
   gh pr comment <PR_NUMBER> --body "## ⚠️ Force finalize: <причина>

Commit: $HEAD_COMMIT
Verify: <✅/❌/не проверено>
Internal review: <состояние>
External review: <состояние>

Force-причина: <обязательное обоснование оператора>

— PM (Claude Opus 4.6), /finalize-pr --force"
   ```
2. Метка `⚠️ Force finalize` обязательна — оператор по этой метке решает, мержить или нет.
3. `--force` bypass-ит только сломанный механизм автоматической валидации, не сами проверки. Если оператор знает, что какой-то gate не пройден — он берёт ответственность на себя.

## Шаг финального gate (после публикации)

После успешной публикации скилл:
1. Не делает merge автоматически (инвариант 7: merge — отдельное решение оператора).
2. Сообщает оператору в чат: «Опубликован финальный комментарий в PR #<N>. Решение о merge — за тобой.»

## Что НЕ делает фаза 1

- Не проверяет статус замечаний (fix now / defer / reject) — это фаза 2 (после внедрения triage-протокола).
- Не проверяет defer >50% warning — это фаза 2.
- Не обновляет Memory Bank — это делает PM в шаге Landing the Plane (`PM_ROLE.md` 2.5).

## Защита от обхода

| Попытка обхода | Реакция |
|----------------|---------|
| Прямой `gh pr comment` с «готов к merge» | Заблокирован hook'ом в `settings.json` |
| `gh pr merge` | Заблокирован deny-правилом в `settings.json` |
| `/finalize-pr` без проверок | Скилл сам обеспечивает порядок проверок; короткий путь невозможен |
| `--force` PM-ом самостоятельно | Запрещено правилом скилла; обязательная пометка `⚠️ Force finalize` делает обход видимым оператору |
