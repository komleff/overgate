# `.claude/tools/` — инструменты пайплайна

## Назначение

Каталог содержит Node.js native-инструменты, вызываемые скиллами Claude Code.

Основной инструмент — `openai-review.mjs`: native-скрипт внешнего ревью для Mode A пайплайна Sprint Final. Пришёл на смену подпроцессу `npx @openai/codex review` в рамках Sprint Pipeline v3.6 (Правка 1).

**Когда вызывается:**
- Скиллом `external-review` на шаге 3.1 (Mode A) — для публикации внешнего ревью в PR от двух полноразмерных моделей. Текущий primary: `gpt-5.5` (reasoning) + `gpt-5.3-codex` (code). `gpt-5.4` доступен как fallback (если `gpt-5.5` API ещё не доступен в данном проекте).
- Скиллом `external-review` на шаге 1.4 (pre-flight API-key validation, `--ping`) — для раннего выхода при невалидном/revoke'нутом ключе (Правка 5).

**Почему не Codex CLI:**
- BE-11 Windows sandbox (`CreateProcessWithLogonW failed: 1326`) устраняется по определению — Node.js не упирается в Win32 subprocess-limit.
- Никаких `sandbox_mode=danger-full-access` — запрещено планом v3.6 (инвариант I4).
- Переносимо между машинами копированием каталога + `npm install`.

## Установка на чистой машине

Требования:
- Node.js ≥ 18.17.0 (минимальная версия, где `parseArgs` из `node:util` стабилен; согласовано с `package.json#engines.node`).
- `$OPENAI_API_KEY` в окружении (кроме `--help`).

**Первая установка (с разрешением версий):**
```bash
cd .claude/tools
npm install
```

**Воспроизводимая установка по `package-lock.json`:**
```bash
cd .claude/tools
npm ci
```

Версия SDK `openai@6.34.0` закреплена без `^` (см. Риск 1 в `docs/plans/sprint-pipeline-v3-6-mode-a-native.md`). Lockfile `package-lock.json` — локальный для этого каталога, не затрагивает root workspaces проекта (`shared/` и `client/`).

**Почему 6.x:** Responses API (`client.responses.create`) появился только в SDK ≥4.80, стабилизирован в 5.x. 6.34.0 — текущий stable, поддерживает оба нужных endpoint'а (`chat.completions` и `responses`). Обновление SDK в будущем — отдельная задача с явной правкой плана.

## Использование

### `--help`

Показать справку без обращения к сети.
```bash
node .claude/tools/openai-review.mjs --help
```

### `--ping`

Проверить валидность `$OPENAI_API_KEY` через `client.models.list()` (~20 ms).

```bash
node .claude/tools/openai-review.mjs --ping
```

Exit 0 при 200 OK, exit 1 при любой ошибке. Класс ошибки печатается на stderr.

### `--model <id> --base <baseRefName>`

Запустить ревью текущего HEAD против `origin/<baseRefName>`. `<baseRefName>` — значение `baseRefName` из PR-метаданных, не захардкоженное имя.

```bash
BASE_REF="$(gh pr view <PR_NUMBER> --json baseRefName --jq '.baseRefName')"
node .claude/tools/openai-review.mjs --model gpt-5.4 --base "$BASE_REF"
node .claude/tools/openai-review.mjs --model gpt-5.3-codex --base "$BASE_REF"
```

Скрипт возвращает **готовый markdown** в формате `## Вердикт: ... / ### Архитектура: ... / ...` — system prompt задаёт жёсткий шаблон с 4 аспектами и enum-вердиктом (`APPROVED | CHANGES_REQUESTED | ESCALATION`). PM **не маппит** вывод вручную — публикует raw в collapsible-блок и переносит консолидацию в свой комментарий по шаблону из `external-review/SKILL.md` Шаг 5.3.

## Runtime allowlist

Три модели, две архитектуры — adversarial diversity через специализацию, не через размерность (см. Err5 плана). После Step 7.5 Plan A добавлена `gpt-5.5` как стратегический primary; `gpt-5.4` остался как fallback.

| Модель | Endpoint | SDK-метод | Request shape | Роль |
|---|---|---|---|---|
| `gpt-5.5` | `/v1/chat/completions` | `client.chat.completions.create(...)` | `{ reasoning_effort: "high" }` | primary (reasoning) |
| `gpt-5.4` | `/v1/chat/completions` | `client.chat.completions.create(...)` | `{ reasoning_effort: "high" }` | fallback для 5.5 |
| `gpt-5.3-codex` | `/v1/responses` | `client.responses.create(...)` | `{ reasoning: { effort: "high" } }` | code-специализация |

**Важно:** это не два формата одного поля, а два разных request shape для двух разных endpoint'ов. Shape выбирается строго по `endpoint` из метаданных allowlist.

Попытка вызвать модель вне runtime-allowlist завершается ранним exit 2 со списком разрешённых моделей и ссылкой на справочные таблицы Err5. Расширение allowlist — отдельная задача, требующая согласованной правки плана.

## Диагностика

### Exit codes

| Код | Значение | Что делать |
|---|---|---|
| 0 | OK | — |
| 1 | Runtime-ошибка: локальная или API/сеть | Проверить stderr; см. разделы «Ошибки с exit 1» ниже |
| 2 | Ошибка валидации аргументов или модель вне allowlist | Проверить имя модели и аргументы; см. `--help` |
| 3 | Нет diff'а против base (nothing to review) | Нормальный сигнал — нечего ревьюить |

### Ошибки с exit 1

Код 1 покрывает любые runtime-ошибки, которые не относятся к валидации аргументов (2) и не означают штатное отсутствие diff'а (3). Автоматизации следует читать stderr для различения причин.

**Локальные причины (до отправки запроса):**
- `$OPENAI_API_KEY` не задан или недоступен в окружении.
- `git fetch` / `git diff` завершились с ошибкой (нет upstream `origin`, ветка не существует в remote, detached HEAD без upstream).
- Diff превышает `maxBuffer` (16 MB) — сообщение: «git ... вернул слишком большой вывод».
- Пустой ответ от модели (невалидный JSON, пустое поле content).

**Ошибки API / сети** — скрипт классифицирует ошибку по HTTP-статусу и печатает actionable-сообщение на stderr:

- **401 / 403** — невалидный/revoke'нутый ключ. Инструкция по ротации: [`.agents/CODEX_AUTH.md`](../../.agents/CODEX_AUTH.md) §5 «Ротация ключа».
- **429** — rate limit / quota. Подождать, уменьшить частоту запросов, проверить лимиты в OpenAI Project.
- **Network error / timeout** — проверить соединение и прокси.

Безопасность:
- API-ключ только из `$OPENAI_API_KEY`, никогда не в аргументах и не в логах.
- `--base` валидируется через `git check-ref-format --branch` — те же правила, что у самого Git (запреты `..`, trailing `/`, управляющие символы и т.п.); отдельно блокируется префикс `-`, чтобы имя не попало в git как опция.
- Для `/v1/responses` trusted system prompt передаётся через параметр `instructions` отдельно от untrusted `input` — изоляция инструкций защищает от prompt injection из diff.

### Smoke-тест

`smoke-test.mjs` проверяет exit codes и вывод без обращения к сети (не требует `$OPENAI_API_KEY`):

```bash
node .claude/tools/smoke-test.mjs
```

Выходит с exit 0 если все кейсы зелёные, иначе 1.

## Ссылки

- План: `docs/plans/sprint-pipeline-v3-6-mode-a-native.md` _(документ не сохранён в репозитории)_ — секция «Правка 1» и Err5 Verification Contract.
- Ротация ключа: [`.agents/CODEX_AUTH.md`](../../.agents/CODEX_AUTH.md) §5.
- Скилл-потребитель: [`.claude/skills/external-review/SKILL.md`](../skills/external-review/SKILL.md).
