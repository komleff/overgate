---
name: external-review
description: Внешнее ревью PR через Codex CLI ChatGPT subscription (Sprint Pipeline v3.9 Mode A primary). Две полноразмерные модели последовательно — gpt-5.5 (reasoning, primary) + gpt-5.3-codex (code). Fallback модели — gpt-5.4. Fallback режимы — A-legacy (openai-review.mjs Platform API), C (Claude adversarial degraded) и D (manual emergency). Используй `/external-review <PR_NUMBER>`.
user-invocable: true
---

# External Review — кросс-модельное ревью через Codex CLI ChatGPT subscription

Автоматизация Sprint Final (Фаза 3 `sprint-pr-cycle`). Две полноразмерные модели разных архитектур проверяют PR по **всем 4 аспектам**, максимизируя adversarial diversity. Основной путь — **Codex CLI с ChatGPT subscription quota** (Sprint Pipeline v3.9, ADR 3.27); при его недоступности — **Mode A-legacy** (Node.js native через `openai-review.mjs` на Platform API) или degraded режимы C/D. Sprint Final не блокируется ни в одном режиме, но помечается честно.

> Источник подхода: [Adversarial Code Review для Claude Code](https://habr.com/ru/articles/1019588/)
>
> **Backend evolution:** v3.6 — `openai-review.mjs` Platform API primary; v3.9 — Codex CLI subscription primary, `openai-review.mjs` сохраняется как Mode A-legacy. Решение: `.agents/PIPELINE_ADR.md` ADR 3.27 (cost-driven: $0/вызов в пределах квоты vs $20-22/вызов на Platform API). Decision keep both reviewers подтверждён данными: 22.7% unique-to-Codex Critical/High findings (см. `<PROJECT_RESEARCH>` — свой анализ эффективности reviewer'ов / overlap-анализ). Анализ invocation policy уточняет: code-специализированный Reviewer B остаётся для Critical/Sprint Final/runtime/tooling PR, но не вызывается по умолчанию для Light/doc-only/landing проходов (`<PROJECT_RESEARCH>`).

## Контекст

Прочитай перед началом:

- `.agents/AGENT_ROLES.md` секция «3. Reviewer» — формат вердикта (4 аспекта).
- `.memory-bank/activeContext.md` — текущее состояние проекта.
- `.agents/CODEX_AUTH.md` §8 — ChatGPT subscription path setup и validated invocation pattern.
- `.agents/PIPELINE_ADR.md` ADR 3.27 — design rationale для Codex CLI subscription backend.
- `<PROJECT_RESEARCH>` (если есть) — свой анализ эффективности reviewer'ов: effectiveness stats и Reviewer B invocation policy.
- Архивный handoff-документ миграции backend (если есть) — описывает backend migration. Для деталей runtime allowlist Mode A-legacy и endpoint dispatch — см. `.claude/tools/openai-review.mjs` (`--help` + sources) и `.agents/CODEX_AUTH.md` §1-§7 (Platform API setup).

## Аргументы

- `PR_NUMBER` — номер PR для ревью (обязательный).
- `--legacy` — explicit override на Mode A-legacy (`openai-review.mjs` Platform API), bypass Mode A primary (Codex CLI subscription) даже если subscription доступна. **Use case:** self-modification PRs которые меняют `.claude/skills/*`, `.agents/*`, `.codex/`, или `AGENTS.md` — Mode A primary имеет known trust boundary gap для них (Beads U2-me5, P1; см. Шаг 3.1 KNOWN LIMITATION warning).
- `--manual` — explicit Mode D ручной fallback (per Шаг 2 mode table).

Argument parsing (выполняется первым в Шаге 1):

```bash
PR_NUMBER=""
FORCE_LEGACY=0
FORCE_MANUAL=0
for arg in "$@"; do
  case "$arg" in
    --legacy) FORCE_LEGACY=1 ;;
    --manual) FORCE_MANUAL=1 ;;
    [0-9]*) PR_NUMBER="$arg" ;;
    *) echo "ВНИМАНИЕ: неизвестный аргумент '$arg' игнорируется." >&2 ;;
  esac
done
if [ -z "$PR_NUMBER" ]; then
  echo "СТОП: PR_NUMBER обязателен. Usage: /external-review <PR_NUMBER> [--legacy|--manual]" >&2
  exit 1
fi
```

## Шаг 1: Пререквизиты

### 1.1 Проверка чистоты рабочего дерева

> Проверяется ПЕРЕД любыми операциями (git fetch, ref creation), чтобы избежать конфликтов и потери локальных изменений. После trust boundary fix (Шаг 7.6 Plan A) `gh pr checkout` больше не выполняется — pipeline остаётся в trusted base, но clean tree всё равно требуется для предсказуемого `git fetch` и операций с локальными refs.

```bash
if [ -n "$(git status --porcelain)" ]; then
  echo "СТОП: рабочее дерево не чистое. Закоммить или stash изменения."
  exit 1
fi
```

### 1.2 Получение PR-метаданных + fetch PR head как trusted ref (БЕЗ checkout)

> **Trust boundary** (Шаг 7.6 Plan A): tool НЕ запускается из ветки PR в Mode A-legacy. Раньше `gh pr checkout` переключал cwd в untrusted ветку, и `node openai-review.mjs` в ней мог быть подменён PR-автором с доступом к `$OPENAI_API_KEY`. Сейчас pipeline остаётся в trusted base/default branch, PR код только читается через diff с fetched ref.
>
> **В Mode A primary (Codex CLI subscription) trust boundary не критичен:** Codex CLI — глобальная установка (`@openai/codex` npm install -g), бинарник в `$AppData\Roaming\npm\codex.cmd` или `/usr/local/bin/codex`, **не из cwd**. PR-автор не может подменить codex binary через PR. Однако clean tree всё равно требуется для предсказуемого `git fetch` и `git checkout --detach` (если используется `--base` invocation).

```bash
BASE_BRANCH=$(gh pr view <PR_NUMBER> --json baseRefName --jq '.baseRefName')
STATE=$(gh pr view <PR_NUMBER> --json state --jq '.state')

if [ "$STATE" != "OPEN" ]; then echo "СТОП: PR не открыт"; exit 1; fi

# Fetch PR head как локальный ref (БЕЗ checkout — cwd остаётся в trusted base).
# refspec `pull/<PR>/head` — это GitHub-специфичный ref для PR head независимо от source repo.
PR_REF="u2-pr-<PR_NUMBER>"
git fetch origin "+pull/<PR_NUMBER>/head:refs/heads/${PR_REF}"
```

`BASE_BRANCH` используется далее в Mode A через `codex review --base "origin/$BASE_BRANCH"` (после detached checkout PR_REF) или `codex review --commit "$HEAD_COMMIT"` (single-commit path). В Mode A-legacy — `openai-review.mjs --base "$BASE_BRANCH" --head "$PR_REF"`. `PR_REF` для всех режимов одинаков.

### 1.3 Проверка что ветка запушена

```bash
if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  echo "СТОП: upstream не настроен. Выполни: git push -u origin $(git branch --show-current)"
  exit 1
fi

UNPUSHED=$(git log @{u}..HEAD --oneline)
if [ -n "$UNPUSHED" ]; then
  echo "СТОП: есть незапушенные коммиты. Выполни git push."
  exit 1
fi
```

### 1.4 Pre-flight: проверка backend availability, фиксация HEAD_COMMIT

> **Двухступенчатый check** (v3.9): сначала проверяем Codex CLI ChatGPT subscription (primary), затем — `openai-review.mjs` Platform API (Mode A-legacy fallback). Если оба недоступны → degraded path (Mode C/D).

```bash
# Фиксация HEAD_COMMIT сразу — используется далее в именах артефактов (Шаг 3.1)
# и в commit binding публикации (Шаг 5.3). Единое значение для всего прохода ревью.
HEAD_COMMIT=$(timeout 10 gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid')
if [[ -z "$HEAD_COMMIT" || "$HEAD_COMMIT" == "null" || ! "$HEAD_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "СТОП: не удалось получить валидный HEAD commit для PR <PR_NUMBER>" >&2
  exit 1
fi

# Trust boundary verify: убедиться что cwd = trusted base (default branch или
# другая базовая ветка), НЕ ветка PR. Защищает Mode A-legacy (openai-review.mjs из cwd).
# Mode A primary не страдает от cwd-substitution (codex CLI — глобальный binary), но
# clean trusted base всё равно нужен для idempotent git операций.
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BASE_BRANCH" ]; then
  echo "СТОП: external-review должен запускаться из trusted base ('$BASE_BRANCH'), текущая ветка '$CURRENT_BRANCH'." >&2
  echo "Сначала: git switch '$BASE_BRANCH' && git pull" >&2
  exit 1
fi

MODE_A_AVAILABLE=0
MODE_PRIMARY=""
MODE_A_LEGACY_AVAILABLE=0

# --- Operator override: --manual флаг force Mode D (manual emergency) ---
# Bypass всю automation chain, route напрямую в Mode D. Use case: incident response,
# forced risk-acceptance runs, или когда automated paths сломаны.
if [ "$FORCE_MANUAL" = "1" ]; then
  echo "Operator override --manual: bypass automation, force Mode D (manual emergency)."
  MODE_A_AVAILABLE=0
  MODE="D"
  # Skip всю availability detection — оператор вручную провёл review external tool'ом.
# --- Operator override: --legacy флаг bypass Mode A primary ---
# Для self-modification PRs которые меняют .claude/skills/*, .agents/*, .codex/,
# AGENTS.md — Mode A primary имеет fundamental trust boundary gap (Beads U2-me5).
# Operator-aware override force routing на Mode A-legacy (openai-review.mjs runs from
# trusted base, читает diff через --head refspec без cwd contents loading).
elif [ "$FORCE_LEGACY" = "1" ]; then
  echo "Operator override --legacy: bypass Mode A primary, force Mode A-legacy."
  # Skip Codex CLI check полностью, идём сразу к Mode A-legacy availability check ниже.
else
  # --- Step 1: Codex CLI ChatGPT subscription (primary) ---
  # Бинарник `codex` должен быть в PATH (npm install -g @openai/codex@latest, ≥0.128.0).
  # `codex login status` возвращает строку "Logged in using ChatGPT" если subscription active.
  # Profile [profiles.review] из ~/.codex/config.toml должен существовать (см. CODEX_AUTH.md §8.4).
  if command -v codex >/dev/null 2>&1; then
    CODEX_LOGIN_STATUS=$(timeout 10 codex login status 2>&1 || true)
    if echo "$CODEX_LOGIN_STATUS" | grep -q "Logged in using ChatGPT"; then
      # Profile validation (per external review iter 4+5 findings): убедиться что
      # [profiles.review] существует и загружается. Без этого Mode A primary будет
      # помечен available, но invocation в Шаге 3.1 упадёт с "profile not found" вместо
      # graceful fallback на Mode A-legacy.
      #
      # Iter 5 finding: `codex -p review --version` exit 0 даже когда profile missing
      # (--version не загружает profile). Только `exec` действительно loads profile config.
      # Используем `exec` only (no OR) для точной валидации.
      if timeout 10 codex -p review exec "echo profile-ok" >/dev/null 2>&1; then
        MODE_A_AVAILABLE=1
        MODE_PRIMARY="chatgpt"
        echo "Mode A primary: Codex CLI ChatGPT subscription + profile [review] доступны."
      else
        echo "ВНИМАНИЕ: Codex CLI logged in, но profile [profiles.review] не загружается."
        echo "Проверь ~/.codex/config.toml (см. CODEX_AUTH.md §8.4)."
        echo "Проверка fallback на Mode A-legacy (openai-review.mjs Platform API)..."
      fi
    else
      echo "ВНИМАНИЕ: Codex CLI установлен, но subscription path недоступен. Status: $CODEX_LOGIN_STATUS"
      echo "Проверка fallback на Mode A-legacy (openai-review.mjs Platform API)..."
    fi
  else
    echo "ВНИМАНИЕ: codex CLI не в PATH. Проверка Mode A-legacy fallback..."
  fi
fi

# --- Step 2: Mode A-legacy fallback (openai-review.mjs Platform API) ---
# Запускается только если Mode A primary недоступен. Установка openai SDK
# и валидация $OPENAI_API_KEY через --ping.
if [ "$MODE_A_AVAILABLE" = "0" ]; then
  if [ ! -d .claude/tools/node_modules ]; then
    # npm ci (не install): строго по lockfile, не пачкает рабочее дерево, воспроизводимо.
    # --ignore-scripts оставлен как defence-in-depth (даже trusted package может иметь
    # неожиданные lifecycle hooks).
    if ! (cd .claude/tools && npm ci --ignore-scripts); then
      echo "ВНИМАНИЕ: npm ci упал в .claude/tools/ — Mode A-legacy недоступен."
    fi
  fi

  # Ранняя проверка валидности $OPENAI_API_KEY (<2 сек, AC6 плана) — только если SDK установлен.
  if [ -d .claude/tools/node_modules ]; then
    if node .claude/tools/openai-review.mjs --ping; then
      MODE_A_AVAILABLE=1
      MODE_PRIMARY="legacy"
      MODE_A_LEGACY_AVAILABLE=1
      echo "Mode A-legacy: openai-review.mjs Platform API доступен (Codex CLI subscription unavailable, используем fallback)."
    else
      echo "ВНИМАНИЕ: Mode A-legacy недоступен (невалидный ключ / rate limit / network)."
      echo "Скрипт перейдёт в degraded-режим C. Детали ошибки — на stderr выше."
    fi
  fi
fi

# Если оба primary и legacy недоступны → MODE_A_AVAILABLE=0 → fallback C/D.
if [ "$MODE_A_AVAILABLE" = "0" ]; then
  echo "ВНИМАНИЕ: Mode A primary (Codex CLI subscription) и Mode A-legacy (openai-review.mjs) оба недоступны."
fi
```

Что детектируется на каждом шаге:

- **Codex CLI primary check fail:** бинарник не в PATH; `codex login status` не возвращает `Logged in using ChatGPT` (logged out, refresh token expired, OAuth broken); profile review не зарегистрирован в `~/.codex/config.toml` (косвенно через invocation в Шаге 3.1 — здесь не проверяем).
- **Mode A-legacy fail:** `npm ci` не отработал; `--ping` exit ≠ 0 (невалидный ключ, rate limit, network); подробности через stderr скрипта (см. `.claude/tools/README.md` таблицу exit codes).

## Шаг 2: Определение режима работы

Пять активных режимов: четыре initial-detected (A primary, A-legacy, C, D) выбираются на pre-flight в Шаге 1.4 + один runtime-derived (A-hybrid) emerges из частичного отказа Mode A primary в Шаге 3.1.2. Mode A primary — Codex CLI ChatGPT subscription. Mode A-legacy — `openai-review.mjs` Platform API как automatic fallback при недоступности subscription. Mode A-hybrid — Reviewer A через subscription + Reviewer B через Platform API при недоступности gpt-5.3-codex на subscription tier. Mode C/D — degraded paths.

### Режим A primary: Codex CLI ChatGPT subscription (основной путь, v3.9)

Если `MODE_A_AVAILABLE=1` И `MODE_PRIMARY="chatgpt"` из Шага 1.4:

- **Reviewer A (primary):** `codex -p review -c sandbox_mode="danger-full-access" review --commit "$HEAD_COMMIT"` — модель `gpt-5.5` берётся из `[profiles.review]` (см. `.agents/CODEX_AUTH.md` §8.4). Reasoning высокий, MCP_DOCKER подавлен через `mcp_servers = {}` table-replace в profile.
- **Reviewer B:** `codex -p review -c sandbox_mode="danger-full-access" -c model="gpt-5.3-codex" review --commit "$HEAD_COMMIT"` — `-c model="gpt-5.3-codex"` перебивает default из profile. **Если gpt-5.3-codex недоступна через subscription tier** (выясняется по exit code и stderr CLI; типичная ошибка `model X not available on this tier`) — Reviewer B автоматически переключается на Mode A-legacy через `openai-review.mjs --model gpt-5.3-codex` (см. Шаг 3.1.2 hybrid fallback).
- **Запуск sequential, НЕ parallel** — два concurrent codex вызова конфликтуют через shared `~/.codex/auth.json` lock. Sequential добавляет ~30-60s wall-clock, но stable.
- **Quota burn:** ChatGPT subscription quota — fixed monthly ($25 Plus / $100 Pro / $30/seat Business). $0/вызов в пределах квоты. Quota check — UI: `chatgpt.com Settings → Subscriptions → Usage` (нет CLI API).
- **На 429 quota exhausted:** ручной switch второго аккаунта через `.claude/tools/codex-account-switch.ps1` (`Use-CodexAccount work-business`), затем retry. Если оба исчерпаны → fallback на Mode A-legacy (см. Шаг 3.1.2).
- В отчёте: `— Reviewer (GPT-5.5 via Codex CLI subscription)` и `— Reviewer (GPT-5.3-Codex via Codex CLI subscription)`.

Codex CLI выводит markdown report на stdout. Exit codes: 0 OK, ≠0 runtime/auth/model error.

### Режим A-legacy: Node.js native через OpenAI SDK (auto-fallback v3.6 path)

Если `MODE_A_AVAILABLE=1` И `MODE_PRIMARY="legacy"` из Шага 1.4 (Codex CLI subscription недоступен, Platform API доступен):

- **Reviewer A:** `node .claude/tools/openai-review.mjs --model gpt-5.5 --base "$BASE_BRANCH" --head "$PR_REF"` — reasoning-специализация (`/v1/chat/completions` с `reasoning_effort: "high"`). Fallback: `--model gpt-5.4` если 5.5 недоступна.
- **Reviewer B:** `node .claude/tools/openai-review.mjs --model gpt-5.3-codex --base "$BASE_BRANCH" --head "$PR_REF"` — code-специализация (`/v1/responses` с `reasoning.effort: "high"`).
- Две полноразмерные модели разных архитектур = максимальная adversarial diversity. Платформа: OpenAI Platform API (pay-per-token, `$OPENAI_API_KEY`).
- В отчёте: `— Reviewer (GPT-5.5 Platform API)` и `— Reviewer (GPT-5.3-Codex Platform API)` + label `⚠️ Mode A-legacy fallback — primary v3.9 path (Codex CLI subscription) недоступен`.
- **⚠️ Стоимость (для адаптера):** Platform API — pay-per-token, ~$20-22 за полный вызов ревью (vs $0 в пределах ChatGPT subscription quota, Mode A primary). Это auto-fallback; для регулярной работы предпочтительна subscription (Codex CLI). См. README «Требования» и `.agents/CODEX_AUTH.md`.

Скрипт возвращает raw markdown на stdout (4 аспекта + вердикт `APPROVED | CHANGES_REQUESTED | ESCALATION`). Exit codes: 0 OK, 1 runtime/API, 2 валидация, 3 nothing to review — см. `.claude/tools/README.md` таблицу.

### Режим C: Все Mode A варианты недоступны (degraded, Claude adversarial)

Если `MODE_A_AVAILABLE=0` (Codex CLI subscription и Platform API оба недоступны), а оператор явно не выбрал ручной fallback:

- **Два прохода Claude-субагента** против одного и того же PR:
  - **Проход 1 (стандартный):** Reviewer в обычном режиме, промпт как в Standard tier.
  - **Проход 2 (adversarial):** Reviewer с промптом «Ты adversarial reviewer. Твоя задача — найти то, что первый проход пропустил. Ищи baseline-слабые места: необработанные edge-cases, скрытые дубликаты, некорректные инварианты».
- **⚠️ В отчёте обязательна метка:** «⚠️ Degraded mode с имитацией adversarial diversity. Не является cross-model review».
- Атрибуция: `— Reviewer (Claude Opus 4.7, standard)` и `— Reviewer (Claude Opus 4.7, adversarial)`.

### Режим D: Автоматические пути недоступны (manual emergency)

Если все Mode A варианты недоступны И оператор требует ручного fallback (например, gpt-5.4 через VS Code GitHub Copilot Agent):

- Оператор вручную прогоняет PR через внешний инструмент.
- PM собирает вывод в текстовом виде и публикует с меткой: «⚠️ Manual emergency mode. Adversarial diversity и воспроизводимость снижены».
- Атрибуция — по фактическому источнику (`— Reviewer (GPT-5.4 via Copilot Agent)`).

### Таблица выбора режима

| Режим | Условие запуска | Reviewer A | Reviewer B |
|-------|-----------------|------------|------------|
| **A** (primary, v3.9) | `codex login status` → `Logged in using ChatGPT` И profile `[profiles.review]` загружается | gpt-5.5 (Codex CLI subscription) | gpt-5.3-codex (Codex CLI subscription, может fallback на Platform API при tier limit) |
| **A-legacy** | Codex CLI недоступен И `openai-review.mjs --ping` → exit 0 | gpt-5.5 Platform API (или gpt-5.4 fallback) | gpt-5.3-codex Platform API |
| **C** | Все Mode A варианты недоступны, оператор не указал ручной fallback | Claude Opus 4.7 standard | Claude Opus 4.7 adversarial |
| **D** | Оператор явно указал ручной fallback (`--manual` или чат-команда) | По факту (Copilot Agent / др.) | — (single reviewer) |

> В любом режиме каждый проверяющий проходит все 4 аспекта. Различается источник ревью и атрибуция.

## Шаг 3: Запуск проверяющих

### 3.1 Режим A primary — через Codex CLI subscription (v3.9, основной путь)

> **Sequential, НЕ parallel.** Два concurrent `codex` вызова могут конфликтовать через shared `~/.codex/auth.json` (refresh token rotation, OAuth state). Sequential добавляет ~30-60s wall-clock, но даёт stable result.

> **Default invocation = `--base "origin/$BASE_BRANCH"` после `git checkout --detach $PR_REF`** (per external review iter 1 finding). Это покрывает PR полностью независимо от количества коммитов. `--commit "$HEAD_COMMIT"` — opt-in для smoke/single-commit cases (см. 3.1.x альтернатива ниже). Sprint Final review должен видеть весь diff PR'а, не только последний commit.

> ⚠️ **KNOWN LIMITATION (Beads U2-me5, P1):** Mode A primary имеет **fundamental trust boundary gap для self-modification PRs** — PRs которые меняют `.claude/skills/*`, `.agents/*`, `.codex/`, или `AGENTS.md`. Codex CLI loads these files из cwd regardless of git ref selection через `--base`/`--commit`, так что detached checkout в PR head exposes reviewer к PR-controlled agent configuration. PR-author мог бы подменить AGENTS.md в своём PR и biased/suppressed Codex review behavior.
>
> **Mitigation до fix U2-me5:** для self-modification PRs operator должен explicitly override на Mode A-legacy через `/external-review <PR_NUMBER> --legacy` (manual flag). Mode A-legacy через `openai-review.mjs` runs from trusted base, читает diff через `--head` refspec без cwd contents loading — trust boundary preserved.
>
> **Detection:** `gh pr diff <PR_NUMBER> --name-only | grep -qE '^(\.claude/|\.agents/|\.codex/|AGENTS\.md)'` → если true, рекомендуется Mode A-legacy. `<REF_PR>` (reference self-modification PR) сам менял pipeline-файлы — iter 1-3 strictly executed под partial trust compromise; mitigating factor что operator-authored PR не имеет malicious intent + reviewers continued surfacing real issues каждой iter (compromise не achieved practically).

```bash
# Создать каталог для артефактов (если ещё нет):
# .review-responses/ исключён из git (см. .gitignore) — raw outputs не коммитятся.
mkdir -p .review-responses

# Refresh base ref ПЕРЕД detached checkout — защита от stale `origin/$BASE_BRANCH`
# (per external review iter 2 finding). Если base branch продвинулся на GitHub
# с последнего fetch — без этого Mode A primary review against устаревший remote-tracking
# ref, possibly missing conflicts с current base или surfacing already-merged code.
# `+refs/heads/$BASE_BRANCH:refs/remotes/origin/$BASE_BRANCH` — explicit refspec
# (устойчиво к пользовательским remote.origin.fetch).
git fetch origin "+refs/heads/$BASE_BRANCH:refs/remotes/origin/$BASE_BRANCH"

# Detached checkout PR head — НЕ branch switch (trust boundary preserved для git refs).
# Codex CLI читает diff origin/$BASE_BRANCH..HEAD из git, поэтому detached HEAD = PR head
# даёт правильный diff scope. Codex CLI binary — глобальный (не из cwd), trust boundary
# preserved для primary path. Однако cwd contents = PR head state — это критично для
# любого fallback который запускает скрипты из cwd (см. Шаг 3.1.2 hybrid fallback —
# обязательный switch обратно в trusted base перед exec'ом openai-review.mjs).
git checkout --detach "$PR_REF"

# Reviewer A: gpt-5.5 (default из [profiles.review])
# Validated invocation pattern (CODEX_AUTH.md §8.3 + ADR 3.27):
# `-p review` активирует profile (model=gpt-5.5, reasoning=high, MCP_DOCKER suppressed).
# `-c sandbox_mode=...` обязателен — profile-level sandbox_mode игнорируется (Codex CLI 0.128.0 quirk).
# `review --base "origin/$BASE_BRANCH"` покрывает весь PR diff (multi-commit safe).
codex -p review -c sandbox_mode="danger-full-access" review --base "origin/$BASE_BRANCH" \
  > .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".md \
  2> .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".err
EXIT_A=$?

if [ "$EXIT_A" -ne 0 ]; then
  echo "ВНИМАНИЕ: Reviewer A (Codex CLI gpt-5.5) упал с exit $EXIT_A. stderr: .review-responses/mode-a-reviewer-a-$HEAD_COMMIT.err"
  # На 429: ручной operator action — `Use-CodexAccount work-business` (см. CODEX_AUTH.md §8.5).
  # Эту проверку реализуй inline: если grep -q '429\|quota' в .err → подсказка в stderr.
fi

# Reviewer B: gpt-5.3-codex через -c model override
# `-c model="gpt-5.3-codex"` перебивает default из profile.
# Если model недоступна на subscription tier → Codex CLI вернёт error на stderr и exit ≠ 0.
codex -p review -c sandbox_mode="danger-full-access" -c model="gpt-5.3-codex" review --base "origin/$BASE_BRANCH" \
  > .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".md \
  2> .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".err
EXIT_B=$?

if [ "$EXIT_B" -ne 0 ]; then
  echo "ВНИМАНИЕ: Reviewer B (Codex CLI gpt-5.3-codex) упал с exit $EXIT_B."
  echo "Возможная причина: gpt-5.3-codex не доступна на текущем ChatGPT subscription tier."
  echo "→ Hybrid fallback на Mode A-legacy для Reviewer B (см. Шаг 3.1.2)."
fi
```

**Альтернативный invocation для smoke/single-commit cases:**

```bash
# Single-commit review — для smoke-тестов или fixup-only PRs.
# НЕ используй для Sprint Final multi-commit PR — пропустит earlier commits.
codex -p review -c sandbox_mode="danger-full-access" review --commit "$HEAD_COMMIT" \
  > .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".md \
  2> .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".err
# (Reviewer B аналогично с -c model="gpt-5.3-codex" --commit "$HEAD_COMMIT")
```

Выбор между `--base + checkout --detach` (default) и `--commit` (alternative): для PR review (multi-commit или single-commit одинаково корректно) — `--base`. Для smoke-тестов одного коммита вне PR контекста — `--commit`. Если есть сомнение — используй `--base` (multi-commit safe).

### 3.1.2 Hybrid fallback: Reviewer B → Mode A-legacy (если codex CLI не даёт gpt-5.3-codex)

> **Размещён ДО cleanup (3.1.3) per external review iter 1 finding** — hybrid fallback использует `--head "$PR_REF"`, поэтому ref должен быть жив до завершения fallback.

Если Reviewer A через Codex CLI subscription отработал, но Reviewer B упал из-за недоступности `gpt-5.3-codex` на subscription tier — переключи только Reviewer B на Platform API:

```bash
# Условие активации hybrid fallback:
# 1. EXIT_A == 0 (Reviewer A через Codex subscription удался)
# 2. EXIT_B != 0 И stderr содержит "model" + "not available|not supported|tier"
# 3. MODE_A_LEGACY_AVAILABLE=1 ИЛИ openai-review.mjs --ping проходит
HYBRID_FALLBACK_NEEDED=0
HYBRID_FALLBACK_FAILED=0  # для partial-report маркировки если npm ci упал
if [ "$EXIT_A" = "0" ] && [ "$EXIT_B" -ne 0 ]; then
  if grep -qE 'model.*(not available|not supported|tier)' ".review-responses/mode-a-reviewer-b-$HEAD_COMMIT.err"; then
    HYBRID_FALLBACK_NEEDED=1
  fi
fi

if [ "$HYBRID_FALLBACK_NEEDED" = "1" ]; then
  echo "Hybrid fallback: Reviewer B → openai-review.mjs Platform API (gpt-5.3-codex недоступна на subscription tier)."

  # КРИТИЧНО (per external review iter 2 CRITICAL finding): SWITCH BACK В TRUSTED BASE
  # перед exec'ом openai-review.mjs. После Шага 3.1 cwd находится в detached HEAD = PR head,
  # т.е. в untrusted PR contents. Запуск `node .claude/tools/openai-review.mjs` оттуда
  # позволил бы PR-автору подменить скрипт и получить execution с $OPENAI_API_KEY.
  # Это rollback Trust boundary fix Шаг 7.6 Plan A. PR_REF остаётся жив и используется
  # через `--head "$PR_REF"` (refspec), а скрипт читается из trusted base checkout.
  git checkout "$BASE_BRANCH"

  # Ленивая установка — npm ci только когда нужен fallback (минимизируем первый-вход overhead).
  if [ ! -d .claude/tools/node_modules ]; then
    if ! (cd .claude/tools && npm ci --ignore-scripts); then
      echo "ОШИБКА: hybrid fallback недоступен — npm ci упал. Partial report публикуется с Reviewer B unavailable."
      HYBRID_FALLBACK_FAILED=1
    fi
  fi

  if [ "$HYBRID_FALLBACK_FAILED" = "0" ] && [ -d .claude/tools/node_modules ]; then
    # Запуск из trusted base (cwd = $BASE_BRANCH after switch выше). PR код читается
    # только через diff origin/$BASE_BRANCH..$PR_REF — refspec, не cwd contents.
    node .claude/tools/openai-review.mjs --model gpt-5.3-codex --base "$BASE_BRANCH" --head "$PR_REF" \
      > .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".md \
      2> .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".err
    EXIT_B=$?
    if [ "$EXIT_B" = "0" ]; then
      MODE="A-hybrid"  # Reviewer A на subscription, Reviewer B на Platform API
      echo "Hybrid fallback успешен."
    else
      echo "ВНИМАНИЕ: hybrid fallback exec упал — exit_B=$EXIT_B. Partial report с Reviewer B unavailable."
      HYBRID_FALLBACK_FAILED=1
    fi
  fi

  # Если hybrid fallback failed (npm ci broken OR exec failure) — partial report.
  # MODE остаётся "A-hybrid" (валиден для case statement в Шаге 5.3),
  # MODEL_B_NAME явно помечается как unavailable + warning label injected при публикации.
  if [ "$HYBRID_FALLBACK_FAILED" = "1" ]; then
    MODE="A-hybrid"
    MODEL_B_NAME="(unavailable — Mode A-legacy fallback failed)"
    # В Шаге 5.3 publish добавь warning label:
    # ⚠️ Reviewer B unavailable — partial report (Reviewer A через subscription отработал,
    # Reviewer B fallback на Platform API не удался: npm ci broken или exec failure)
  fi
fi
```

### 3.1.3 Cleanup PR_REF после ревью (важно для idempotency)

> **Размещён ПОСЛЕ hybrid fallback (3.1.2) per external review iter 1 finding** — fallback использует `--head "$PR_REF"`, ref должен быть удалён только когда все reviewer paths завершены.

После того как оба reviewer'а (включая возможный hybrid fallback) отработали — возврат в trusted base + удаление локального ref:

```bash
# Возврат в trusted base branch (был git checkout --detach в Шаге 3.1).
git checkout "$BASE_BRANCH"

# Удалить локальный ref u2-pr-<PR_NUMBER> — идемпотентно (флаг -f игнорирует отсутствие).
git update-ref -d "refs/heads/${PR_REF}" || true

# Альтернатива (если ref был как обычная ветка):
# git branch -D "$PR_REF" 2>/dev/null || true
```

Без cleanup при повторном `/external-review` для того же PR `git fetch` обновит ref на актуальный head — это не баг, но ref'ы накапливаются. Cleanup гигиеничен.

В отчёте (Шаг 5.3) Mode A-hybrid помечается как `⚠️ Reviewer B на Mode A-legacy fallback (gpt-5.3-codex недоступна через subscription)`.

### 3.1.3 Mode A-legacy (full Platform API path, v3.6 baseline)

Если из Шага 1.4 `MODE_PRIMARY="legacy"` (Codex CLI вообще недоступен) — оба reviewer'а через `openai-review.mjs`. Pattern идентичен v3.6:

```bash
# Trust boundary: --head "$PR_REF" указывает PR head как fetched ref,
# tool делает diff origin/${BASE_BRANCH}...${PR_REF} БЕЗ переключения cwd.
# Reviewer A: gpt-5.5 через /v1/chat/completions
node .claude/tools/openai-review.mjs --model gpt-5.5 --base "$BASE_BRANCH" --head "$PR_REF" \
  > .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".md \
  2> .review-responses/mode-a-reviewer-a-"$HEAD_COMMIT".err &
PID_A=$!

# Reviewer B: gpt-5.3-codex через /v1/responses
node .claude/tools/openai-review.mjs --model gpt-5.3-codex --base "$BASE_BRANCH" --head "$PR_REF" \
  > .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".md \
  2> .review-responses/mode-a-reviewer-b-"$HEAD_COMMIT".err &
PID_B=$!

wait "$PID_A"; EXIT_A=$?
wait "$PID_B"; EXIT_B=$?
```

В Mode A-legacy parallel допустим (`openai-review.mjs` instances independent). На Codex CLI primary — sequential обязателен (см. 3.1).

Exit 3 (`nothing to review`) — не ошибка, штатный сигнал пустого diff'а.

`openai-review.mjs` сам обеспечивает:
- Явный `git fetch origin +refs/heads/<base>:refs/remotes/origin/<base>` (устойчиво к пользовательским `remote.origin.fetch`).
- `git diff --no-color --no-ext-diff` (детерминированный diff независимо от git config пользователя).
- Runtime allowlist (три полноразмерные модели — gpt-5.5 primary, gpt-5.4 fallback, gpt-5.3-codex; отказ при любой другой).
- Диспатч endpoint по модели (chat.completions vs responses).
- Классификацию ошибок API (401/403 ключ, 429 rate limit, 400 oversized, 5xx сервер, network).
- Таймауты: 180 сек для review (reasoning high может отрабатывать долго); 2 сек для `--ping` **без retry** — строгий wall-clock бюджет AC6 плана для fail-fast на проблемах сети/ключа.

**Формат вывода — готовый markdown** в обоих режимах (A primary и A-legacy): system prompt (для openai-review.mjs) или Codex CLI native review задают жёсткий формат `## Вердикт: ...` + `### Архитектура: ...` + 3 других аспекта.

### 3.2 Режим C — Claude adversarial degraded

Запусти два Claude-субагента последовательно на том же PR.

**Проход 1 (стандартный):**
```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Режим: Standard, все 4 аспекта.
Задача: проверь PR #<PR_NUMBER>. Верни structured findings PM.
```

**Проход 2 (adversarial):**
```
Ты adversarial Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Контекст: первый проход этого PR уже прошёл. Твоя задача — найти то, что первый проход пропустил.
Фокус: baseline-слабые места, необработанные edge-cases, скрытые дубликаты, некорректные инварианты, маловероятные, но критичные ошибки.
Задача: проверь PR #<PR_NUMBER>. Верни structured findings PM.
```

Сохрани findings обоих проходов для collapsible блоков. **Обязательно** добавь в итоговый отчёт метку «⚠️ Degraded mode с имитацией adversarial diversity. Не является cross-model review».

### 3.3 Режим D — manual emergency

Оператор вручную прогоняет PR через внешний инструмент (VS Code GitHub Copilot Agent или аналог) и передаёт PM текстовый вывод. PM:

1. Принимает вывод как есть.
2. Маппит на 4 аспекта.
3. Публикует с меткой «⚠️ Manual emergency mode. Adversarial diversity и воспроизводимость снижены».
4. Атрибуция — по тому, кого оператор использовал.

## Шаг 3.5: Convergence detection и iteration cap (ADR 3.24)

> ⛔ **Stateless модели не сходятся естественно.** GPT-5.5/5.3-Codex каждую iter перечитывают весь diff и могут indefinitely surfacing replays + Low refinements. Без cap — infinite polish loop, нарушает цель пайплайна (облегчение труда оператора).

### 3.5.1 Convergence detection (preferred path)

PM объявляет APPROVED если выполнены **ВСЕ** условия:

- **3 итерации подряд** с 0 новых Critical/High findings (новый = не в triage предыдущих iter, не replay уже-deferred);
- только replays уже-deferred + Low refinements того же класса;
- **AND total external iter ≥ 5** (минимум для adversarial coverage);
- **AND каждое выявленное Low/Med/High finding имеет явный triage-статус** (fix now / defer to Beads с ID / reject with rationale). Сохраняет инвариант #5 — никаких «висящих» finding'ов без owner.

Минимум 5 iter критичен — обеспечивает что cross-model diversity отработала достаточно. Эмпирическая статистика зрелых проектов (big-heroes, bonk-race, surprise-arena, slime-arena) показывает 5-7 iter как минимум, 10-15 в среднем для нетривиальных PR. Не «спешим закрыть» на iter 2-3.

В v3.7 convergence/cap enforcement — **PM-side manual recipe**, не автоматический runtime gate: PM считает streak, scope, CAP и triage evidence в PR comment. Автоматизация этого правила — отдельное улучшение (`--prev-head` / diff-narrowing и fixtures), не текущее поведение скилла.

### 3.5.2 Soft iteration cap (safety valve, не hard ceiling)

Если convergence не detected — soft cap по scope:

| Scope diff (по `gh pr diff <N> --name-only`) | Soft cap |
|----------------------------------------------|----------|
| Doc-only (только `*.md`) | 7 |
| Mixed (doc + config без executable: `*.json`, `*.yaml`) | 12 |
| Executable / governance / security-sensitive infrastructure (`.claude/hooks/*.py`, `.claude/skills/*/SKILL.md`, `.claude/tools/*.mjs`, `.claude/settings.json` hooks/permissions/deny rules, `.claude/rules/*.md` claude code constraints, `.agents/*.md` doctrine/ADR/governance, server/client code) | 20 |

**Cap — soft.** При hit cap PM эскалирует к оператору binary вопросом (см. §3.5.3), НЕ автоматически APPROVE. Если оператор хочет ещё iter — продолжаем. Cap — только trigger для дискуссии оператору, не для финального решения.

Определение scope — автоматически. **Fail-closed:** при ошибке `gh pr diff` или пустом списке файлов — устанавливается максимальный cap (20), не минимальный. Иначе security-sensitive диффы получили бы заниженный cap из-за сетевой ошибки.

```bash
DIFF_FILES=$(gh pr diff <PR_NUMBER> --name-only 2>&1)
GH_EXIT=$?

if [ "$GH_EXIT" -ne 0 ] || [ -z "$DIFF_FILES" ]; then
  echo "ВНИМАНИЕ: gh pr diff упал (exit=$GH_EXIT) или вернул пустой список. Fail-closed: CAP=20."
  CAP=20
else
  # Executable / governance / security-sensitive scope:
  # - .py, .ts, .cs, .js, .jsx, .tsx, .mjs, .cjs, .mts, .sh, .ps1, .bat,
  #   .go, .rs, .java, .kt, .rb, .php, .swift, Dockerfile — реальный код
  # - .html, .css — клиентские артефакты с XSS / style-injection рисками (governance)
  # - .claude/hooks/, .claude/tools/ — runtime executable
  # - .claude/skills/*/SKILL.md — meta-instructions для subagents
  # - .claude/agents/*.md — native subagent instructions (governance)
  # - .claude/settings.json — hooks, deny rules, permissions (governance, не «config»)
  # - .claude/rules/*.md — claude code constraints (governance, не «doc-only»)
  # - .agents/*.md — pipeline doctrine, ADR, governance-документы
  # - .gitignore, .gitattributes — могут скрывать secrets/artifacts (governance)
  HAS_EXECUTABLE=$(echo "$DIFF_FILES" | grep -E '\.(py|ts|cs|js|jsx|tsx|mjs|cjs|mts|sh|ps1|bat|go|rs|java|kt|rb|php|swift|html|css|svg)$|(^|/)Dockerfile$|^\.claude/hooks/|^\.claude/skills/.*/SKILL\.md$|^\.claude/tools/|^\.claude/agents/.*\.md$|^\.claude/settings\.json$|^\.claude/rules/.*\.md$|^\.agents/.*\.md$|^\.gitignore$|^\.gitattributes$' | head -1)

  # Fail-closed: при unknown extension (не .md/.json/.yaml/etc) — escalate в executable.
  # Любой файл вне известного doc/config whitelist считается executable до доказательства обратного.
  # KNOWN_HARMLESS — узкий whitelist чисто документных/data-форматов БЕЗ executable risks.
  # .html и .css ИСКЛЮЧЕНЫ — они in HAS_EXECUTABLE из-за XSS/style-injection.
  # SVG исключён — может быть XSS-вектор (inline JS, foreignObject, use href).
  # SVG → HAS_EXECUTABLE через дополнительный extension match выше.
  KNOWN_HARMLESS=$(echo "$DIFF_FILES" | grep -E '\.(md|json|yaml|yml|toml|txt|csv|tsv|png|jpg|jpeg|gif|webp|ico)$|^\.gitignore$|^\.gitattributes$' | wc -l)
  TOTAL_FILES=$(echo "$DIFF_FILES" | wc -l)
  if [ "$KNOWN_HARMLESS" -lt "$TOTAL_FILES" ] && [ -z "$HAS_EXECUTABLE" ]; then
    echo "ВНИМАНИЕ: в diff есть файлы вне known-harmless whitelist (.md/.json/.yaml/etc). Fail-closed: escalate в executable scope (CAP=20)."
    HAS_EXECUTABLE="unknown_extension_fail_closed"
  fi

  # Config: остальные .json/.yaml/.yml/.toml — обычные конфиги без governance scope
  HAS_CONFIG=$(echo "$DIFF_FILES" | grep -vE '^\.claude/settings\.json$' | grep -E '\.(json|yaml|yml|toml)$' | head -1)
  # DOC_ONLY: только product/spec/gdd .md, без governance .md (последние уже в HAS_EXECUTABLE)
  DOC_ONLY=$(echo "$DIFF_FILES" | grep -vE '\.md$' | head -1)

  if [ -n "$HAS_EXECUTABLE" ]; then
    CAP=20
  elif [ -n "$HAS_CONFIG" ]; then
    CAP=12
  elif [ -z "$DOC_ONLY" ]; then
    CAP=7
  else
    CAP=12  # mixed default
  fi
fi
echo "External review iteration cap для scope: $CAP"
```

### 3.5.3 Binary escalation при hit cap (без оценки findings)

Когда iter == cap и convergence ещё не detected — PM публикует **бинарный вопрос** в PR comment, **не** проси оператора оценить findings (нарушает Zero Trust to Human Tech Skills):

```markdown
## ⏸ External review hit iteration cap (iter <N>/<CAP>)

Cross-model adversarial coverage достигнута. Оставшиеся findings:
- <X> новых Med refinements (детали в collapsible ниже)
- <Y> replays уже-deferred (см. <BEADS_ID>)
- 0 новых Critical/High

PM-рекомендация: **(a) APPROVE с deferred bundle**.

**Operator decision:**
- (a) Approve — finalize PR с deferred bundle <BEADS_ID> (рекомендация)
- (b) Continue iter <N+1> — ожидаемо ещё refinements того же класса, не блокеры

Жду явный (a) или (b) в PR comment или чате.
```

Оператор выбирает «принять текущее качество» vs «полировать дальше», **без необходимости evaluating findings** — это требование Zero Trust директивы.

### 3.5.4 Когда cap не применим

- **Tier ≠ Sprint Final.** Cap для external review только; internal review цикл не имеет cap (Critical-tier требует 2 iter, остальные — 1).
- **Operator override.** Оператор может явно потребовать продолжение iter ≥ cap+1 (например при подозрении на missed Critical в новом коде после cap'а).
- **Regression detected.** Если iter N+1 нашёл NEW Critical/High который раньше не surfac'ился — cap reset, fix-cycle продолжается до полной 3-iter convergence per §3.5.1 (без снижения до 2-iter — иначе post-regression streak слабее initial).

**Источник:** ADR 3.24 + U2 PR #186 retrospective.

## Шаг 4: Copilot Re-Review

Запроси re-review от GitHub Copilot (auto-reviewer):

```bash
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
gh api "repos/$REPO/pulls/<PR_NUMBER>/requested_reviewers" \
  --method POST \
  -f 'reviewers[]=copilot-pull-request-reviewer[bot]' \
  && echo "Copilot: re-review requested" \
  || echo "Copilot: request failed — может потребоваться ручной запуск"
```

## Шаг 5: Консолидация и публикация

### 5.1 Имена моделей (атрибуция)

Подставь реальные имена из шага 2 — не захардкоженные:

| Режим | MODEL_A_NAME | MODEL_B_NAME | Метка |
| --- | --- | --- | --- |
| **A** (primary, v3.9) | `GPT-5.5 via Codex CLI subscription` | `GPT-5.3-Codex via Codex CLI subscription` | — |
| **A-hybrid** | `GPT-5.5 via Codex CLI subscription` | `GPT-5.3-Codex via Platform API (openai-review.mjs)` | `⚠️ Reviewer B на Mode A-legacy fallback — gpt-5.3-codex недоступна через subscription` |
| **A-legacy** (v3.6 baseline) | `GPT-5.5 via Platform API (openai-review.mjs)` (или `GPT-5.4` если 5.5 недоступна) | `GPT-5.3-Codex via Platform API (openai-review.mjs)` | `⚠️ Mode A-legacy fallback — primary v3.9 path (Codex CLI subscription) недоступен` |
| **C** | `Claude Opus 4.7 (standard)` | `Claude Opus 4.7 (adversarial)` | `⚠️ Degraded mode с имитацией adversarial diversity. Не является cross-model review` |
| **D** | По факту (например, `GPT-5.4 via Copilot Agent`) | — (single reviewer) | `⚠️ Manual emergency mode. Adversarial diversity и воспроизводимость снижены` |

### 5.2 Защита findings — raw output в collapsible

> **Инвариант 6 (PM не искажает findings).** PM имеет право структурировать по 4 аспектам и убирать дубликаты, но **не** перефразировать или смягчать формулировки. Чтобы оператор мог проверить, raw-вывод каждого проверяющего публикуется целиком в `<details>` блоке отдельно от консолидированного отчёта.

### 5.3 Шаблон комментария

> ⚠️ **Commit binding — без `**` и с META JSON.** `/finalize-pr` ищет маркер через regex `Commit:\s*\`?<hash>` ИЛИ JSON `"commit": "<hash>"`. Шаблон `**Commit:**` (bold markdown) **не** матчится (между `Commit:` и хэшем идёт `**`, не whitespace) — это drift, найденный внешним ревью (round 12). Используй простой `Commit: <hash>` и добавь HTML META с JSON — дублирование на случай, если кто-то изменит markdown-форматирование.

`HEAD_COMMIT` уже зафиксирован в шаге 1.4 — повторно не вычисляем.

Публикация отчёта (quoted heredoc с high-entropy делимитером + bash parameter expansion, чтобы body-содержимое не проходило shell-расширения). Перед запуском команды сгенерируй fresh suffix (`openssl rand -hex 8`), замени `<RAND>` в обеих строках делимитера и проверь подготавливаемое тело: выбранный делимитер не должен встречаться как отдельная строка.

```bash
BODY=$(cat <<'GH_BODY_<RAND>'
## Внешнее ревью (Sprint Final) — Режим: __MODE__

Commit: `__HEAD_COMMIT__`

<!-- {"reviewer": "__MODEL_A_NAME__ + __MODEL_B_NAME__", "reviewer_a": "__MODEL_A_NAME__", "reviewer_b": "__MODEL_B_NAME__", "commit": "__HEAD_COMMIT__", "kind": "external", "mode": "__MODE__", "iteration": __ITERATION__} -->

<!--
Для режима A primary не добавляй warning-метки — оставь этот блок как есть (в комментарии).
Для режима A-hybrid: вынеси только строку `⚠️ Reviewer B на Mode A-legacy fallback ...`.
Для режима A-legacy: вынеси только строку `⚠️ Mode A-legacy fallback — primary v3.9 path ...`.
Для режима C: вынеси только строку `⚠️ Degraded mode ...`.
Для режима D: вынеси только строку `⚠️ Manual emergency mode ...`.
Не добавляй несколько строк одновременно. Дефолт — безопасный (нет меток).
⚠️ Reviewer B на Mode A-legacy fallback — <описание из таблицы 5.1>
⚠️ Mode A-legacy fallback — <описание из таблицы 5.1>
⚠️ Degraded mode — <описание из таблицы 5.1>
⚠️ Manual emergency mode — <описание из таблицы 5.1>
-->

### Findings (обязательная таблица для /finalize-pr фазы 2 triage)

> Если вердикт APPROVED без замечаний — оставь таблицу с единственной строкой `| — | — | нет замечаний | — | — | — |`. Пустая таблица недопустима: `/finalize-pr` отличает «нет findings» от «парсинг сломался».

| # | Severity | Заголовок | Файл:строка | Статус | Beads ID / Обоснование |
|---|----------|-----------|-------------|--------|------------------------|
| 1 | CRITICAL | ... | path:N | fix now | — |
| 2 | WARNING | ... | path:N | defer to Beads | bd-xyz-123 |
| 3 | INFO | ... | path:N | reject with rationale | <обоснование> |

### Консолидация (PM)

#### Reviewer A: __MODEL_A_NAME__

##### Архитектура: [OK / ISSUE]
[обоснование — дословно из findings, не перефразировать]

##### Безопасность: [OK / ISSUE]
[обоснование]

##### Качество: [OK / ISSUE]
[обоснование]

##### Гигиена кода: [OK / ISSUE]
[обоснование]

**Вердикт:** [APPROVED / CHANGES_REQUESTED / ESCALATION]
— Reviewer (__MODEL_A_NAME__)

---

> Секция Reviewer B публикуется в режимах A, A-hybrid, A-legacy, C. В D — опускается.

#### Reviewer B: __MODEL_B_NAME__

##### Архитектура: [OK / ISSUE]
[обоснование]

##### Безопасность: [OK / ISSUE]
[обоснование]

##### Качество: [OK / ISSUE]
[обоснование]

##### Гигиена кода: [OK / ISSUE]
[обоснование]

**Вердикт:** [APPROVED / CHANGES_REQUESTED / ESCALATION]
— Reviewer (__MODEL_B_NAME__)

---

### Raw output (для аудита оператором)

<details>
<summary>Reviewer A: __MODEL_A_NAME__ — raw</summary>

<pre><code>
<вставить raw-вывод Reviewer A целиком, без редактуры>
</code></pre>

</details>

<details>
<summary>Reviewer B: __MODEL_B_NAME__ — raw</summary>

<pre><code>
<вставить raw-вывод Reviewer B целиком, без редактуры>
</code></pre>

</details>

---

### Copilot
[re-review requested / auto-triggered / unavailable]

### Итоговый вердикт: [APPROVED / CHANGES_REQUESTED / ESCALATION]
CRITICAL: N, WARNING: N

— PM (Claude Opus 4.7), по результатам внешнего ревью
GH_BODY_<RAND>
)
# Вычисление обязательных полей публикации.
# MODE из шага 2 (A / A-hybrid / A-legacy / C / D); MODEL_A_NAME и MODEL_B_NAME — из таблицы 5.1.
# ITERATION — порядковый номер прохода внешнего ревью.
if [ -z "${MODE:-}" ]; then
  echo "MODE не задан. Установи переменную MODE (A / A-hybrid / A-legacy / C / D)." >&2
  exit 1
fi
case "$MODE" in
  A|A-hybrid|A-legacy|C|D) ;;
  *)
    echo "MODE='$MODE' invalid. Допустимые значения: A / A-hybrid / A-legacy / C / D." >&2
    exit 1
    ;;
esac
if [ -z "${MODEL_A_NAME:-}" ]; then
  echo "MODEL_A_NAME не задан. См. таблицу 5.1." >&2
  exit 1
fi
if [ -z "${MODEL_B_NAME:-}" ]; then
  # В режиме D Reviewer B отсутствует — допустимо "—".
  # В режимах A / A-hybrid / A-legacy / C Reviewer B обязателен — молчаливый дефолт маскирует ошибку конфигурации.
  if [ "$MODE" = "D" ]; then
    MODEL_B_NAME="—"
  else
    echo "MODEL_B_NAME не задан для режима $MODE, где Reviewer B обязателен. См. таблицу 5.1." >&2
    exit 1
  fi
fi
ITERATION="${ITERATION:-1}"

BODY="${BODY//__HEAD_COMMIT__/$HEAD_COMMIT}"
BODY="${BODY//__MODEL_A_NAME__/$MODEL_A_NAME}"
BODY="${BODY//__MODEL_B_NAME__/$MODEL_B_NAME}"
BODY="${BODY//__MODE__/$MODE}"
BODY="${BODY//__ITERATION__/$ITERATION}"
gh pr comment <PR_NUMBER> --body "$BODY"
```

> ⚠️ Raw output публикуется **без редактуры** содержимого, но **с HTML-escaping** перед вставкой в `<pre><code>`: заменить `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`. Без этого attacker-controlled diff может вернуть модели строку `</code></pre>` и сломать структуру комментария (закрывает Security ISSUE Reviewer A на 8e7dce6).
>
> Пример экранирования (bash):
> ```bash
> RAW_A_ESC=$(printf '%s' "$RAW_A" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
> # далее используй $RAW_A_ESC внутри <pre><code>...</code></pre> вместо $RAW_A
> ```
>
> Если raw слишком длинный — собрать как artifact и приложить ссылкой, но **не** сокращать пересказом.

## Шаг 6: Pre-Chat Gate

> Инвариант: review-pass НЕ завершён, пока отчёт не опубликован в PR.

Перед любым сообщением оператору проверь:

1. `gh pr comment` выполнился успешно.
2. Ссылка на комментарий зафиксирована (если доступна).
3. Только после этого сообщай оператору результат.

> ⛔ Чат-резюме без PR comment не завершает review-pass.

## Шаг 7: Обработка ошибок

### 7.1 Mode A primary (Codex CLI subscription) errors

| Ситуация | Признак | Действие |
| --- | --- | --- |
| `429` quota exhausted | stderr содержит `429` или `quota` | Manual swap аккаунта: `Use-CodexAccount work-business` (см. CODEX_AUTH.md §8.5). Retry. Если оба исчерпаны — fallback на Mode A-legacy через перезапуск skill (auto-detected в Шаге 1.4 при перезапуске) |
| `oauth token exchange failed` | stderr содержит `oauth` | Refresh token истёк. Re-login: `codex logout && codex login`, затем restore из backup при необходимости. Retry |
| `model X not available on this tier` (Reviewer B) | EXIT_B ≠ 0, stderr содержит `model` + `not available\|tier` | Auto hybrid fallback (Шаг 3.1.2) — Reviewer B через openai-review.mjs Platform API. Mode помечается `A-hybrid` |
| Profile `[profiles.review]` не найден | stderr содержит `profile` + `not found` | Operator должен добавить profile в `~/.codex/config.toml` (CODEX_AUTH.md §8.4). Skill exit 1 — невозможно continue без profile |
| Empty output / pipe error | Empty stdout file | Retry × 1; если снова пусто — переход в Mode A-legacy или публикация частичного отчёта с меткой |

### 7.2 Mode A-legacy (openai-review.mjs Platform API) errors

| Ситуация | Действие |
| --- | --- |
| `openai-review.mjs` exit 1 (локальная или API-ошибка) | Retry × 1; если повторно падает — переход в Mode C или D. Классификация ошибки — в stderr скрипта |
| `openai-review.mjs` exit 2 (валидация) | Исправить аргументы/модель. См. `--help` |
| `openai-review.mjs` exit 3 (nothing to review) | Нормальный сигнал — `HEAD == origin/<base>`. Ревью не запускается |

### 7.3 Общие правила для всех режимов

| Ситуация | Действие |
| --- | --- |
| Пустой вывод от модели | Retry × 1; если снова пусто — переход в Mode A-legacy / Mode C/D или публикация частичного отчёта |
| Оба проверяющих упали | Эскалация оператору, публикация частичного отчёта с меткой |
| Один проверяющий упал | Публикация отчёта с пометкой об упавшем проверяющем |
| Rate limit на всех повторах | Пометить как unavailable, переход вниз по chain (A → A-hybrid → A-legacy → C → D) |

> Никогда не пропускай ошибку молча. Частичный отчёт лучше, чем отсутствие отчёта.

## Шаг 8: Итеративные исправления

Если итоговый вердикт `CHANGES_REQUESTED`:

1. PM передаёт CRITICAL и WARNING findings Developer-субагенту.
2. Developer исправляет → `git push`.
3. PM запрашивает Copilot re-review (шаг 4).
4. PM повторно запускает `/external-review <PR_NUMBER>` на новом HEAD.
5. Каждый повторный запуск создаёт **новый** комментарий (не редактирует старый) — для audit trail.
