---
title: "Codex CLI authentication paths setup for Claude Code"
status: active
version: "2.2"
date: 2026-05-17
source: "github.com/komleff/overgate/.agents/CODEX_AUTH.md"
tags: [pipeline, codex, openai, auth, external-review, chatgpt-subscription]
related:
  - .agents/REFERENCES.md
  - .agents/PIPELINE_ADR.md (ADR 3.27)
  - .claude/tools/codex-account-switch.ps1
---

# Codex CLI authentication paths

> 🔄 **Sprint Pipeline v3.8 (2026-05-05): два пути аутентификации, primary поменялся.**
>
> | Путь | Статус | Quota | Когда использовать |
> |------|--------|-------|-------------------|
> | **§8 ChatGPT subscription** | ✅ **PRIMARY** (validated 2026-05-05) | Plus/Pro/Business месячная подписка | Default для всех external review вызовов |
> | **§1-§7 + §9 OpenAI API key (Platform API)** | ⛔ Legacy — emergency-only | Pay-per-token (дорого; на практике квота исчерпывается мгновенно) | Только аварийно, если ChatGPT subscription path полностью недоступен |
>
> ⛔ **Operator decision 2026-05-17 (bead U2-v43k):** Platform API key path признан дорогим и фактически нерабочим (месячный лимит сжигается за час). Это **не равноправный fallback** — используется только в аварийной ситуации. SessionStart-хук `codex-login.sh` (API-key автологин) по умолчанию выключен (opt-in `OVERGATE_CODEX_AUTOLOGIN`). Штатный путь — §8 ChatGPT subscription.
>
> **Quick start (subscription):**
> ```bash
> npm install -g @openai/codex@latest
> codex login                              # browser → workspace picker → выбрать workspace
> codex -p review -c sandbox_mode="danger-full-access" review --commit <SHA>
> ```
>
> Полный setup и pipeline pattern — §8.

---

# Часть 1. Legacy: API key (Platform API) — §1-§7

Документ описывает, как настроить Codex CLI так, чтобы **любая сессия Claude Code** в проекте Universe Unlimited (U2) автоматически получала доступ к моделям OpenAI (primary `GPT-5.5` + `GPT-5.3-Codex`; `GPT-5.4` — fallback) для внешнего ревью PR через скилл [`/external-review`](../.claude/skills/external-review/SKILL.md).

Документ — часть пайплайна агентов (см. соседние файлы в `.agents/`). Читай целиком — в конце раздел «Что делать при компрометации ключа».

---

## 1. Архитектура решения

```
┌───────────────────────────────────────┐
│ OpenAI Dashboard                      │
│ • Project (Default или отдельный)     │
│ • Restricted API key                  │
└──────────────────┬────────────────────┘
                   │ sk-proj-...
                   ▼
┌───────────────────────────────────────┐
│ Источник OPENAI_API_KEY (один из):    │
│ • Claude Code Web → Secrets           │
│ • ~/.claude/settings.json → env       │
│ • .claude/settings.local.json → env   │
│ • shell rc (export)                   │
└──────────────────┬────────────────────┘
                   │ env var в каждой сессии
                   ▼
┌───────────────────────────────────────┐
│ SessionStart hook                     │
│ .claude/hooks/codex-login.sh          │
│ → codex login --with-api-key (stdin)  │
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────┐
│ ~/.codex/auth.json (chmod 600)        │
│ живёт в $HOME, вне git-репо           │
└───────────────────────────────────────┘
```

Ключ **никогда не попадает в git**: он хранится в Secrets/user-global settings/shell, пробрасывается в сессию как env var, а хук на старте сессии делает логин Codex из stdin.

> **Platform note:** схема показывает POSIX-путь `$HOME/.codex/`. На Windows git-bash `$HOME == $USERPROFILE`, физический путь — `%USERPROFILE%\.codex\`. Hook использует `${HOME:-}` expansion, которое в git-bash разрешается корректно. `chmod 600` на Windows — no-op (NTFS ACL, не POSIX bits), auth.json полагается на стандартный user-profile ACL.

---

## 2. Создание API key в OpenAI

### 2.1 Project (контекст биллинга)

OpenAI Project — это **биллинговый/изоляционный контейнер**, не «программный продукт». Один project = одна категория интеграции (Claude Code, Cursor, VS Code Copilot…), а не одна игра. Разделять имеет смысл по **источнику запросов**, чтобы:

- usage и алерты считались отдельно;
- при компрометации revoke не задел другие интеграции.

**Рекомендация:** отдельный проект `claude-code-codex` (Settings → Projects → Create project). Если в твоём аккаунте Projects не управляются (только `Default project`) — оставайся в Default, главное настроить Limits (§2.4).

### 2.2 Restricted API key — минимальные permissions

В выбранном проекте: **API keys → Create new secret key → Restricted**.

**Name:** `claude-code-codex` (или с датой ротации).

#### Семантика уровней OpenAI

| Уровень | Что значит |
|---|---|
| **None** | 403 на любой вызов |
| **Read** | только GET (актуально для эндпоинтов с listing — например `/v1/models`) |
| **Request** | разрешён инференс — основной рабочий уровень для эндпоинтов без stored ресурсов |
| **Write** | плюс создание/изменение хранящихся ресурсов (доступен только там, где такие ресурсы есть) |

Важно: уровни Write vs Request в OpenAI UI **зависят от эндпоинта**, не одинаковы повсеместно. Для Chat completions, Embeddings, TTS максимум — `Request` (эти эндпоинты без stored ресурсов). Для `/v1/responses` доступен `Write` — т.к. Responses API управляет хранимым context state (streaming sessions). Для File API и Fine-tuning тоже доступен `Write`. «Request» — полноценный доступ к inference, не урезанный; `Write` — плюс ресурс-ops, где они есть.

#### Минимальный набор permissions для `codex review`

| Скоуп | Уровень | Зачем |
|---|---|---|
| **List models** | **Read** | Codex CLI опрашивает `/v1/models` в некоторых сценариях (интерактивный login / model discovery). **Не используется** при `codex login --with-api-key` — этот путь сохраняет ключ без валидации (см. §4 troubleshooting row про «Hook OK но 401»). Оставлен в минимальном наборе на случай будущих версий CLI |
| **Model capabilities → Responses** (`/v1/responses`) | **Write** | Основной API для `codex review` |
| **Model capabilities → Chat completions** (`/v1/chat/completions`) | **Request** | Fallback для отдельных моделей |
| Model capabilities → Text-to-speech | **None** | Не используется |
| Model capabilities → Realtime | **None** | Не используется |
| Model capabilities → Embeddings | **None** | Не используется |
| Model capabilities → Images | **None** | Не используется |
| Model capabilities → Moderations | **None** | Не используется |
| Assistants | **None** | Не используется |
| Threads | **None** | Не используется |
| Evals | **None** | Не используется |
| Fine-tuning | **None** | Не используется |
| Files | **None** | Ревью передаёт diff inline, файлы не загружает |
| Videos | **None** | Не используется |
| Vector Stores | **None** | Не используется |
| Prompts | **None** | Не используется |
| Datasets | **None** | Не используется |
| Batch / Uploads / Audit logs | **None** | Не используется |
| Organization / Billing / Members | **None** | Критично — иначе ключ сможет менять биллинг и приглашать юзеров |

Итого: **5 selected permissions** (List models: Read + Responses: Write + Chat completions: Request, остальные None).

> **Правило:** UI OpenAI для каждого скоупа предлагает свой набор уровней. Если для какого-то поля нет варианта `Write` — это нормально, у этого эндпоинта нет stored-ресурсов; используй максимум, который доступен (обычно `Request`).

### 2.3 Model allowlist (если доступно в UI)

Если в настройках проекта есть «Model access» или «Allowed models» — ограничь только теми моделями, что использует `/external-review`:

- `gpt-5.5` — primary (reasoning)
- `gpt-5.3-codex` — primary (code-специализация)
- `gpt-5.4` — fallback для `gpt-5.5`
- (опционально) дефолтная модель Codex CLI на случай fallback

Защита от misuse: даже при утечке нельзя будет вызывать дорогие модели вне набора.

### 2.4 Usage limits (бюджет)

**Settings → Limits → Usage limits** на уровне проекта:

| Лимит | Рекомендация | Обоснование |
|---|---|---|
| **Hard limit** | `$50/мес` для старта | Одно ревью PR = ~$1-4 (2 ревьюера × ~100k токенов). При 15-20 PR/мес хватит с запасом |
| **Soft limit (email alert)** | `$30/мес` (60% от hard) | Заранее увидишь аномальный расход |
| **Rate limit: RPM** | 20 | `codex review` делает ~5-10 запросов на ревью; 20 RPM хватит на 2-3 одновременных ревью |
| **Rate limit: TPM** | `200k` | С запасом на большие diff'ы |

> Первый месяц — понаблюдай фактический расход в OpenAI Dashboard → Usage. Потом скорректируй hard limit до `max(наблюдаемое × 3, $20)`.

### 2.5 Срок жизни ключа (expiration)

Если UI поддерживает `expires_at` — **90 дней**. Принудительная ротация отрежет утёкший ключ автоматически. Иначе — поставь напоминание раз в 90 дней.

### 2.6 ВАЖНО: API-кредиты

API оплачивается **отдельно** от ChatGPT Plus/Pro/Team. Без кредитов любой запрос → `429 You exceeded your current quota`, даже с валидным ключом и полными правами. **Settings → Billing → Add credits** ($10-20 для старта).

---

## 3. Размещение ключа в Claude Code

Иерархия по приоритету (от лучшего к худшему):

### 3.1 Claude Code Web (`claude.ai/code`) — Secrets

1. Открой проект в web-интерфейсе.
2. **Settings → Environment Variables / Secrets**.
3. Добавь:
   - **Name:** `OPENAI_API_KEY`
   - **Value:** `sk-proj-...`
   - **Scope:** project (или user, если хочешь использовать в нескольких репо)
4. Сохрани.

После этого во всех новых сессиях переменная доступна, и SessionStart-хук автоматически залогинит Codex.

### 3.2 Claude Code Desktop / CLI — user-global settings (рекомендуется)

Если работаешь в нескольких репозиториях, удобнее всего положить ключ **один раз** в user-global settings — ключ будет работать во всех проектах.

Файл: `~/.claude/settings.json` (на macOS/Linux) или `%USERPROFILE%\.claude\settings.json` (Windows).

```jsonc
{
    "$schema": "https://json.schemastore.org/claude-code-settings.json",
    "env": {
        "OPENAI_API_KEY": "sk-proj-..."
    },
    "permissions": {}
    // ... другие секции (permissions, hooks) — оставь существующие.
    // Важно: после "env": {...} ставь запятую, если дальше идут другие секции.
}
```

После правки: `chmod 600 ~/.claude/settings.json` и перезапусти сессии.

### 3.3 Shell rc — env через систему

```bash
# в ~/.zshrc или ~/.bashrc
export OPENAI_API_KEY='sk-proj-...'
```

Либо через менеджер секретов:

```bash
# 1Password CLI
export OPENAI_API_KEY="$(op read 'op://Personal/OpenAI Big Heroes/credential')"
```

Claude Code наследует env из shell, в котором запущен.

### 3.4 Project-local fallback: `.claude/settings.local.json`

Если нужно привязать ключ к **одному** проекту:

```jsonc
// .claude/settings.local.json — НЕ коммитится (в .gitignore)
{
    "env": {
        "OPENAI_API_KEY": "sk-proj-..."
    }
}
```

Файл **должен** быть в `.gitignore` (в этом репо уже добавлен — см. `.gitignore`). В web-сессиях не работает (репо клонируется свежим каждый старт).

### 3.5 ⚠️ Чего делать НЕ надо

**Не клади ключ в `.claude/settings.json`** проекта — он коммитится в git.

```jsonc
// ❌ ОПАСНО — settings.json коммитится
{
    "env": {
        "OPENAI_API_KEY": "sk-proj-..."  // утечёт в историю репо!
    }
}
```

`.claude/settings.json` — shared-файл команды (permissions, хуки). Ключ оттуда попадёт в коммит, в PR, в GitHub-зеркала, в индекс поисковиков. Revoke не отменит репутационную утечку.

> **Приоритет:** Secrets (3.1) > user-global settings.json (3.2) > shell rc (3.3) > settings.local.json (3.4) >>> shared settings.json (❌ никогда).

---

## 4. Проверка работы

> ⛔ Проверка относится к **legacy emergency-only** Platform API-key пути (hook `codex-login.sh`, opt-in `OVERGATE_CODEX_AUTOLOGIN`). Команды `codex ...` ниже предполагают глобальный binary, установленный по §8 (`npm install -g @openai/codex`). Если ставился ТОЛЬКО legacy путь без §8 — используй `npx '@openai/codex@~0.20' ...` вместо `codex ...` (хук логинит именно через этот pinned npx-пакет).

В новой сессии Claude Code:

```bash
# 1. Хук отработал при старте?
codex login status
# → Logged in using an API key - sk-proj-***XXXX

# 2. Env var видна?
printenv OPENAI_API_KEY | head -c 15
# → sk-proj-XXXXXXX (первые 15 символов твоего ключа)

# 3. Smoke-тест запроса
echo 'Скажи pong' | codex exec -
```

### Возможные ошибки

| Ошибка | Причина | Лечение |
|---|---|---|
| `printenv` пусто | JSON в settings.json сломан или env-секция не на верхнем уровне | `python3 -m json.tool ~/.claude/settings.json` |
| `401 Unauthorized` | Ключ скопирован неполностью / лишний пробел | Перекопировать целиком из OpenAI Dashboard |
| `403 Forbidden` на конкретной модели | Permissions слишком узкие (не Responses: Write) | Проверь permissions ключа (§2.2) |
| `429 quota exceeded` | На аккаунте нет API-кредитов | OpenAI → Billing → Add credits (§2.6) |
| `model X not found` | Модель не входит в твой tier | Скорректируй модели в `/external-review` SKILL.md |
| `Not logged in` после старта сессии | Хук не сработал — проверь путь `.claude/hooks/codex-login.sh` читаем, в `.claude/settings.json` есть `hooks.SessionStart` с этим путём, в PATH доступны `bash` и `npx` | `bash .claude/hooks/codex-login.sh` вручную; см. логи: `cat ~/.codex/log/*.log` |
| Hook exit 0 + stderr `установлен` / silent, но `/external-review` возвращает `401 Unauthorized` | `codex login --with-api-key` не валидирует ключ при сохранении — hook успешно пишет в `auth.json` любую строку. Реальная невалидность проявляется только на первом API call. Ключ в env либо revoke'нут, либо неполностью скопирован, либо из другого OpenAI project | `codex logout && printenv OPENAI_API_KEY \| head -c 15` — проверь префикс; пересоздай ключ на OpenAI Dashboard; обнови источник (Secrets / settings / shell rc); перезапусти сессию |

---

## 5. Ротация ключа

**Раз в 90 дней (или при подозрении на утечку):**

1. В OpenAI Dashboard создай новый restricted key с теми же permissions (§2.2).
2. Обнови значение `OPENAI_API_KEY` в источнике (Secrets / user-global settings / shell rc).
3. Дождись, пока все открытые сессии перезапустятся (или перезапусти вручную).
4. В OpenAI Dashboard **revoke** старый ключ.
5. Проверь Usage за 24 часа: запросов со старого ключа быть не должно.

---

## 6. Что делать при компрометации ключа

**Признаки:** аномальный расход в OpenAI Usage, email-alert от OpenAI, ключ засветился в git/PR/чате/скриншоте.

### Действия (по срочности):

1. **Немедленно revoke** в OpenAI Dashboard → API keys → Revoke. Доступ отсекается мгновенно.
2. Создай новый ключ (§2.2) и обнови источник (§3).
3. Проверь Usage за 24-72 часа: нетипичные модели, объёмы токенов, время.
4. Если ключ засветился в git:
   - `git rebase -i` НЕ помогает: GitHub/GitLab уже индексируют историю и могут раздать ботам.
   - Ключ скомпрометирован, даже если commit удалён. Обязателен revoke.
   - Проверь `git reflog` и remote mirrors.
5. При подозрении на misuse — напиши в OpenAI Support с указанием key prefix (`sk-proj-***last4`).

### Быстрая проверка, не засветился ли ключ в репо

```bash
git log --all -p -S 'sk-proj-' | head
git log --all -p -S 'OPENAI_API_KEY=' | head
```

Пусто = чисто.

---

## 7. Сводка: безопасность vs функциональность

| Что даёт ограниченный ключ | Что теряем |
|---|---|
| Компрометация = максимум $50/мес убытков (hard limit) | Ничего — весь набор прав `codex review` доступен |
| Ключ не может менять биллинг/приглашать юзеров | — |
| Только whitelisted модели (если allowlist настроен) | — |
| Ротация каждые 90 дней ограничивает окно злоупотребления | — |
| Алерты при 60% бюджета ловят аномалии | — |

**Итог:** полноценное ревью PR возможно без компромиссов по безопасности.

---

# Часть 2. Primary: ChatGPT subscription path — §8

## 8. ChatGPT subscription path (validated 2026-05-05)

> **Why:** Platform API (§1-§7) — pay-per-token, ~$20-22 за один `codex review` с `reasoning_effort: high`. PR #186: $560-620 за 14 итераций. Operator потерял $100 за вечер на infinite loop.
>
> ChatGPT subscription quota — fixed monthly ($25 Plus / $100 Pro / $30/seat Business), $0/вызов в пределах квоты. См. ADR 3.27.

### 8.1 Пререкизиты

- **Codex CLI** (npm install) — `npm install -g @openai/codex@latest`. Подтверждено на v0.128.0.
- **ChatGPT account** хотя бы Plus tier. Pro и Business tiers дают больше квоты.
- **Browser** на этой машине для OAuth flow (один раз на аккаунт).

> ⚠️ **Codex CLI subscription quota ≠ Platform API credits.** ChatGPT Plus/Pro/Business **НЕ включают** Platform API. Подписка покрывает только Codex CLI / ChatGPT.com / OpenAI desktop apps. Платежи раздельные.

### 8.2 Browser OAuth login

```bash
codex login
# → Открывает http://localhost:1455/auth/callback в браузере.
# → На auth.openai.com логинишься (если ещё нет сессии).
# → Workspace picker (для same-email accounts с несколькими workspace'ами):
#    выбери нужный workspace (Personal / Business / Enterprise).
# → "Signed in to Codex"
```

Verify:

```bash
codex login status
# → "Logged in using ChatGPT"
```

### 8.3 Pipeline invocation pattern (production-ready)

```bash
codex -p review -c sandbox_mode="danger-full-access" review --commit "$HEAD_COMMIT"
# или для PR:
codex -p review -c sandbox_mode="danger-full-access" review --base "origin/main"
```

**Что значит каждый флаг:**

- `-p review` — активирует [profiles.review] из `~/.codex/config.toml`. Профиль задаёт `model = "gpt-5.5"`, `model_reasoning_effort = "high"`, и подавляет MCP_DOCKER (`mcp_servers = {}`).
- `-c sandbox_mode="danger-full-access"` — обходит BE-11 (`CreateProcessWithLogonW failed: 1326` на Windows npm install). **Profile-level `sandbox_mode` игнорируется** — нужен именно CLI override. Acceptable для review — read-only по природе.
- `review --commit <SHA>` — non-interactive review одного коммита (для smoke-test).
- `review --base <BRANCH>` — review всех коммитов от base до HEAD (для PR review).

### 8.4 Profile setup в `~/.codex/config.toml`

Если профиль ещё не настроен — добавь в `~/.codex/config.toml`:

```toml
# Pipeline profile — minimal config для предсказуемой review invocation.
# См. ADR 3.27 в .agents/PIPELINE_ADR.md.
[profiles.review]
model = "gpt-5.5"
model_reasoning_effort = "high"
sandbox_mode = "danger-full-access"   # ⚠️ игнорируется — дублируй через -c
mcp_servers = {}                      # подавляет MCP_DOCKER (table-replace)
```

**Quirk:** `sandbox_mode` в profile **не применяется** Codex loader'ом — всегда передавай через `-c sandbox_mode="danger-full-access"` в команде. Profile корректно применяет model, reasoning_effort и mcp_servers.

### 8.5 Dual-account fallback chain (опционально)

Если на одном email есть несколько workspace (personal Plus + work Business) — можно держать оба auth.json в backup и переключаться при quota exhaustion.

**Setup (один раз):**

1. Login в первый workspace через `codex login` (browser → выбрать Personal).
2. Backup: `Copy-Item ~/.codex/auth.json ~/.codex/auth-personal-plus.json`
3. `codex logout && codex login` (browser → выбрать work workspace).
4. Backup: `Copy-Item ~/.codex/auth.json ~/.codex/auth-work-business.json`

**Switch (any time):** dot-source `.claude/tools/codex-account-switch.ps1` и используй:

```powershell
. .\.claude\tools\codex-account-switch.ps1
Show-CodexAccount                # plan, account_id, expires
Use-CodexAccount personal-plus   # → копирует backup в active
Use-CodexAccount work-business   # → переключает на work
```

JWT decode внутри script показывает plan_type / account_id для подтверждения.

### 8.6 Troubleshooting

| Симптом | Причина | Лечение |
|---|---|---|
| `1326` / `CreateProcessWithLogonW failed` | Windows sandbox требует elevation, npm install не имеет hooks | `-c sandbox_mode="danger-full-access"` (всегда обязателен в pipeline вызовах) |
| `MCP_DOCKER/search_code started` зависает >5 мин | docker MCP gateway tool, медленный/требует interactive auth | Используй профиль `-p review` (mcp_servers = {} подавляет) |
| `The 'gpt-5.5' model requires a newer version of Codex` | Установлена старая Codex CLI (<= 0.118 alpha) | `npm install -g @openai/codex@latest` (требуется ≥ 0.128) |
| `Not logged in` после восстановления auth.json | active auth.json malformed / corrupted | `Use-CodexAccount <name>` восстанавливает из backup |
| `429 quota exceeded` на subscription path | Месячная subscription quota исчерпана | Switch второй аккаунт (`Use-CodexAccount`); если оба исчерпаны — fallback на Mode A-legacy (Platform API через openai-review.mjs §1-§7) |
| `oauth token exchange failed` | Истёк refresh token (~30 дней) | Re-login: `codex logout && codex login` (browser); restore backup после |
| Quota check | ChatGPT не предоставляет API для quota status | UI: ChatGPT Settings → Subscriptions → Usage |

### 8.7 Когда использовать какой аккаунт

- **Default = personal-plus** для большинства pipeline calls (дешевле, отдельный billing scope).
- **Switch на work-business при:** Plus quota exhausted; критичный PR где нужна максимальная headroom; тестирование на разных tier'ах.
- **Fallback на Mode A-legacy (Platform API):** оба subscription accounts exhausted; OAuth login broken; CI environment без browser.

> **Разведение терминов:** Mode A-legacy остаётся в mode chain скилла как автоматический технический режим деградации (скилл переключается сам при недоступности subscription). Это НЕ означает, что *настройка/использование Platform API key как операционного пути* — равноправный fallback: этот путь **emergency-only** (см. banner в шапке документа, строки 21-23, и operator decision 2026-05-17, bead U2-v43k).

### 8.8 Что **не** покрыто этим разделом

- Переписывание `external-review/SKILL.md` под новый backend — отдельный план (Beads U2-rhm).
- Pro tier upgrade ($100/мес, 10x bonus до 31.05.2026) — operator decision после measure quota burn на real PR.
- Cost optimization (diff-narrowing, reasoning_effort tuning, caching) — Plan B Phase 1-3, deferred.
- Internal review changes — pipeline orchestration, отдельный scope.

---

## 9. Legacy footnote: §1-§7 API key path

§1-§7 описывают legacy путь через OpenAI Platform API (pay-per-token). До 2026-05-05 это был primary mode. После validation §8 — это **технический режим деградации (Mode A-legacy)**:

> **Важно (разведение терминов):** Mode A-legacy присутствует в mode chain скилла `/external-review` как автоматический fallback-режим — скилл переходит в него сам при недоступности subscription path. Однако *настройка и операционное использование Platform API key как штатного пути* — **emergency-only**, не равноправный fallback (см. banner в шапке документа, строки 21-23, и operator decision 2026-05-17, bead U2-v43k). Месячный лимит Platform API сжигается за час; путь применяется только аварийно.


- **Когда использовать §1-§7:** ChatGPT subscription unavailable (quota exhausted в обоих аккаунтах + нет Pro upgrade); CI environment без browser для OAuth; диагностика проблем подписочного path.
- **Pipeline integration:** `openai-review.mjs --ping` остаётся в `external-review/SKILL.md` Шаг 1.4 как legacy ping; при недоступности subscription скилл переходит в Mode A-legacy (через openai-review.mjs).
- **Ротация ключей §5:** актуальна для legacy. Если §8 — primary, рекомендуется revoke API ключ при долгом неиспользовании (минимизировать blast radius утечки).

---

## Связанные файлы

- `.claude/tools/codex-account-switch.ps1` — dual-account swap script (§8.5)
- `.claude/hooks/codex-login.sh` — SessionStart-хук auto-login для legacy API key path (§3)
- `.claude/settings.json` — регистрация хука (секция `hooks.SessionStart`)
- `.claude/skills/external-review/SKILL.md` — скилл, использующий Codex CLI (текущая версия Mode A через openai-review.mjs; миграция на §8 — план U2-rhm)
- `.claude/tools/openai-review.mjs` — Mode A-legacy backend (Platform API, §1-§7 path)
- `.gitignore` — исключение `.claude/settings.local.json`
- `.agents/AGENT_ROLES.md` §3 — формат вердикта Reviewer
- `.agents/PIPELINE_ADR.md` ADR 3.27 — formal decision record для §8 (subscription path)
- `.agents/PIPELINE.md`, `.agents/AGENTIC_PIPELINE.md` — общая архитектура пайплайна
