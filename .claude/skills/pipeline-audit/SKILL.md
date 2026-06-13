---
name: pipeline-audit
description: Антивирус против drift между документами пайплайна. Проверяет 8 инвариантов (v3.3 + pre-merge landing v3.4), согласованность имён ролей/команд/аспектов, отсутствие противоречий с deny-rules. Запускай каждые 3-5 спринтов и обязательно перед изменением самого пайплайна.
user-invocable: true
---

# Pipeline Audit — проверка консистентности агентного пайплайна

Drift между нормативными документами — один из самых частых failure modes ИИ-пайплайна. Этот скилл собирает все источники истины и проверяет, что они говорят одно и то же.

## Когда запускать

- **Регулярно:** после каждых 3–5 завершённых спринтов.
- **Обязательно:** перед любым изменением самого пайплайна (новые скиллы, правки ролей, новые правила).
- **По требованию:** при подозрении на расхождение между документами (например, агент сослался на правило, которого нет).

## Цель

Получить отчёт `[OK / DRIFT DETECTED]` с конкретными расхождениями. Скилл **не исправляет** drift — только обнаруживает, чтобы оператор или PM приняли решение.

## Шаг 1: Сбор нормативных файлов

Собери все файлы, влияющие на поведение агентов:

```bash
# Документация ролей и пайплайна
ls -1 .agents/*.md

# Нативные агенты
ls -1 .claude/agents/*.md

# Скиллы
ls -1 .claude/skills/*/SKILL.md

# Правила
ls -1 .claude/rules/*.md

# Hooks: код и тесты hard gates (v3.3)
ls -1 .claude/hooks/*.py

# Конфиг harness
ls -1 .claude/settings.json
```

Сохрани список файлов как `AUDITED_FILES`.

## Шаг 2: Проверка 8 инвариантов (v3.3 + pre-merge landing v3.4)

Для каждого инварианта проверь, что он отражён хотя бы в одном из источников и нет противоречий:

| # | Инвариант | Где должен упоминаться |
|---|-----------|------------------------|
| 1 | Все review-pass публикуются в PR. Push, изменивший код после последнего review/verify-артефакта без нового отчёта = незавершённый цикл | `PM_ROLE.md`, `AGENT_ROLES.md`, `sprint-pr-cycle/SKILL.md`, `finalize-pr/SKILL.md` |
| 2 | Один владелец публикации (PM). Субагенты возвращают findings, PM публикует | `PM_ROLE.md`, `AGENT_ROLES.md`, `reviewer.md`, `sprint-pr-cycle/SKILL.md`, `external-review/SKILL.md` |
| 3 | Нет merge без fresh review на текущем commit. Review привязан к commit hash | `PM_ROLE.md`, `AGENT_ROLES.md`, `finalize-pr/SKILL.md` |
| 4 | Любое замечание имеет адрес: fix now / defer to Beads (с ID) / reject with rationale | `PM_ROLE.md`, `AGENT_ROLES.md`, `finalize-pr/SKILL.md` |
| 5 | Проверки централизованы через `/verify`. Один gate, одна точка изменения | `PM_ROLE.md`, `sprint-pr-cycle/SKILL.md`, `verify/SKILL.md` |
| 6 | PM не искажает findings ревьюверов. Агрегация — да, изменение смысла — нет | `AGENT_ROLES.md`, `PM_ROLE.md`, `reviewer.md`, `external-review/SKILL.md` |
| 7 | Merge — отдельное решение оператора. Агенты доводят до merge-ready, не мержат | `HOW_TO_USE.md`, `PM_ROLE.md`, `AGENT_ROLES.md`, `settings.json` (deny `gh pr merge`) |
| 8 | Sprint не создаёт отдельный `chore/landing-pr-N` PR (ранее — post-merge, до v3.4). Landing commit коммитится в ветку Sprint PR между первым `/finalize-pr APPROVED` и merge (pre-merge landing, v3.4+). Operator-facing документы должны учить ждать **второй** `/finalize-pr` для Sprint Final PR. | `PM_ROLE.md §2.5`, `sprint-pr-cycle/SKILL.md Фаза 4.5`, `finalize-pr/SKILL.md Dual-invocation`, `HOW_TO_USE.md` (operator decision logic), `PIPELINE.md` (flow diagram с landing шагом) |

Для каждого инварианта:
- Если упоминание отсутствует — `DRIFT: инвариант N не отражён в <ожидаемые файлы>`.
- Если есть противоречие (например, в одном файле сказано «PM публикует», в другом «Reviewer публикует») — `DRIFT: противоречие по инварианту N между <файл1> и <файл2>`.

## Шаг 3: Согласованность имён и понятий

Проверь точное совпадение терминов в `AUDITED_FILES`:

### 3.1 Имена ролей

Должны быть везде одинаковыми: `PM`, `Architect`, `Developer`, `Reviewer`, `Tester`. Без вариаций (`Project Manager` vs `PM` — допустимо в заголовке секции, но не как разные сущности).

`Planner` — субагент в `.claude/agents/planner.md` и ссылается из `Developer`/Memory Bank, но не самостоятельная роль в `AGENT_ROLES.md`. В audit не ищется как роль; проверь только что файл `.claude/agents/planner.md` существует и ссылки на него валидны в пункте 5 (Валидность ссылок).

### 3.2 Имена скиллов

Должны существовать как директории `.claude/skills/<name>/` И упоминаться через `/<name>` в документах:
- `/verify`
- `/sprint-pr-cycle`
- `/external-review`
- `/finalize-pr`
- `/pipeline-audit`

Если скилл упоминается, но директории нет — `DRIFT: скилл /<name> упомянут в <файл>, но директории не существует`.
Если директория есть, но нигде не упомянут — `DRIFT: скилл /<name> существует, но не упомянут в публичных документах`.

### 3.3 Аспекты ревью

Для `Standard`, `Critical`, `Sprint Final` — **ровно 4 аспекта** в порядке: Архитектура, Безопасность, Качество, Гигиена кода.

Для `Light` — **ровно 2 аспекта** в порядке: Архитектура, Гигиена кода (Light пропускает Безопасность и Качество по `AGENT_ROLES.md:183`).

Если в Standard/Critical/Sprint Final не 4 — `DRIFT: число аспектов не равно 4 для non-Light tier в <файл>`.
Если в Light не 2 или состав отличается от «Архитектура + Гигиена кода» — `DRIFT: Light tier должен содержать только Архитектура + Гигиена кода в <файл>`.

### 3.4 Tier-ы ревью

Везде должны быть: Light, Standard, Critical, Sprint Final.

### 3.5 Режимы external-review (v3.9+)

> **Backend evolution:** v3.6 — `openai-review.mjs` Platform API primary; v3.9 — Codex CLI ChatGPT subscription primary, `openai-review.mjs` сохраняется как Mode A-legacy fallback. Решение: ADR 3.27 + U2-rhm sprint.

Должны быть 5 активных режимов:

- **A** (primary, v3.9) — Codex CLI с ChatGPT subscription quota (`codex login status` → `Logged in using ChatGPT`, profile `[profiles.review]` в `~/.codex/config.toml`). Sequential две полноразмерные модели — gpt-5.5 через default profile + gpt-5.3-codex через `-c model="gpt-5.3-codex"` override.
- **A-hybrid** — Reviewer A через Codex CLI subscription (gpt-5.5), Reviewer B через Mode A-legacy (`openai-review.mjs --model gpt-5.3-codex`). Активируется автоматически когда gpt-5.3-codex недоступна на текущем subscription tier.
- **A-legacy** (v3.6 baseline) — Node.js native через [`.claude/tools/openai-review.mjs`](../../tools/openai-review.mjs), две полноразмерные модели параллельно (gpt-5.5 через `/v1/chat/completions` + gpt-5.3-codex через `/v1/responses`, обе с `reasoning effort: "high"`). Активируется когда Codex CLI subscription недоступен (logged out, quota exhaust на обоих accounts, OAuth broken).
- **C** — Claude adversarial degraded (два прохода субагента при недоступности всех Mode A вариантов).
- **D** — manual emergency (оператор прогоняет вручную через внешний инструмент).

Mode B (ChatGPT OAuth через Codex CLI subprocess `npx codex review`) **deprecated в v3.6** — не должен упоминаться как активный режим. Если встречается в скиллах/документах — `DRIFT: Mode B устарел, удалить или пометить как deprecated`.

> **Note:** v3.9 Mode A primary тоже использует `codex` CLI — но через **глобальный binary** (`npm install -g @openai/codex@latest`), не через `npx codex` subprocess. Семантика отличается: глобальный binary запускается напрямую с залогиненной ChatGPT subscription quota; `npx codex` (deprecated Mode B) — subprocess через npx с разным auth path. Pipeline-audit отличает эти два паттерна по invocation pattern (наличие `-p review` profile flag → v3.9 Mode A primary, OK; `npx @openai/codex` без profile → legacy Mode B pattern, DRIFT).

### 3.6 Инварианты Правки 1 v3.6 (Mode A baseline) + ADR 3.27 v3.9 (Mode A primary update)

- **I1.** Mode A primary в v3.9 = Codex CLI ChatGPT subscription через глобальный binary `codex -p review -c sandbox_mode="danger-full-access" review --commit "$HEAD_COMMIT"` (или `--base "origin/$BASE_BRANCH"`). Mode A-legacy = `openai-review.mjs` через Platform API. Mode B (`npx codex review` без profile) — deprecated, не должен встречаться как primary path в any active skill/doc. Если встречается — `DRIFT: deprecated Mode B path в <файл>`.
- **I3.** Ни один скилл не содержит хардкода `master`/`main` для base-ветки — только через `baseRefName` PR-метаданных.
- **I4.** Параметр `sandbox_mode=danger-full-access` имеет **conditional разрешение** (per ADR 3.27):
  - **Разрешён:** в Mode A primary invocation Codex CLI на Windows как BE-11 workaround (`CreateProcessWithLogonW failed: 1326` через npm install). Acceptable потому что review — read-only по природе. Должен передаваться через `-c sandbox_mode="danger-full-access"` (profile-level setting игнорируется Codex CLI 0.128.0).
  - **Запрещён:** в любом другом контексте — `npm`/`pip` install hooks, Developer-роли, hooks/scripts которые мутируют код или сетевые ресурсы. Если встречается вне Mode A primary Codex CLI invocation — `DRIFT: sandbox_mode="danger-full-access" вне разрешённого scope в <файл>`.

Если хотя бы один инвариант нарушен — `DRIFT: инвариант I<N> нарушен в <файл>`.

### 3.7 Имена веток

В документах не должно быть упоминаний удалённых, переименованных или несуществующих веток. Особое внимание — упоминания `master` vs `main`.

## Шаг 4: Соответствие deny-rules в settings.json

Прочитай `.claude/settings.json` блок `permissions.deny`. Для каждого запрета проверь, что в документации **нет инструкций нарушать его**:

| Deny-правило | Что НЕ должно быть в документах |
|--------------|----------------------------------|
| `Bash(git push * master)` / `* main` | Инструкции «git push origin master» в любом workflow |
| `Bash(gh pr merge *)` | Инструкции «после approval сделай gh pr merge» |
| `Bash(rm -rf *)` | Инструкции массового удаления через rm -rf |
| `Bash(git push --force *)` | Инструкции «если что — force push» |

Если найдено — `DRIFT: документ <файл> предлагает действие, заблокированное deny-правилом <правило>`.

## Шаг 5: Валидность ссылок между документами

Для каждой ссылки вида `.agents/X.md`, `.claude/agents/X.md`, `.claude/skills/X/SKILL.md`, `.claude/hooks/X.(md|py)`, `.memory-bank/X.md`, `.claude/rules/X.md` проверь:

```bash
# Извлечь все упомянутые пути
grep -rEo '\.(agents|claude/agents|claude/skills|claude/hooks|memory-bank|claude/rules)/[^ )"]*\.(md|json|py)' \
  .agents/ .claude/agents/ .claude/skills/ .claude/hooks/ .claude/rules/ .memory-bank/ 2>/dev/null | sort -u
```

Для каждого пути — проверь существование файла. Если файл не существует — `DRIFT: <файл-источник> ссылается на несуществующий <файл-цель>`.

## Шаг 6: Версии и даты

Сравни поля `Версия` и `Дата` в шапках документов в `.agents/`. Если за последние 3 спринта документ не обновлялся, но другие — да, это потенциальный сигнал устаревания (warning, не drift).

## Шаг 7: Отчёт

### Если нет drift

```
## Pipeline Audit: ✅ OK

Дата: <ISO дата>
Спринт: <номер из .memory-bank/activeContext.md>

Проверено файлов: N
Инвариантов: 8/8 ✅
Согласованность имён: ✅
Соответствие deny-rules: ✅
Валидность ссылок: ✅

— Pipeline Audit (Claude Opus 4.6)
```

### Если drift обнаружен

```
## Pipeline Audit: ⚠️ DRIFT DETECTED

Дата: <ISO дата>
Спринт: <номер из .memory-bank/activeContext.md>

### Расхождения

1. **Инвариант N не отражён** в <файл>:
   <конкретное место и что отсутствует>

2. **Противоречие** между <файл1> и <файл2>:
   <файл1>: «<цитата>»
   <файл2>: «<цитата>»

3. **Скилл /name** упомянут в <файл>, но директории не существует.

[...]

### Рекомендации

- Запустить PM с задачей: «устрани drift по отчёту pipeline-audit от <дата>»
- При невозможности устранить drift автоматически — эскалация оператору

— Pipeline Audit (Claude Opus 4.6)
```

## Шаг 8: Публикация отчёта

Если запущен в контексте PR (например, перед merge большого изменения пайплайна) — публикуй отчёт через `gh pr comment <PR_NUMBER>`. Иначе — выводи в чат оператору.

> ⚠️ **Пререквизит для публикации в PR:** PreToolUse hook `Bash(gh pr comment*)` из `.claude/settings.json` блокирует команду, если PR не найден для **локальной текущей ветки** (`git branch --show-current`). Если audit запускают не с head-ветки PR — `gh pr comment <PR_NUMBER>` будет заблокирован как «PR не найден для ветки».
>
> **Перед публикацией обязательно выполни:**
> ```bash
> gh pr checkout <PR_NUMBER>
> ```
> Это переключит локально на head-ветку PR, и hook разрешит публикацию. Если `gh pr checkout` невозможен (нет прав, конфликт, detached HEAD) — **не пытайся** публиковать через `gh pr comment`, вместо этого выведи отчёт в чат оператору.

> ⛔ Pipeline Audit **не пишет в файлы** — он только обнаруживает drift. Любые правки делает PM/Developer как отдельная задача.

## Ограничения

- Скилл проверяет **тексты документов**, а не реальное поведение агентов в runtime. Согласованность документации — необходимое, но не достаточное условие.
- Не проверяет качество формулировок, только структурную согласованность.
- При первом запуске после крупного изменения пайплайна возможны false-positive — внимательно проверь каждый пункт.
