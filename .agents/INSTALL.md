---
title: "OverGate pipeline installer — onboarding for new projects"
status: active
version: "1.0"
date: 2026-05-04
source: "github.com/komleff/overgate/.agents/INSTALL.md"
tags: [pipeline, install, onboarding, bootstrap, dogfood]
related:
  - .agents/PIPELINE.md
  - .agents/PM_ROLE.md
  - .agents/AGENT_ROLES.md
  - .agents/HOW_TO_USE.md
  - .agents/PIPELINE_ADR.md
---

# OverGate pipeline — установка в новый проект

**Цель:** перенести двухслойный AI-пайплайн (`.agents/` доктрина + `.claude/` исполнение) из reference-репозитория в новый проект и довести его до рабочего состояния через первый Bootstrap PR.

**Аудитория:** оператор (человек, который не читает код) + ИИ-агент Claude, который выполнит установку.

**Reference baseline:** [Universe Unlimited (U2), PR #185](https://github.com/komleff/u2/pull/185) — первая успешная dogfood-миграция (21 коммит, 7 итераций cross-model review через GPT-5.4 на iter 1 и GPT-5.5 на iters 2-7, ~10 deferred Beads issues, FINAL APPROVED через `/finalize-pr`).

---

## A. Для оператора (короткая инструкция)

> Полная версия — секция B ниже (читает ИИ-агент). Эта секция объясняет, что делать **тебе** во время установки.

### A.1 Что нужно перед стартом

- Терминал или VS Code с Claude Code (Opus 4.7+)
- Открыта папка нового проекта
- Доступ к GitHub-репо нового проекта (для PR)
- **Reference-репозиторий** установлен локально (откуда копируем) — например `~/GitHub/u2/`; reference должен уже содержать `.agents/INSTALL.md` и `.claude/settings.json`
- **Сильно рекомендуется (любой из путей):** (a) **ChatGPT subscription** (Plus/Pro/Business) + Codex CLI logged in (`codex login` → "Logged in using ChatGPT") для Mode A primary (v3.9, ADR 3.27); ИЛИ (b) `OPENAI_API_KEY` для Mode A-legacy (v3.6 baseline через `openai-review.mjs` Platform API). Без обоих путей Bootstrap PR (executable infrastructure) не сможет пройти Sprint Final review-gate стандартным путём. Альтернатива — Mode D (ручное Copilot review) через явный operator risk acceptance, фиксируется в PR. См. §B.8 + §D.3 + ADR 3.20 + ADR 3.27.

### A.2 Промпт активации (копируй целиком)

```
Ты — установщик OverGate-пайплайна. Прочитай .agents/INSTALL.md секцию B
(полную инструкцию для AI-агента) в reference-репозитории
[путь к reference, например ~/GitHub/u2/.agents/INSTALL.md].

Контекст текущего проекта:
- Имя проекта: [например, my-new-game]
- GitHub-репо: [https://github.com/user/repo]
- Стек: [например, Node.js + React, или .NET + Unity]
- Reference-репозиторий: [например, ~/GitHub/u2/]
- Префикс Beads: [например, mng-* для my-new-game]

Действуй автономно по шагам a-j. Останавливайся только на:
1. Шаг f (Bootstrap PR) — мне нужно подтвердить структуру PR
2. Шаг j (финальный merge) — мерджу я

После каждого шага кратко отчитывайся, что сделал. На спорных решениях
(adapt vs copy-as-is) — выбирай consistency с reference и продолжай.
```

### A.3 Что ты контролируешь

> **Два типа контрольных точек:**
> - **Report-only** (после шагов c, d, e): AI-агент кратко отчитывается что сделал, ты читаешь, но **не блокируешь** — продолжай работу. Соответствует §A.2 «После каждого шага кратко отчитывайся».
> - **Blocking confirmation** (шаги f и j): AI-агент **останавливается** и ждёт твоего ответа. Соответствует §A.2 «Останавливайся только на: 1. Шаг f, 2. Шаг j».

| Точка | Тип | Действие | Что смотреть |
|-------|-----|----------|--------------|
| После шага c (копирование) | Report-only | Проверь diff `git status` | Файлы скопированы, без неожиданных удалений |
| После шага d (адаптация) | Report-only | Прочитай предложенные правки имени проекта/префикса | Подмена везде однозначна |
| После шага e (валидация) | Report-only | Подтверди что `bd doctor` зелёный, `/verify` либо есть либо N/A | Нет ошибок Beads |
| Шаг f (Bootstrap PR) | **Blocking** | Подтверди структуру PR (один большой / серия мелких) | По умолчанию: один большой PR |
| Шаги g-i (review-cycle) | Report-only | НЕ вмешивайся, кроме случаев явного блокера | Доверяй вердиктам — в этом смысл пайплайна |
| Шаг j (merge) | **Blocking** | **Только ты** мержишь после `## ✅ Готов к merge` без warning | См. `HOW_TO_USE.md §4` про dual-invocation |

### A.4 Когда установка завершена

Полные критерии — секция D. Кратко: после твоего merge Bootstrap PR в default branch, ИИ-агент должен подтвердить:
- `.agents/` и `.claude/` присутствуют в default branch
- `bd doctor` без ошибок
- Memory Bank инициализирован
- Один dogfood-цикл (этот самый PR) пройден до merge

После этого → используй `HOW_TO_USE.md` для обычной работы со спринтами.

---

## B. Для AI-агента (полная инструкция)

> Если ты ИИ-агент, выполняющий установку — читай эту секцию полностью **до** первого действия. Все шаги обязательны и идут строго по порядку.

### B.0 Mindset

Ты выполняешь **самоустанавливающийся пайплайн**: копируешь сам себя из reference-репо, потом проходишь свой же первый цикл review/finalize на самом себе. Это **chicken-and-egg** ситуация — есть один разовый ручной gate (шаг f confirm + шаг j merge оператором), всё остальное автономно.

**Reference baseline:** U2 PR #185 (21 коммит, 7 итераций). Не воспроизводи 7 итераций намеренно — это норма для bootstrap, а не цель. Цель — `## ✅ Готов к merge` без warning.

### B.1 Шаг a — Идентифицировать source и target

```bash
# Reference (откуда копируем)
REFERENCE_REPO="${REFERENCE_REPO:-/path/to/u2}"   # передаёт оператор

# Sanity-check: $REFERENCE_REPO должен указывать на валидный pipeline reference
if [[ ! -f "$REFERENCE_REPO/.agents/INSTALL.md" ]] || [[ ! -f "$REFERENCE_REPO/.claude/settings.json" ]]; then
  echo "СТОП: \$REFERENCE_REPO=$REFERENCE_REPO не похож на валидный pipeline reference"
  echo "(нужны .agents/INSTALL.md и .claude/settings.json). Проверь путь."
  exit 1
fi

ls "$REFERENCE_REPO/.agents/"                      # должно быть: AGENTIC_PIPELINE.md, AGENT_ROLES.md, ..., INSTALL.md (10 файлов)
ls "$REFERENCE_REPO/.claude/"                      # должно быть: settings.json, agents/, hooks/, skills/, rules/, tools/

# Target (текущая директория)
pwd                                                # должно быть == корень нового проекта
git status                                         # ветка main или master, без uncommitted критичных
DEFAULT_BRANCH=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
echo "Default branch: $DEFAULT_BRANCH"

# Target sanity-check: предотвращает silent overwrite существующего пайплайна.
# Проверяем целиком .claude/ и .agents/ — не только settings.json. Если есть
# .claude/agents/, .claude/hooks/, .claude/skills/, .claude/rules/ или
# .claude/tools/ — там уже есть существующая Claude-инфра, копирование
# может молча перезаписать или смешать. Любое существующее присутствие
# Claude-структуры → СТОП, эскалация к оператору.
if [[ -d .agents ]] || [[ -d .claude ]]; then
  echo "СТОП: target-проект уже содержит .agents/ или .claude/."
  ls -la .agents/ .claude/ 2>/dev/null
  echo "Существующая Claude-инфра. Возможные действия:"
  echo "  1. Если она от другого инсталлятора — backup и удалить вручную"
  echo "  2. Если своя кастомная — оператор решает merge стратегию"
  echo "  3. Если случайно создана пустой — rmdir пустых каталогов"
  echo "PM не пытается auto-merge — это нетривиальное решение."
  exit 1
fi
```

**Эскалация:** sanity-check выше блокирует автоматически на наличие **любого** `.agents/` или `.claude/` (целиком, не только `settings.json`). Если оператор намеренно хочет overwrite — он явно удаляет ВЕСЬ `.agents/` каталог И ВЕСЬ `.claude/` каталог (или backup'ит их) ДО запуска установщика. Удаление одного `settings.json` недостаточно: если остался хотя бы `.claude/agents/`, `.claude/hooks/`, `.claude/skills/`, `.claude/rules/` или `.claude/tools/` — guard сработает.

### B.2 Шаг b — Создать ветку

```bash
DATE=$(date +%Y-%m-%d)
BRANCH="pipeline-bootstrap-${DATE}"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  BRANCH="pipeline-bootstrap-${DATE}-$(date +%H%M%S)"
fi
git checkout -b "$BRANCH"
```

Имя ветки **должно** содержать `pipeline-bootstrap` (generic prefix) — это **prompt-level convention** для PM-самораспознавания Bootstrap-режима (см. PM_ROLE.md §2.0.5 «Признаки Bootstrap session»). **Hook-enforcement отсутствует** — это soft constraint, на который PM опирается при чтении контекста сессии. Для новых проектов используй ТОЛЬКО `pipeline-bootstrap-*`. Имя `bigheroes-pipeline-migration` — legacy marker от исторической миграции big-heroes → U2 (PR #185); распознаётся ради backward compat, но не используется в новых проектах.

### B.3 Шаг c — Копировать файлы

**Что копировать:**

| Источник | Назначение | Примечание |
|----------|-----------|------------|
| `$REFERENCE_REPO/.agents/*.md` | `.agents/` | Все markdown — доктрина (10 файлов: см. §F полный список) |
| `$REFERENCE_REPO/.claude/settings.json` | `.claude/settings.json` | Hooks + deny rules + permissions |
| `$REFERENCE_REPO/.claude/agents/*.md` | `.claude/agents/` | Native subagents |
| `$REFERENCE_REPO/.claude/hooks/*` | `.claude/hooks/` | Pre/Post/SessionStart hooks (вкл. `codex-login.sh`) |
| `$REFERENCE_REPO/.claude/skills/` | `.claude/skills/` | verify, sprint-pr-cycle, external-review, finalize-pr, pipeline-audit |
| `$REFERENCE_REPO/.claude/rules/*.md` | `.claude/rules/` | universal.md обязателен; client-*/server.md опционально |
| `$REFERENCE_REPO/.claude/tools/` (`*.mjs`, `*.ps1`, `package.json`, `README.md`) | `.claude/tools/` | Cross-model review backend (`openai-review.mjs`) + helpers (`codex-account-switch.ps1`, `smoke-test.mjs`) + `package.json` (+ `npm ci --ignore-scripts` при наличии lockfile) |

**Что НЕ копировать:**

- `.claude/settings.local.json` — personal overrides
- `.claude/worktrees/` — runtime artifacts
- `.claude/skills/external-review/.review-responses/` — runtime cache
- `.beads/` — issue tracker нового проекта инициализируется отдельно (шаг e)
- `.memory-bank/` — контекст нового проекта инициализируется отдельно (шаг e)
- `docs/plans/`, `docs/archive/` — это контент reference-проекта

**Команды:**

```bash
mkdir -p .agents .claude/{agents,hooks,skills,rules,tools}
cp -r "$REFERENCE_REPO/.agents/"*.md .agents/
cp "$REFERENCE_REPO/.claude/settings.json" .claude/
cp -r "$REFERENCE_REPO/.claude/agents/"*.md .claude/agents/
cp -r "$REFERENCE_REPO/.claude/hooks/"* .claude/hooks/

# skills/ — preventive cleanup runtime cache в reference перед копированием
# (rsync с exclude если доступен; иначе cp + reactive rm)
# Windows-операторы (git-bash без WSL) обычно не имеют rsync — fallback на cp.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude='.review-responses/' --exclude='__pycache__/' \
    "$REFERENCE_REPO/.claude/skills/" .claude/skills/
else
  # Windows fallback: cp без trailing slash на source копирует skills/ как
  # subdirectory. Trailing slash на source («.claude/skills/») копирует
  # ТОЛЬКО содержимое (могло бы создать .claude/<skills-content>/, не
  # .claude/skills/<content>/). Защита от структурного бага:
  cp -r "$REFERENCE_REPO/.claude/skills" .claude/
  # cleanup runtime cache (defensive, см. блок ниже)
fi

# Post-copy structural check (защита от cross-platform cp quirks).
# Проверяем все 5 обязательных skills — должны соответствовать D.1 acceptance criteria.
for required_skill in finalize-pr external-review verify sprint-pr-cycle pipeline-audit; do
  if [ ! -d ".claude/skills/${required_skill}" ]; then
    echo "СТОП: structural check skills/ упал — отсутствует .claude/skills/${required_skill}/"
    echo "Ожидаемая структура: .claude/skills/{finalize-pr,external-review,verify,sprint-pr-cycle,pipeline-audit}"
    echo "Проверь fallback cp/rsync — возможен nested skills/skills или missing subdirs."
    exit 1
  fi
done

cp -r "$REFERENCE_REPO/.claude/rules/"*.md .claude/rules/
# Все tools: review backend (.mjs) + helpers (.ps1) + manifest + README; node_modules исключён (rm ниже)
for tf in "$REFERENCE_REPO/.claude/tools/"*.mjs "$REFERENCE_REPO/.claude/tools/"*.ps1 \
          "$REFERENCE_REPO/.claude/tools/package.json" "$REFERENCE_REPO/.claude/tools/README.md"; do
  [ -f "$tf" ] && cp "$tf" .claude/tools/
done
# Lockfile (если есть) — для воспроизводимости через npm ci
[ -f "$REFERENCE_REPO/.claude/tools/package-lock.json" ] && cp "$REFERENCE_REPO/.claude/tools/package-lock.json" .claude/tools/

# Удалить runtime cache если случайно попал (defensive — на случай если
# rsync недоступен и пришлось fallback на cp)
rm -rf .claude/skills/external-review/.review-responses/
rm -rf .claude/worktrees/
rm -rf .claude/tools/node_modules/

# Установить зависимости openai-review.mjs.
# npm ci (а не install): строго по lockfile, не пачкает рабочее дерево, воспроизводимо.
# --ignore-scripts: defence-in-depth против supply-chain attack через postinstall hooks
# из npm registry. Trusted reference repo всё равно не гарантирует trust transitively.
#
# Fail-closed по умолчанию: если lockfile отсутствует — STOP. Это security-sensitive
# tooling (`openai-review.mjs` имеет доступ к OPENAI_API_KEY и code review prompts);
# dependency drift / supply-chain непредсказуемость недопустимы без явного operator
# acceptance. Если оператор сознательно хочет fallback — пусть установит env-var
# INSTALL_ALLOW_NPM_DRIFT=1 (явная opt-in).
if [ -f .claude/tools/package-lock.json ]; then
  (cd .claude/tools && npm ci --ignore-scripts)
elif [ "${INSTALL_ALLOW_NPM_DRIFT:-0}" = "1" ]; then
  echo "ВНИМАНИЕ: package-lock.json отсутствует, INSTALL_ALLOW_NPM_DRIFT=1 — fallback на npm install --ignore-scripts (dependency drift возможен; явный operator acceptance)"
  (cd .claude/tools && npm install --ignore-scripts)
else
  echo "СТОП: package-lock.json отсутствует в \$REFERENCE_REPO/.claude/tools/."
  echo "Это security-sensitive tooling — fail-closed по умолчанию."
  echo "Если оператор явно принимает risk: установи INSTALL_ALLOW_NPM_DRIFT=1 в env и перезапусти эти команды"
  echo "Безопаснее: попроси reference repo добавить package-lock.json и перезапусти."
  exit 1
fi
```

**Обнови `.gitignore`** (или создай если нет):

```gitignore
# Claude Code: коммитим shared pipeline-инфру (settings.json, hooks, agents,
# skills, rules, tools/*.mjs, tools/*.ps1, tools/package.json) для cross-machine portability.
# Исключаем только runtime artifacts и personal overrides.
.claude/settings.local.json
.claude/worktrees/
.claude/tools/node_modules/
.claude/**/*.local.*
.claude/**/credentials*
.claude/**/secrets*
.env
.env.*
*.key
*.pem
*.p12
*.crt
*.npmrc

# external-review skill runtime artifacts
.review-responses/
.claude/skills/external-review/.review-responses/

# Beads / Dolt files (added by bd init)
.dolt/
.beads/**/*.db
.beads/dolt-server.*
.beads-credential-key
```

### B.4 Шаг d — Адаптация (имя проекта, префикс Beads, стек)

> **Принцип:** generic-strict в `.agents/INSTALL.md` (не трогать), U2-specific можно адаптировать по месту в твоём проекте. Минимизируй правки — большинство файлов универсальны.

**Что обязательно адаптировать:**

| Файл | Что заменить | На что |
|------|--------------|--------|
| `.agents/*.md` ВСЕ файлы (frontmatter `source:`) | `github.com/<reference-owner>/<reference-repo>/...` | `github.com/<your-owner>/<your-repo>/...` — source-only command ниже, без переписывания body. Owner и repo определи через shell-команду в code block ниже (НЕ inline, чтобы pipe `\|` не сломался при copy-paste). |
| `.agents/PM_ROLE.md` строка `**Проект:** Universe Unlimited (U2)` | `Universe Unlimited (U2)` | Имя твоего проекта |
| `.agents/AGENT_ROLES.md` (frontmatter + строка 12 `Agent Roles — Universe Unlimited (U2)`) | `Universe Unlimited (U2)` | Имя твоего проекта |
| `.agents/PIPELINE.md` (frontmatter + заголовок `Пайплайн разработки Universe Unlimited (U2)`) | `Universe Unlimited (U2)` | Имя твоего проекта |
| `.agents/HOW_TO_USE.md` (frontmatter + контекстные упоминания) | `Universe Unlimited (U2)` если есть | Имя твоего проекта |
| `.claude/rules/universal.md` (если есть упоминания проекта) | проектные упоминания | Адаптируй |
| `.claude/skills/verify/SKILL.md`, `.claude/rules/tests.md` | `<PLACEHOLDER>`-команды и baseline-числа (стек-агностичный шаблон) | **Заполни** плейсхолдеры (`<CLIENT_DIR>`, `<CLIENT_BUILD_CMD>`, `<SERVER_BUILD_CMD>`, `<TEST_CMD>`, `<EXPECTED_CLIENT_TESTS>`, `<EXPECTED_SERVER_TESTS>`, `<WARNING_BASELINE>`) под свой стек. **Не удаляй** — скиллы поставляются как шаблон, а не как U2-хардкод. Имя скилла `/verify` менять нельзя. |
| `.claude/skills/sync-docs/SKILL.md`, `.claude/skills/sync-site-gdd/SKILL.md` | EXAMPLE doc/site-навигация (U2-пути `docs/INDEX.md`, ADR-INDEX, memory-bank, manifest сайта) | **Не generic как прочие скиллы.** `sync-docs` — адаптируй doc-пути (`<DOC_INDEX>`, `<ADR_INDEX>`, `<MEMORY_BANK>`) под свою структуру. `sync-site-gdd` — если у проекта **нет публичного сайта документации, удали скилл целиком**; иначе адаптируй `<SITE_HOST>`/`<SITE_MANIFEST>` и `scripts/find-missing.py`. |
| `.claude/rules/client-*.md`, `server.md` (если присутствуют) | Стек-специфичные tactical-правила (в reference-репо U2 — TS+Three.js, .NET+Entitas) | U2-payload: в этом overgate-репозитории таких файлов **нет**. Если твой reference-репо их принёс и стек **не** совпадает — удали или замени на свои; совпадает — оставь. |

**Shell-команда для автоматического определения owner/repo:**

```bash
# Извлечь owner/repo из git remote (HTTPS или SSH origin, с .git и без).
REMOTE_URL=$(git remote get-url origin)
OWNER_REPO=$(
  printf '%s\n' "$REMOTE_URL" |
    sed -E \
      -e 's#^https://github\.com/([^/]+/[^/]+)/?$#\1#' \
      -e 's#^git@github\.com:([^/]+/[^/]+)$#\1#' \
      -e 's#\.git$##'
)
if ! printf '%s' "$OWNER_REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
  echo "СТОП: не удалось извлечь owner/repo из origin: $REMOTE_URL" >&2
  echo "Ожидается GitHub remote вида https://github.com/owner/repo(.git) или git@github.com:owner/repo.git" >&2
  exit 1
fi
echo "Detected: $OWNER_REPO"

# Обновить ТОЛЬКО frontmatter source:. Не переписывай исторические reference links в body:
# ссылки на U2 PR #185/#186 — это reference baseline, не project-specific metadata.
for f in .agents/*.md; do
  tmp="$(mktemp)"
  awk -v owner_repo="$OWNER_REPO" '
    NR == 1 && $0 == "---" { in_fm = 1 }
    in_fm && /^source: "github\.com\/[^/]+\/[^/]+\// {
      sub(/^source: "github\.com\/[^/]+\/[^/]+\//, "source: \"github.com/" owner_repo "/")
    }
    { print }
    in_fm && NR > 1 && $0 == "---" { in_fm = 0 }
  ' "$f" > "$tmp" && mv "$tmp" "$f"
done
```

**Что НЕ нужно адаптировать:**

- `.agents/AGENTIC_PIPELINE.md` — universal philosophy + 7 invariants, уже generic
- `.agents/PIPELINE_ADR.md` — историческая запись решений, не переписывается под твой проект
- `.agents/INSTALL.md` (этот файл) — содержательно сохраняй как есть (U2 PR #185 как concrete reference baseline). **Адаптируй ТОЛЬКО frontmatter `source:` на свой `github.com/<owner>/<repo>/.agents/INSTALL.md`** через source-only `awk` block выше. Сам текст руководства не переписывай — он generic с U2-historical examples
- `.agents/REFERENCES.md` — на шаге B.4 оставь без содержательных правок; добавление твоего проекта в секцию «Собственные проекты» — post-merge landing artifact (см. §B.9/D.4), потому что Bootstrap считается установленным только после merge
- Бóльшая часть `.claude/skills/*/SKILL.md` — generic, не привязаны к проекту (`finalize-pr`, `external-review`, `sprint-pr-cycle`, `pipeline-audit`). **Исключения** (см. таблицу «Что обязательно адаптировать» выше):
  - `verify/SKILL.md` + `.claude/rules/tests.md` — поставляются с `<PLACEHOLDER>`-командами/baseline'ами, которые **заполняются** под стек (не удаляются и не «уже generic»);
  - `sync-docs/SKILL.md` + `sync-site-gdd/SKILL.md` — **EXAMPLE** doc/site-навигация: адаптируй пути или удали `sync-site-gdd`, если нет публичного сайта. НЕ считай их «generic, ничего не делать».
- **U2-payload скиллы/правила, которых в этом overgate-репозитории НЕТ** (`game-designer`, `mobile-game-analyst`, `.claude/rules/server.md`, `.claude/rules/client-*.md`): это содержимое dogfood-проекта U2. Если твой reference-репо их притащил — относись к ним как к стек/домен-специфике (адаптируй или удали), они не часть generic-ядра OverGate.
- Все `.claude/hooks/*` — generic enforcement
- `.claude/settings.json` — generic, deny rules универсальны. ⚠️ PreToolUse-хук `Bash(git commit*)` запускает npm-тесты только при наличии `package.json` (в не-npm проекте — no-op); это уже учтено и не требует правок.

**Адаптация Beads-префикса:**

Если ты хочешь свой префикс (например `mng-*` вместо `u2-*`/`big-heroes-*`) — это решается в `bd init` (шаг e), а не правкой файлов. Большинство ссылок на U2-* / big-heroes-* в документах — исторические референсы и не требуют замены.

### B.5 Шаг e — Инициализация runtime (Beads + Memory Bank)

**Beads:**

```bash
bd init                                    # создаёт .beads/, .gitignore-entries
bd doctor                                  # health check — должен быть зелёный
bd ready --json >/dev/null                 # acceptance check: tracker query работает

# ВНИМАНИЕ: per ADR 3.21 — только single-quotes для bd commands.
# Double-quoted с $VAR / $(date) bash раскрывает ДО передачи в bd, и
# значение попадает в Beads/Dolt persisted state. Если переменная
# содержит секрет — leak. Безопасный pattern — hardcoded literal или
# pre-substitute через intermediate variable + concatenation вне quotes:
bd remember 'Pipeline installed on YYYY-MM-DD. Reference: U2 PR #185 baseline.'   # подставь реальную дату
# Если нужен динамический контент — concatenate через '"$VAR"', не "$VAR":
#   INSTALL_DATE=$(date +%Y-%m-%d)         # safe: just a date, no secrets
#   bd remember 'Pipeline installed on '"$INSTALL_DATE"'. Reference: ...'
```

> **Важно:** `bd doctor` + `bd ready --json` — acceptance gate для шага e. Если любой из них красный — **СТОП**, не двигайся дальше. Чаще всего проблема: missing dolt binary или несовместимая версия. Обновляй `bd` до последней.

**Memory Bank:**

```bash
mkdir -p .memory-bank
```

Создай 6 файлов с минимальным содержимым (пустые шаблоны можно скопировать из reference как структурный пример, но **содержимое** должно быть про твой проект):

- `.memory-bank/projectbrief.md` — цели, ограничения, milestone-история (1-2 параграфа для старта)
- `.memory-bank/productContext.md` — зачем проект, UX (1 параграф)
- `.memory-bank/systemPatterns.md` — пока пусто, заполнится после первой архитектурной задачи
- `.memory-bank/techContext.md` — стек, команды, порты
- `.memory-bank/activeContext.md` — `**Текущий фокус:** Bootstrap pipeline установка через PR #N`
- `.memory-bank/progress.md` — `**Сделано:** установка пайплайна. **В процессе:** Bootstrap PR review.`

### B.6 Шаг f — Bootstrap PR (точка contained-confirmation)

> **Это единственная точка, где ты ОБЯЗАН остановиться и спросить оператора** — про структуру PR. Один большой коммит vs серия — нетривиальное решение.

**По умолчанию:** один большой коммит-bundle (все файлы пайплайна) + последующие fix-коммиты в рамках review-цикла. Это паттерн U2 PR #185.

```bash
# Уточнение по .beads/: коммитим только конфиг + tracker file, НЕ Dolt history.
# .gitignore (см. шаг c) уже исключает .dolt/ и Beads-local DB/runtime files. После bd init остаются:
#   .beads/issues.jsonl       — task tracker state (commit)
#   .beads/config.json        — local config (commit)
#   .beads-credential-key     — НЕ коммитим (в .gitignore)
# git add .beads/ корректно работает: tracked files добавятся, ignored игнорируются.
git add .agents/ .claude/ .gitignore .beads/ .memory-bank/
git status                                  # покажи оператору
# Спроси: "один большой коммит ОК?"

# Public label для commit/PR metadata: НЕ используй $REFERENCE_REPO напрямую,
# он может быть локальным filesystem path оператора.
REFERENCE_REMOTE=$(cd "$REFERENCE_REPO" && git remote get-url origin 2>/dev/null || true)
REFERENCE_OWNER_REPO=$(
  printf '%s\n' "$REFERENCE_REMOTE" |
    sed -E \
      -e 's#^https://github\.com/([^/]+/[^/]+)/?$#\1#' \
      -e 's#^git@github\.com:([^/]+/[^/]+)$#\1#' \
      -e 's#\.git$##'
)
REFERENCE_SHA=$(cd "$REFERENCE_REPO" && git rev-parse --short HEAD 2>/dev/null || echo unknown)
if printf '%s' "$REFERENCE_OWNER_REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
  REFERENCE_LABEL="$REFERENCE_OWNER_REPO@$REFERENCE_SHA"
else
  REFERENCE_LABEL="local-reference@$REFERENCE_SHA"
fi

git commit -m "feat(pipeline): bootstrap OverGate pipeline from $REFERENCE_LABEL

Двухслойный пайплайн: .agents/ (доктрина) + .claude/ (исполнение).
Reference baseline: U2 PR #185.

— PM (Claude Opus 4.7)"

git push -u origin "$(git branch --show-current)"

gh pr create \
  --title "Pipeline bootstrap from $REFERENCE_LABEL" \
  --body "$(cat <<'EOF'
## Summary
Bootstrap OverGate pipeline в новый проект.

- `.agents/` — доктрина (10 файлов): AGENTIC_PIPELINE, AGENT_ROLES, PM_ROLE, PIPELINE, PIPELINE_ADR, HOW_TO_USE, REFERENCES, INSTALL, CODEX_AUTH (legacy fallback для Codex CLI), pipeline-improvement-plan-v3.3 (исторический snapshot)
- `.claude/` — исполнение: settings.json, agents/, hooks/, skills/ (verify, sprint-pr-cycle, external-review, finalize-pr, pipeline-audit), rules/, tools/ (openai-review.mjs + helpers .mjs/.ps1 + README)

## Reference
- Source: U2 PR #185 (21 коммит, 7 итераций cross-model review GPT-5.4/5.5 mixed)
- Validation: bd doctor зелёный, .claude/tools/npm ci --ignore-scripts ОК (или INSTALL_ALLOW_NPM_DRIFT=1 npm install при отсутствии lockfile с явным operator acceptance)

## Tier: Sprint Final

Это Bootstrap PR — финальная гейт через `/finalize-pr` обязательна.
External review через `/external-review` обязательно (Sprint Final правило).

— PM (Claude Opus 4.7)
EOF
)"
```

**Маркер `Tier: Sprint Final` в body PR — обязателен**, иначе `/finalize-pr` ошибочно классифицирует Bootstrap PR как `standard` и пропустит external review.

### B.7 Шаг g — Активация PM-роли и dogfood старт

После создания PR — переключись в PM-режим:

```
Ты PM. Прочитай .agents/PM_ROLE.md секцию "2.0.5 Bootstrap session"
(если есть) или просто "2. Обязанности".

Контекст: Bootstrap PR #N только что создан. Это первый dogfood-цикл
для этого проекта. Tier: Sprint Final.

Действуй автономно: запусти /sprint-pr-cycle для внутреннего review-pass,
потом /external-review N для cross-model. Cycle review/fix/re-review
до APPROVED по всем аспектам. Это норма что Bootstrap проходит несколько
итераций (U2 baseline: 7).

Останавливайся только на блокерах. Findings которые нельзя/не нужно
фиксить сейчас — defer to Beads с обязательным ID.
```

### B.8 Шаг h — Cross-model review через `/external-review`

Запускается из PM-сессии. Скилл сам определяет режим (A primary / A-hybrid / A-legacy / C / D) — см. `.agents/PIPELINE.md §5`.

**Если Codex CLI залогинен на ChatGPT subscription** (`codex login status` → `Logged in using ChatGPT`, profile `[profiles.review]` в `~/.codex/config.toml` загружается) → **Mode A primary (v3.9)**: GPT-5.5 + GPT-5.3-Codex через subscription quota. См. ADR 3.27 + CODEX_AUTH.md §8.

**Иначе если `OPENAI_API_KEY` установлен** → **Mode A-legacy (v3.6 baseline)**: через `openai-review.mjs` (Node.js native Platform API). GPT-5.5 primary + GPT-5.3-Codex или GPT-5.4 fallback.

**Если оба пути недоступны** → Mode C (Claude adversarial) — degraded. **Scope ограничен ADR 3.20: только doc-only landing commit, НЕ для full Bootstrap PR.** Bootstrap PR содержит executable infrastructure (`.claude/hooks/*`, `.claude/settings.json`, deny rules, `openai-review.mjs`, skills) — security-sensitive код, для которого требуется cross-model adversarial diversity. Если ни Codex CLI subscription, ни `OPENAI_API_KEY` недоступны на установочной машине — оператор должен либо настроить один из двух путей, либо явно принять risk через operator acceptance перед `/finalize-pr` (Mode D через ручное Copilot review).

**Stateless model dedup:** GPT-5.5 не помнит предыдущие итерации. Если он повторяет finding, который PM уже triage'нул в предыдущей итерации — PM агрегирует как duplicate, не запускает повторный fix-cycle (см. `AGENT_ROLES.md §3 Reviewer`).

### B.9 Шаг i — Финализация PR (стандартный v3.4 pre-merge dual-invocation)

> ⚠️ **REVISED 2026-05-05 (после PR #186 retrospective):** Прежняя версия §B.9 предписывала Bootstrap exception (post-merge landing). Это был over-engineered design. **Bootstrap PR теперь следует стандартному v3.4 pattern** — inline pre-merge landing, как любой обычный Sprint Final (см. PM_ROLE.md §2.5).
>
> **Reasoning revision:** запись «Bootstrap COMPLETE» в Memory Bank на ветке PR — это **intent**, который становится фактом ПОСЛЕ operator merge. Семантически identical с записью «Sprint N завершён» в обычном Sprint Final landing. Branch protection на default branch делает Путь 2 (operator direct push) технически невозможным. Inline pre-merge landing — единственный sane вариант.

После APPROVED от всех каналов — **dual-invocation per §2.5 Landing the Plane** (как любой Sprint Final):

```bash
# Шаг 1 — первый /finalize-pr с --pre-landing
PM: /finalize-pr <PR_NUMBER> --pre-landing
# Скилл опубликует первый "## ✅ Готов к merge" с warning
# "⏳ Pre-merge landing commit впереди — жди второй /finalize-pr". НЕ мержи!

# Шаг 2 — landing commit ВНУТРИ ветки PR
# Landing artifacts:
# - .memory-bank/activeContext.md — запись "Bootstrap pipeline COMPLETE YYYY-MM-DD"
# - bd remember 'Bootstrap pipeline COMPLETE on YYYY-MM-DD. Lessons: ...'  # single-quotes per ADR 3.21
# - .agents/REFERENCES.md — твой проект в секцию «Собственные проекты»
# - bd close <bootstrap-tracker-id> если был создан в §B.5/§B.7
git add .memory-bank/ .agents/REFERENCES.md
git commit -m "chore(landing): pre-merge artifacts — Bootstrap PR #N"
git push

# Шаг 3 — второй /finalize-pr БЕЗ --pre-landing на новом HEAD
PM: /finalize-pr <PR_NUMBER>
# Скилл опубликует второй "## ✅ Готов к merge" без warning.
# Это единственный сигнал к merge для оператора.
```

> **Что значит «как обычный Sprint Final»:** PM_ROLE.md §2.5 Landing the Plane описывает этот pattern для всех Sprint Final PR. Никаких Bootstrap-специфичных шагов больше нет — используй §2.5 как single source of truth.

### B.10 Шаг j — Merge оператором

> **Это единственный merge, который делает оператор.** Ты как ИИ-агент **не мержишь**.

Сообщи оператору после второго `/finalize-pr` (без warning):

```
PR #N готов к merge:
- ✅ Готов к merge (без warning) опубликован после landing commit
- Landing artifacts inside ветки PR (Memory Bank update, REFERENCES update, bd remember)
- bd doctor зелёный
- Все Beads-замечания либо closed, либо deferred с ID

Жду твоего merge через GitHub UI или `gh pr merge N` (любой mode).
```

> ⚠️ **Заметка про squash merge и D.4:** GitHub при `--squash` создаёт single squash-commit (не merge-commit с двумя parents). D.4 acceptance criterion «PR-history содержит merge-коммит с маркером `Tier: Sprint Final`» относится к body/title PR-а или squash-commit message — не к git merge-commit структуре. Squash merge сохраняет PR title/body метаданные.

После merge оператора → проект готов к обычным спринтам через `HOW_TO_USE.md`. **Никаких post-merge housekeeping шагов нет** — всё уже в landing commit ветки PR.

> ⛔ **Запрещено:** PM пушит artifacts напрямую в default branch (branch protection всё равно блокирует, но даже без protection — нарушит инвариант #4).

---

## C. Bootstrap pattern (chicken-and-egg note)

> Эта секция — для понимания, **почему** Bootstrap PR требует contained-confirmation gates вместо полностью автономного режима.

**Парадокс:** пайплайн обещает автономность через hard gates (`/finalize-pr` verify-on-commit), но первый PR — это сам пайплайн, и hard gates ещё не работают на нём по полной (например `/verify` нет если нет тестовой инфраструктуры; landing artifacts ссылаются на сам себя).

**Решение в U2 PR #185:**

1. **Один разовый ручной merge оператором** — это и есть единственный gate, который обходит chicken-and-egg.
2. **Все остальные шаги** (review/fix/external/finalize) проходят как обычно — потому что hooks и skills уже на ветке после первого commit.
3. **Mode C (degraded) допустим ТОЛЬКО для doc-only landing commit** (per ADR 3.20). Для full Bootstrap PR Mode C **недопустим** — Bootstrap PR содержит executable infrastructure, требует cross-model adversarial diversity. Mode C — exception для landing artifacts только.

**Урок для будущих миграций:** не пытайтесь автоматизировать Bootstrap merge. Это нарушит инвариант 7 (merge — решение оператора) и создаст рекурсивную дыру в trust model.

**Что НЕ делает пайплайн в Bootstrap:**

- Не пушит в default branch (даже Bootstrap PR — через PR, никогда напрямую)
- Не использует `git checkout` для сброса (защита pipeline self-defense)
- Не модифицирует `.gitignore` после первого commit без явной правки PM
- Не запускает `/external-review` на ветках без PR (защита от leak prompts в trusted env)

---

## D. Критерии завершения установки

> **Установка считается завершённой, когда выполнены ВСЕ пункты ниже.** Если хотя бы один не выполнен — пайплайн не готов к production-спринтам.

### D.1 Структурные

- [ ] `.agents/` присутствует в default branch с 10 doctrine-файлами: AGENTIC_PIPELINE, AGENT_ROLES, PM_ROLE, PIPELINE, PIPELINE_ADR, HOW_TO_USE, REFERENCES, INSTALL, CODEX_AUTH, pipeline-improvement-plan-v3.3
- [ ] `.claude/settings.json` присутствует в default branch
- [ ] `.claude/hooks/` укомплектован: `check-merge-ready.py`, `test_check_merge_ready.py`, `codex-login.sh` (SessionStart-хук из `settings.json` — без него `bash .claude/hooks/codex-login.sh` укажет на missing file)
- [ ] `.claude/skills/` содержит как минимум: `verify`, `sprint-pr-cycle`, `external-review`, `finalize-pr`, `pipeline-audit`
- [ ] `.claude/tools/` укомплектован: `openai-review.mjs`, `codex-account-switch.ps1`, `smoke-test.mjs`, `package.json`, `README.md` присутствуют, `npm ci --ignore-scripts` отработал. **Если `package-lock.json` отсутствует** — fail-closed по умолчанию (`exit 1`); fallback `npm install --ignore-scripts` разрешён ТОЛЬКО при явном `INSTALL_ALLOW_NPM_DRIFT=1` operator acceptance (см. §B.3)
- [ ] `.gitignore` обновлён (runtime artifacts исключены)

### D.2 Runtime

- [ ] `bd doctor` без ошибок
- [ ] `bd ready` возвращает валидный JSON (даже если пусто)
- [ ] `.memory-bank/activeContext.md` существует и содержит контекст проекта (не пустой)
- [ ] PM-промпт активации работает (Claude отвечает как PM, читает MEMORY)

### D.3 Dogfood-цикл

- [ ] Bootstrap PR прошёл хотя бы один полный `/sprint-pr-cycle` (внутренний review-pass APPROVED)
- [ ] Bootstrap PR прошёл `/external-review` **Mode A primary / A-hybrid / A-legacy** (cross-model GPT-5.5 primary + GPT-5.3-Codex; GPT-5.4 — допустимый fallback для GPT-5.5 в Mode A-legacy; см. §B.8 + PIPELINE.md §5 + ADR 3.27). **Альтернативно — Mode D** (ручное VS Code Copilot Agent review) с явной фиксацией operator risk acceptance в PR comment (формат: `Operator risk acceptance: external review через Mode D, причина: ..., scope: full Bootstrap PR, commit: abcd1234, подпись оператора`). **Mode C для full Bootstrap PR недопустим** — Bootstrap PR содержит executable infrastructure (см. §B.8 + ADR 3.20)
- [ ] **Pre-merge dual-invocation per §2.5 + §B.9:** первый `/finalize-pr --pre-landing` → landing commit inline → второй `/finalize-pr` без флага. Финальный `## ✅ Готов к merge` БЕЗ warning опубликован после landing commit на новом HEAD
- [ ] Bootstrap PR смерджен оператором в default branch

### D.4 Документация (pre-merge inline в landing commit)

> ✅ **REVISED 2026-05-05:** D.4 чек-листы выполняются **ВНУТРИ ветки PR в landing commit** (per §2.5 + §B.9), как обычный Sprint Final. Прежняя Bootstrap exception (post-merge) отменена per PR #186 retrospective.

- [ ] `.memory-bank/activeContext.md` обновлён в landing commit с записью «Bootstrap pipeline COMPLETE YYYY-MM-DD»
- [ ] `bd remember` содержит запись с lessons learned из Bootstrap PR
- [ ] `.agents/REFERENCES.md` обновлён в landing commit — твой проект добавлен в секцию «Собственные проекты»
- [ ] PR-метаданные (title, body, или squash-commit message при squash merge) содержат маркер `Tier: Sprint Final`. Не требуется git merge-commit как отдельный объект (squash merge создаёт single commit без двух parents — это валидно)

### D.5 Финальный smoke test

> **Manual smoke check** — это subjective acceptance gate, не automatable. Использовать как complement к D.1-D.4 (machine-checkable).

После merge Bootstrap PR в default branch, оператор запускает:

```
Ты PM. Прочитай .agents/AGENT_ROLES.md секция "0. Project Manager".
Задача: покажи текущее состояние проекта и предложи план Sprint 1.
```

**Объективные критерии успеха** (все должны выполниться, не subjective оценка):

- [ ] PM возвращает не пустой ответ длиной > 200 символов
- [ ] В ответе явно упоминается «Bootstrap COMPLETE» или эквивалент из `.memory-bank/activeContext.md`
- [ ] В ответе вызывается `bd ready` или эквивалент (упоминание Beads-задач)
- [ ] PM предлагает план Sprint 1 как минимум с 2-3 конкретными задачами (не общие фразы)
- [ ] Нет ошибок типа «не могу прочитать», «файл не найден», «недоступно»

→ **Установка завершена.** Дальше — обычная работа через `HOW_TO_USE.md`.

Если хотя бы один критерий не выполнен — диагностируй: какой шаг (D.1-D.4) не доделан, и докручивай.

---

## E. Что делать при провале установки

| Симптом | Диагноз | Что делать |
|---------|---------|------------|
| `bd doctor` красный | Beads не инициализирован или версия старая | `bd init`, обновить `bd` до последней |
| `/verify` ругается на отсутствие тестов | Тестовой инфры в проекте ещё нет | Это норма для нового проекта — `/verify` пропустит шаг тестов или вернёт N/A; добавь tests в Sprint 1 |
| Hook блокирует `gh pr comment` | PreToolUse matcher срабатывает в bootstrap-режиме | Проверь `.claude/settings.json` matchers; в U2 PR #185 фиксили catch-22 в Step 7.10 |
| `/external-review` падает с auth error | Codex CLI subscription и `OPENAI_API_KEY` оба недоступны | **Primary path (v3.9, ADR 3.27):** `codex login` через browser → workspace picker, профиль `[profiles.review]` в `~/.codex/config.toml` (см. CODEX_AUTH.md §8). **Fallback (Mode A-legacy, v3.6):** session-only `$env:OPENAI_API_KEY = '...'` (PowerShell) или `export OPENAI_API_KEY=...` (bash). `setx OPENAI_API_KEY ...` (Windows) сохраняет ключ в registry — это persisted, противоречит духу ADR 3.23. Если нужен persisted — используй secrets manager. **Fallback на Mode C ограничен** — только doc-only landing commit (ADR 3.20). Для full Bootstrap PR Mode C **недопустим** (см. §B.8 + §D.3); либо настрой один из путей, либо явно прими risk через Mode D (ручное Copilot review). |
| `/finalize-pr` блокирует на отсутствии Tier | В body PR нет строки `Tier: ...` | Добавь `Tier: Sprint Final` в body PR через `gh pr edit N --body` |
| Bash переменная `$VAR` раскрылась в `bd create` и закоммичен secret | Использовал double-quotes с `$OPENAI_API_KEY` или подобным | Только single-quotes для bd commands; rotate secret немедленно |
| `git checkout file` блокируется deny-rule | Сработала pipeline self-defense | Это **positive** signal. Используй `git restore --source=HEAD --staged --worktree -- file` (если разрешено) или Edit для аккуратной правки |

---

## F. Связанные документы

| Файл | Когда читать |
|------|--------------|
| `.agents/HOW_TO_USE.md` | После завершения установки — обычная работа |
| `.agents/PIPELINE.md` | Карта компонентов и lifecycle спринта |
| `.agents/PM_ROLE.md` | Детальный workflow PM, включая §2.0.5 Bootstrap session |
| `.agents/AGENT_ROLES.md` | Промпты активации для всех ролей |
| `.agents/PIPELINE_ADR.md` | Решения 3.16-3.24 (PR #185 dogfood + convergence cap из PR #186) + ADR 3.27 (v3.8 — Codex CLI ChatGPT subscription primary backend) |
| `.agents/AGENTIC_PIPELINE.md` | Философия generic, для понимания «почему». Полные нумерованные инварианты — в `PIPELINE_ADR.md §3` |
| `.agents/REFERENCES.md` | Источники и референсы фреймворков |
| `.agents/CODEX_AUTH.md` | **Primary backend setup (v3.9).** §8 — ChatGPT subscription path для Mode A primary (browser OAuth, workspace picker, `[profiles.review]` config). §1-§7 — legacy Platform API path для Mode A-legacy fallback. §9 — legacy footnote. Читай при первой настройке и при auth issues |
| `.agents/pipeline-improvement-plan-v3.3.md` | **Исторический snapshot.** План эволюции пайплайна v3.3, переехал из big-heroes как reference. Не required для миграции, но полезен для понимания контекста ADR 3.11-3.15 |
