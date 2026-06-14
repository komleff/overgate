---
name: sprint-pr-cycle
description: Оркестрация полного PR-цикла спринта — от создания PR до готовности к merge. Контролирует порядок шагов, запуск субагентов, публикацию отчётов. Используй когда PM завершил кодирование спринта и готов к ревью-циклу.
user-invocable: true
---

# Sprint PR Cycle

Оркестратор полного ревью-цикла спринта. Ведёт PM по обязательным шагам, не позволяя пропустить ни один.

## Контекст

Прочитай перед началом:
- `.agents/AGENT_ROLES.md` — роли и правила
- `.memory-bank/activeContext.md` — текущее состояние

## Инвариант review-pass

Каждый review-pass считается завершённым только после публикации отчёта в PR через `gh pr comment`.

Обязательная последовательность для любого прохода:
1. Сформировать вердикт или summary текущего прохода.
2. Опубликовать его в PR через `gh pr comment`.
3. Подтвердить, что публикация успешна; зафиксировать ссылку на комментарий, если она доступна.
4. Только после этого переходить к следующему шагу цикла или писать оператору о результате.

> ⛔ Чат-резюме без PR comment не завершает review-pass.
> ⛔ Термин «финальный ответ» не используется как gate для ревью; gate = успешная публикация текущего прохода.

## Фаза 1: Подготовка PR

### Шаг 1.1: Проверка готовности

Запусти единый gate:

```
/verify
```

> `/verify` — единая точка проверки (build + test). При расширении пайплайна (linter, typecheck) добавляется туда, чтобы не было расползания проверок по скиллам.

Если `/verify` упал — **СТОП**. Исправь перед продолжением.

### Шаг 1.2: Push всех изменений

```bash
git status --porcelain
git push
```

### Шаг 1.3: Создание PR

```bash
BRANCH=$(git branch --show-current)
gh pr list --head "$BRANCH" --json number,title --jq '.[0]'
```

Если PR не найден — создай. **Обязательно укажи `Tier:` в body** — `/finalize-pr` использует его для автодетекта Sprint Final (без маркера hard gate ошибочно классифицирует PR как `standard` и не потребует external review):

| Tier в body | Когда указывать |
|-------------|-----------------|
| `Tier: Sprint Final` | PR завершает спринт и идёт к merge в main (требует `/external-review`) |
| `Tier: Critical` | shared/, config/balance.json, нормативные артефакты пайплайна |
| `Tier: Standard` | Фичи, рефакторинг, обычные PR |
| `Tier: Light` | Только документация |

```bash
TIER_LINE="Tier: Standard"  # или Sprint Final / Critical / Light — см. таблицу выше

# Quoted heredoc с high-entropy делимитером блокирует shell-расширения внутри тела:
# Summary/Issues могут содержать $VAR, $(...), backticks от пользовательских
# значений — без кавычек bash раскроет их и исказит/выполнит подстановку.
# $TIER_LINE подставляется через bash parameter expansion после.
# Перед запуском команды сгенерируй fresh suffix: `openssl rand -hex 8`.
# Замени <RAND> в обеих строках делимитера и проверь, что тело не содержит
# выбранный делимитер как отдельную строку.
BODY=$(cat <<'GH_BODY_<RAND>'
__TIER_LINE__

## Summary
- [список ключевых изменений]

## Issues
- [список закрытых beads issues]

## Test plan
- [ ] /verify

🤖 Generated with [Claude Code](https://claude.com/claude-code)
GH_BODY_<RAND>
)
BODY="${BODY//__TIER_LINE__/$TIER_LINE}"
gh pr create --title "Sprint N: [краткое описание]" --body "$BODY"
```

> Sprint Final дополнительно полезно помечать GitHub-меткой `sprint-final` (если права позволяют) — `/finalize-pr` видит ОБА маркера: label ИЛИ `Tier: Sprint Final` в body. Достаточно одного, body-маркер канонический и работает без прав на labels.

## Фаза 2: Внутреннее ревью

### Шаг 2.0a: Чтение Copilot auto-review (ОБЯЗАТЕЛЬНО)

> ⚠️ **Copilot автоматически запускает review при создании PR.** Его комментарии появляются в PR в течение 1–3 минут после `gh pr create`. **PM ОБЯЗАН** прочитать их **до запуска** reviewer-субагентов — иначе findings Copilot'а не попадут в triage и могут быть пропущены (реальный случай: PR #9 пропустил 7 Copilot-замечаний в 10 раундах ревью).

Выгрузка комментариев Copilot:

```bash
# Все review-треды (комментарии, привязанные к строкам кода)
timeout 10 gh pr view <PR_NUMBER> --json reviews \
  | jq -r '.reviews[] | select(.author.login | contains("copilot-pull-request-reviewer")) | .body' \
  | head -200

# Комментарии на уровне файлов/строк — через MCP (или gh api)
timeout 10 gh api repos/OWNER/REPO/pulls/<PR_NUMBER>/comments \
  | jq -r '.[] | select(.user.login | contains("copilot")) | "\(.path):\(.line) — \(.body)"'
```

Для каждого Copilot-findings:
- Если валиден → добавь в triage как `fix now` / `defer to Beads` / `reject with rationale`.
- Помечай в консолидированном отчёте как `**[Copilot]**` (атрибуция источника).

### Шаг 2.0b: Запрос повторного Copilot re-review после фиксов (ОБЯЗАТЕЛЬНО)

> ⛔ **Инвариант auto-loop.** После КАЖДОГО push с фиксами Copilot findings PM **немедленно** запрашивает re-review — без напоминания оператора, в том же сообщении, что и сам push. Без явного запроса Copilot не реагирует на push автоматически: review-loop тихо останавливается, и оператор видит «жду ответа», когда на самом деле ничего не запрошено.
>
> Реальный случай (PR #9): за сессию дважды пришлось вручную напоминать «ты запросил re-review?» — каждый пропуск саботирует автоматизацию пайплайна. Это hard rule, не soft guideline.

Сразу после `git push` (без промежуточных шагов):

```bash
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
gh api "repos/$REPO/pulls/<PR_NUMBER>/requested_reviewers" \
  --method POST -f 'reviewers[]=copilot-pull-request-reviewer[bot]' \
  && echo "Copilot: re-review requested" \
  || echo "Copilot: request failed"
```

Через MCP (если `gh` недоступен): `mcp__github__request_copilot_review`.

> ⛔ Сообщение оператору вида «жду Copilot re-review» **запрещено**, если запрос фактически не отправлен. Если запрос не отправляется (нет прав, ошибка API) — это эскалация, а не «жду».

### Шаг 2.0: Определение review tier (ОБЯЗАТЕЛЬНО)

Tier выбирается по содержимому изменений PR:

| Tier | Когда | Ревью |
|------|-------|-------|
| **Light** | Только документация (`.md`), конфиги без логики | Один проход, аспекты «Архитектура» и «Гигиена кода» |
| **Standard** | Фичи, рефакторинг, обычные PR | Один проход, все 4 аспекта параллельно |
| **Critical** | Изменения в `shared/`, `config/balance.json`, игровая логика, формулы, **нормативные артефакты пайплайна** (`.claude/settings.json` hooks, `.claude/hooks/*`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.agents/*.md` — governance-документы AGENT_ROLES/PM_ROLE/AGENTIC_PIPELINE) | Tester gate + два прохода, все 4 аспекта |
| **Sprint Final** | PR, завершающий спринт (готовится к merge в main) | Standard/Critical + обязательный `/external-review` (Sprint Pipeline v3.9: Mode A primary — Codex CLI ChatGPT subscription через `[profiles.review]`; Mode A-legacy — Node.js native через `.claude/tools/openai-review.mjs` Platform API; см. ADR 3.27) |

Определение tier:
```bash
# Copilot round 20: хардкоженый /tmp/pr-files.txt ломал параллельные
# запуски и не работает на окружениях без /tmp. mktemp + trap cleanup.
PR_FILES="$(mktemp)"
trap 'rm -f "$PR_FILES"' EXIT
gh pr diff <PR_NUMBER> --name-only > "$PR_FILES"

# Critical, если есть изменения в shared/ или config/balance.json
if grep -qE '^(shared/|config/balance\.json)' "$PR_FILES"; then
  TIER="critical"
# Critical, если затронуты нормативные артефакты пайплайна:
# - .claude/settings.json, hooks, skills, agents
# - .agents/*.md (AGENT_ROLES, PM_ROLE, PIPELINE, HOW_TO_USE, PIPELINE_ADR, план)
# Эта проверка идёт ДО light-ветки, потому что такие файлы имеют расширение
# .json/.md и иначе были бы ложно классифицированы как light. GPT-5.4 round 14
# CRITICAL: ранее .agents/*.md не учитывался, PR с только .agents/ изменениями
# уходил в Light и пропускал Tester gate + второй Critical pass.
elif grep -qE '^(\.claude/(settings\.json|hooks/|skills/|agents/)|\.agents/)' "$PR_FILES"; then
  TIER="critical"
# Light, если только .md/.json без логики (и не .agents/ — см. выше)
elif ! grep -qvE '\.(md|json)$' "$PR_FILES"; then
  TIER="light"
else
  TIER="standard"
fi
echo "Tier: $TIER"
```

**Правила выбора при смешанных изменениях (не понижай tier):**

- **Любое изменение в `shared/` или `config/balance.json`** → tier = `critical`, даже если 99% PR это документация. Игровая математика не может быть проревьюена поверхностно.
- **Только `.md` / `.json` без логики (`settings.json` hooks — не «без логики»!, `.agents/*.md` — нормативные!)** → tier = `light` разрешается.
- **Смешанные `client/` + `docs/`** → tier = `standard`.
- **Изменения в `.claude/settings.json` hook-логики, `.claude/hooks/*`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.agents/*.md`** → приравниваются к `critical` (нормативные артефакты пайплайна), даже если расширение `.json`/`.md`.
- Для PR помеченного как **Sprint Final** (завершение спринта перед merge в main) — к выбранному tier добавляется обязательный `/external-review` в Фазе 3.

> Если PR помечен как Sprint Final (метка `sprint-final` или явно в описании) — добавь обязательный `/external-review` в Фазе 3 поверх выбранного tier.

### Шаг 2.0.1: Tester gate для Critical (только Critical tier)

> Применяется **до** запуска reviewer'ов. Цель: найти непокрытые edge-cases ДО ревью кода.
>
> Промпт Tester-субагенту различается по **классу Critical-изменений**: игровая математика (`shared/`, `config/balance.json`) vs нормативные артефакты пайплайна (`.claude/settings.json`, `.claude/hooks/*`, `.claude/skills/*`, `.claude/agents/*`, `.agents/*`, шаблоны review-pass). Для каждого класса — свой промпт: тестер должен знать, что именно искать, иначе gate работает формально и пропускает реальные bypass/drift (этот gap нашёл GPT-5.4 external review round 12).

**Определи класс** по `gh pr diff --name-only`:

```bash
# Два независимых флага — корректно ловит mixed PR (shared/ + .claude/*).
# Ранее if/elif: первая ветка game-math выигрывала, pipeline-artifacts
# промпт не запускался даже для mixed — Tester gate работал формально
# (Tester CRIT #6 из round 13 deferred, затем GPT-5.4 round 14 critical).
HAS_GAME=$(grep -qE '^(shared/|config/balance\.json)' "$PR_FILES" && echo 1 || echo 0)
HAS_PIPE=$(grep -qE '^(\.claude/(settings\.json|hooks/|skills/|agents/)|\.agents/)' "$PR_FILES" && echo 1 || echo 0)

if [ "$HAS_GAME" = "1" ] && [ "$HAS_PIPE" = "1" ]; then
  CRITICAL_CLASS="mixed"
elif [ "$HAS_GAME" = "1" ]; then
  CRITICAL_CLASS="game-math"
elif [ "$HAS_PIPE" = "1" ]; then
  CRITICAL_CLASS="pipeline-artifacts"
else
  CRITICAL_CLASS="mixed"   # fallback для не классифицированных Critical PR
fi
```

**Промпт Tester-субагенту — game-math:**
```
Ты Tester. Прочитай .agents/AGENT_ROLES.md секция "4. Tester".
Задача: проверь PR #<PR_NUMBER>. Tier: Critical, класс: игровая математика.
Контекст: PR трогает shared/ или config/balance.json.
Найди:
- Edge cases из Verification Contract плана (docs/plans/<sprint>.md), не покрытые тестами
- Граничные значения из config/balance.json без покрытия
- Регрессии: сценарии, ранее работавшие, которые могут сломаться
Верни findings PM (НЕ публикуй в PR).
```

**Промпт Tester-субагенту — pipeline-artifacts:**
```
Ты Tester. Прочитай .agents/AGENT_ROLES.md секция "4. Tester".
Задача: проверь PR #<PR_NUMBER>. Tier: Critical, класс: нормативные артефакты пайплайна.
Контекст: PR трогает .claude/settings.json / .claude/hooks/* / .claude/skills/* /
.claude/agents/* / .agents/* / шаблоны review-pass. Это hard-gate инфраструктура,
и ошибки класса «bypass», «drift между продьюсером и консьюмером», «silent downgrade»
здесь критичны сильнее, чем в обычном коде.

Найди:
- Bypass hook'ов: можно ли обойти `check-merge-ready.py` через переменные
  (`--body "$VAR"`), через непрозрачные подстановки (`$(cat /file)`, `--body-file`),
  через альтернативные формы фразы (ready to merge без ##, bare merge-ready,
  ready_to_merge, локализованные варианты), через разные whitespace между
  токенами (`gh\tpr\tcomment`), через здоровые markdown-конструкции
  (blockquote с запрещённой фразой).
- Drift между скиллами: шаблон producer'а и regex consumer'а расходятся.
  Пример: шаблон публикации external-review печатает `**Commit:**`, а /finalize-pr
  ищет `Commit:` — такие mismatch'и скилл не ловит, но они ломают commit binding.
- Silent downgrade: проверь автодетект tier в /finalize-pr — что происходит,
  если PR не имеет ни label `sprint-final`, ни `Tier:` строки в body. Должно быть
  эскалация, а не тихая классификация как standard.
- Verification Contract: есть ли он в плане спринта? Полный (acceptance criteria,
  expected behaviors, edge cases, error cases, invariants, test list) или только
  `## Verification`? Последнее = автоматический quality fail.
- Непокрытые unit-тестами сценарии для hook'а (bypass-матрица) и для скиллов.

Верни findings PM с конкретными путями:строками и репродьюсерами (например,
точная команда `gh pr comment ... --body '...'`, которая проходит hook вместо блокировки).
НЕ публикуй в PR.
```

**Промпт Tester-субагенту — mixed:** объединить оба промпта (оба класса применимы).

Если Tester нашёл **непокрытые edge-cases** — PM делегирует Developer'у написать тесты / закрыть bypass / унифицировать шаблоны, затем повторный `/verify`. Только после этого — переход к шагу 2.1.

### Шаг 2.1: Запуск reviewer субагентов (параллельно)

> В этом skill reviewer субагенты не публикуют комментарии в PR самостоятельно.
> Они возвращают результаты PM.
> Владельцем внутреннего review-pass является PM, и именно PM публикует единый комментарий за проход.

**Архитектура:**
```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #<PR_NUMBER> — аспект АРХИТЕКТУРА.
Фокус: разделение слоёв (client/shared), чистота shared-пакета, паттерны сцен.
Результат: вердикт APPROVED / CHANGES_REQUESTED с обоснованием.
```

**Безопасность:**
```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #<PR_NUMBER> — аспект БЕЗОПАСНОСТЬ.
Фокус: XSS, утечка данных, OWASP top-10.
Результат: вердикт APPROVED / CHANGES_REQUESTED с обоснованием.
```

**Качество:**
```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #<PR_NUMBER> — аспект КАЧЕСТВО.
Фокус: покрытие тестами, edge-cases, производительность < 16мс/кадр.
Результат: вердикт APPROVED / CHANGES_REQUESTED с обоснованием.
```

**Гигиена кода:**
```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #<PR_NUMBER> — аспект ГИГИЕНА КОДА.
Фокус: мёртвый код, дублирование типов, захардкоженные константы, закомментированный код.
Результат: вердикт APPROVED / CHANGES_REQUESTED с обоснованием.
```

### Шаг 2.2: Публикация отчёта

> **Commit binding обязателен.** `/finalize-pr` (фаза 1, шаг 3) ищет последний internal review-pass с `Commit: <hash>` ИЛИ `"commit": "<hash>"` в HTML META. Без этих маркеров скилл считает review-pass отсутствующим и блокирует финализацию. Формат идентичен external-review для единообразия.

Перед публикацией зафиксируй HEAD commit:

```bash
HEAD_COMMIT=$(timeout 10 gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid')
# Copilot round 20: без null-guard пустой/null commit попадал в review-pass,
# и /finalize-pr не мог найти commit-binding. Валидируем формат SHA сразу.
if [[ -z "$HEAD_COMMIT" || "$HEAD_COMMIT" == "null" || ! "$HEAD_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Не удалось получить валидный HEAD_COMMIT для PR <PR_NUMBER>. Публикация review-pass остановлена." >&2
  exit 1
fi
```

Затем публикуй отчёт. **Используй quoted heredoc с high-entropy делимитером + плейсхолдер**, чтобы bash не делал подстановок внутри тела (резюме reviewer-субагентов может содержать `$VAR`, `$(...)`, backticks — без quoted heredoc их раскроет shell и текст исказится). Перед запуском команды сгенерируй fresh suffix (`openssl rand -hex 8`), замени `<RAND>` в обеих строках делимитера и проверь подготавливаемое тело: выбранный делимитер не должен встречаться как отдельная строка. Подставь `$HEAD_COMMIT` после, через bash parameter expansion:

```bash
# Copilot round 22: ITERATION должна быть задана явно.
# Определяем номер прохода: ищем последний iteration в PR comments, +1.
# Если нет — первый проход.
ITERATION=$(gh pr view <PR_NUMBER> --json comments \
  --jq '[.comments[].body | capture("\"iteration\":\\s*(?<n>[0-9]+)") | .n | tonumber] | max // 0 | . + 1')
if [[ -z "$ITERATION" || "$ITERATION" == "null" ]]; then
  ITERATION=1
fi

BODY=$(cat <<'GH_BODY_<RAND>'
## Внутреннее ревью (Claude) — review-pass

Commit: `__HEAD_COMMIT__`

<!-- {"reviewer": "claude-opus-4-6", "commit": "__HEAD_COMMIT__", "kind": "internal", "iteration": __ITERATION__, "tier": "__TIER__"} -->

### Findings (обязательная таблица для /finalize-pr фазы 2 triage)

> Если вердикт APPROVED без замечаний — оставь таблицу с единственной строкой `| — | — | нет замечаний | — | — | — |`. Пустая таблица недопустима: `/finalize-pr` отличает «нет findings» от «парсинг сломался».

| # | Severity | Заголовок | Файл:строка | Статус | Beads ID / Обоснование |
|---|----------|-----------|-------------|--------|------------------------|
| 1 | CRITICAL | ... | path:N | fix now | — |
| 2 | WARNING | ... | path:N | defer to Beads | bd-xyz-123 |
| 3 | INFO | ... | path:N | reject with rationale | <обоснование> |

### Архитектура
**Вердикт:** [APPROVED / CHANGES_REQUESTED]
[резюме]

### Безопасность
**Вердикт:** [APPROVED / CHANGES_REQUESTED]
[резюме]

### Качество
**Вердикт:** [APPROVED / CHANGES_REQUESTED]
[резюме, включая проверку Verification Contract]

### Гигиена кода
**Вердикт:** [APPROVED / CHANGES_REQUESTED]
[резюме]

— PM (Claude Opus 4.6)
GH_BODY_<RAND>
)
# Безопасная подстановка маркеров через bash parameter expansion.
# Тело отчёта остаётся буквальным (quoted heredoc), shell-расширений нет.
BODY="${BODY//__HEAD_COMMIT__/$HEAD_COMMIT}"
BODY="${BODY//__ITERATION__/$ITERATION}"    # номер прохода: 1, 2, 3...
BODY="${BODY//__TIER__/$TIER}"              # standard | critical | sprint-final | light
gh pr comment <PR_NUMBER> --body "$BODY"
```

### Шаг 2.2.1: Pre-Chat Gate

Перед любым сообщением оператору о результате внутреннего ревью проверь:

- PR идентифицирован корректно
- `gh pr comment` выполнился успешно
- Есть подтверждение публикации; ссылка на комментарий предпочтительна

Если хотя бы один пункт не выполнен, review-pass не завершён.

### Шаг 2.3: Исправление замечаний (если есть)

Если хотя бы один аспект `CHANGES_REQUESTED`:

1. Запусти developer субагента на исправления
2. `git push`
3. `gh pr comment` с отчётом об исправлениях
4. Запроси Copilot re-review:

```bash
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
gh api "repos/$REPO/pulls/<PR_NUMBER>/requested_reviewers" \
  --method POST -f 'reviewers[]=copilot-pull-request-reviewer[bot]' \
  && echo "Copilot: re-review requested" \
  || echo "Copilot: request failed — может потребоваться ручной запуск"
```

5. Повтори ревью

> ⛔ `git push` без `gh pr comment` = незавершённый цикл. Не останавливайся после push.
> Только `gh pr comment` — не `gh pr review` (агенты работают под аккаунтом оператора).
> ⛔ После повторного ревью снова действует тот же review-pass gate: сначала публикация, потом сообщение оператору.

### Шаг 2.4: Critical — второй проход (только Critical tier)

Для tier=Critical обязателен **второй проход** всех 4 аспектов после фиксов первого прохода. Цель — поймать то, что было пропущено или сломано в ходе исправлений.

Промпт каждому Reviewer-субагенту изменяется:
```
Ты Reviewer (второй проход). Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Контекст: PR #<PR_NUMBER>, Critical tier, фиксы первого прохода применены.
Фокус: то, что мог пропустить первый проход; регрессии от фиксов; сценарии,
не покрытые первым проходом.
Аспект: <АРХИТЕКТУРА | БЕЗОПАСНОСТЬ | КАЧЕСТВО | ГИГИЕНА КОДА>.
Верни findings PM (НЕ публикуй в PR).
```

PM публикует второй консолидированный отчёт (по аналогии с шагом 2.2). В JSON-метаданных `iteration: 2`.

Если второй проход дал `CHANGES_REQUESTED` — повторить шаг 2.3 → 2.4 до APPROVED.

> Если tier=Light, шаги 2.0.1, 2.4 пропускаются. Если tier=Standard — пропускается только 2.4.

## Фаза 3: Внешнее ревью (Sprint Final)

> **ОБЯЗАТЕЛЬНО перед merge в main.** PM запускает `/external-review` для кросс-модельного ревью через Codex CLI. Модели определяются автоматически по режиму авторизации (API key или ChatGPT login).

### Шаг 3.1: Запуск внешнего ревью

Вызови скилл:

```
/external-review <PR_NUMBER>
```

Скилл выполнит:

- Запуск внешних ревьюеров через Codex CLI (по всем 4 аспектам)
- Запрос Copilot re-review
- PM консолидирует вывод и публикует отчёт в PR через `gh pr comment` (ручной шаг в скилле)

> ⚠️ **Проверь режим работы.** `/external-review` автоматически выбирает режим по доступности Codex CLI. Режимы C (Codex недоступен → Claude adversarial degraded) и D (ручной emergency через Copilot Agent) **требуют явной метки в финальном отчёте** — см. таблицу в `external-review/SKILL.md` шаг 5.1. PM должен убедиться, что метка присутствует: «⚠️ Degraded mode» (C) или «⚠️ Manual emergency mode» (D). Без метки audit trail вводит в заблуждение — Sprint Final маркируется как cross-model review, хотя им не является.

### Шаг 3.2: Обработка результатов

Если вердикт `CHANGES_REQUESTED`:

1. Исправь CRITICAL и WARNING замечания через Developer-субагента
2. `git push`
3. Запроси Copilot re-review:

```bash
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
gh api "repos/$REPO/pulls/<PR_NUMBER>/requested_reviewers" \
  --method POST -f 'reviewers[]=copilot-pull-request-reviewer[bot]' \
  && echo "Copilot: re-review requested" \
  || echo "Copilot: request failed — может потребоваться ручной запуск"
```

4. Повтори `/external-review <PR_NUMBER>`

Если вердикт `APPROVED` — переходи к Фазе 3.5.

## Фаза 3.5: Triage замечаний (обязательно перед финализацией)

Все findings из внутреннего и внешнего ревью должны получить явный статус. Это инвариант 4 v3.3 и предусловие `/finalize-pr` фаза 2.

| Статус | Действие PM | Валидация |
|--------|-------------|-----------|
| **fix now** | Developer исправляет, повторный review-pass на новом commit | Повторный APPROVED для затронутого аспекта |
| **defer to Beads** | PM создаёт issue через `bd create`, фиксирует ID в PR | Обязателен Beads ID. Канонические правила валидации (приоритет `bd show <id>`, fallback regex, формат) — см. **`.claude/skills/finalize-pr/SKILL.md` фаза 2**. Не дублируй regex здесь, чтобы избежать drift |
| **reject with rationale** | PM публикует обоснование в PR | Обоснование не пустое |

Замечания без статуса = незавершённый цикл. `/finalize-pr` фаза 2 заблокирует финализацию.

Если `defer_ratio > 50%` — это сигнал defer-abuse. Скилл `/finalize-pr` выведет предупреждение оператору, но merge не блокирует (план v3.3 секция 1.4).

## Фаза 4: Финализация через `/finalize-pr`

> ⛔ **Не публикуй «готов к merge» вручную.** Hook `.claude/hooks/check-merge-ready.py` блокирует такие формулировки в `gh pr comment` вне `/finalize-pr`. Даже если все проверки зелёные — финализация идёт только через скилл.

Вызови скилл:

```
/finalize-pr <PR_NUMBER>               # для не-Sprint Final tier (Light/Standard/Critical)
/finalize-pr <PR_NUMBER> --pre-landing  # для Sprint Final PR — ПЕРВЫЙ вызов (до landing commit)
```

> ⚠️ **Для Sprint Final первый вызов ОБЯЗАТЕЛЬНО с `--pre-landing`** — иначе шаблон финального комментария выйдет без строки `⏳ Pre-merge landing commit впереди — жди второй /finalize-pr, не мерджи сейчас.`, и оператор может смержить PR до landing commit (регрессия к post-merge landing, VC-8 срыв). Флаг передаётся только для первого Sprint Final вызова; для второго (после landing commit) — без флага. Detection explicit, без runtime autodetect.

`/finalize-pr` сам проверит:
1. HEAD commit hash PR.
2. `/verify` зелёный на этом commit.
3. Internal review-pass привязан к этому commit.
4. Если tier = Sprint Final — external review есть на этом commit.
5. После CHANGES_REQUESTED был повторный review-pass на текущем commit.
6. (фаза 2) У каждого замечания есть triage-статус (fix now / defer с Beads ID / reject с обоснованием).
7. (фаза 2) Warning при `defer_ratio > 50%`.

Если все проверки пройдены — скилл опубликует финальный комментарий `## ✅ Готов к merge` через inline-токен `FINALIZE_PR_TOKEN`, который обходит hook только для этого одного вызова.

## Фаза 4.5: Pre-merge Landing (ОБЯЗАТЕЛЬНО для Sprint Final после первого `/finalize-pr --pre-landing APPROVED`)

> ⛔ **Применимость: только для Sprint Final PR** (PR с `Tier: Sprint Final` в body или меткой `sprint-final`). Для tier ≠ Sprint Final (Light/Standard/Critical) `/finalize-pr` вызывается **один раз без `--pre-landing`**, landing-фазы и второго вызова **нет** — оператор мержит сразу после первого `## ✅ Готов к merge`. См. `.agents/HOW_TO_USE.md` §4 и `.agents/PIPELINE.md` §3.
>
> ⛔ Landing artifacts (.memory-bank/activeContext.md update, plan archive, bd close, memory entry)
> **обязаны быть в ветке PR до merge** для Sprint Final. Отдельный `chore/landing-pr-N` PR
> запрещён с v3.4 — это убирает bureaucratic toil без safety value.

После успешной публикации первого `## ✅ Готов к merge` (с `⏳ landing впереди` warning, только Sprint Final) PM выполняет в **той же ветке**:

### Шаг 4.5.1: Обновление Memory Bank

- `.memory-bank/activeContext.md` — спринт помечен `COMPLETE <finalize_date>` (дата этого `/finalize-pr`).
- При необходимости — `systemPatterns.md` / `productContext.md`.

### Шаг 4.5.2: Архивация плана

```bash
git mv docs/plans/<sprint>.md docs/archive/
```

(если план был в `docs/plans/`).

### Шаг 4.5.3: Закрытие beads

```bash
bd close <sprint-tracking-id>    # с reason: "pre-merge landing in PR #<N> via commit <SHA>"
bd close <task-issue-id>         # с reason: "pre-merge landing in PR #<N> via commit <SHA>"; task, который инициировал спринт
```

### Шаг 4.5.4: Memory pattern

```bash
bd remember "Sprint N завершён <finalize_date>: <1-line summary + key decisions>"
```

Используй именно `завершён <finalize_date>`, **не** `<merge_date>` — см.
`PM_ROLE.md §2.5` рациональ.

### Шаг 4.5.5: Commit + push

```bash
git add .memory-bank/ docs/archive/
git commit -m "chore(landing): pre-merge artifacts — sprint-N"
git push
```

### Шаг 4.5.6: Doc-only review round

Copilot автоматически стартует — прочитай его комментарии. Tier обычно Light
(только .md). Если zero findings — достаточно PM delta self-review как единого
internal review-pass с `iteration: N+1, tier: light`.

#### Sprint Final tier — external review на landing HEAD обязателен

Если первый прогон PR был Sprint Final, **второй `/finalize-pr` тоже потребует
external review на landing commit** (hard gate `/finalize-pr` Шаг 4 — см.
`.claude/skills/finalize-pr/SKILL.md` Dual-invocation). Иначе finalize упадёт
с «СТОП: External review обязателен для Sprint Final на commit $HEAD_COMMIT».

Запусти `/external-review <PR_NUMBER>` повторно на landing commit. Допустимо:

- **Mode A primary** — если Codex CLI ChatGPT subscription доступна (см. `external-review/SKILL.md` Шаг 2).
- **Mode A-hybrid** — Reviewer A через Codex CLI subscription, Reviewer B fallback на Platform API (`openai-review.mjs`) при недоступности gpt-5.3-codex через subscription.
- **Mode A-legacy** — Codex CLI недоступен полностью; оба reviewer через `openai-review.mjs` Platform API.
- **Mode C / D** — с меткой `⚠️ Degraded mode` / `⚠️ Manual emergency mode`
  в теле ревью. Landing = doc-only delta (.memory-bank/activeContext.md + plan archive + memory
  entry), поэтому degradation обоснована объёмом изменений. PM явно фиксирует
  rationale degradation в теле external review-pass.

Для tier=Light/Standard/Critical (не Sprint Final) — external review опционален
на landing commit; достаточно internal self-review делта-ревью из шага выше.

### Шаг 4.5.7: Повторный /finalize-pr

```
/finalize-pr <PR_NUMBER>
```

Skill обнаружит новый HEAD (landing commit) — это штатный **dual-invocation
pattern**. Hard gate прогонит все проверки заново на новом SHA:

- `/verify` зелёный на landing commit
- internal review-pass на landing commit (от шага 4.5.6)
- external review-pass на landing commit — **обязателен для Sprint Final**
  (запускается в 4.5.6; Mode A primary / A-hybrid / A-legacy / C / D, метка
  Degraded — для C/D). Для прочих tier — N/A

Если второй `/finalize-pr` APPROVED → сообщи оператору что PR merge-ready,
**landing уже внутри, POST-merge шагов у PM нет**.

### Dogfood-замечание

Этот pattern (pre-merge landing — финальный комментарий и landing внутри PR
до merge, без POST-merge шагов у PM) введён в Sprint Pipeline v3.4.

## Фаза 5: Сообщение оператору

После публикации — сообщи оператору: «Опубликован финальный комментарий в PR #<N>. Решение о merge — за тобой.»

> См. `.claude/skills/finalize-pr/SKILL.md` для полной логики, шаблонов и emergency override `--force`.
