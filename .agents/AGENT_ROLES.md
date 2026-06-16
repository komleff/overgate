---
title: "Agent Roles"
status: active
version: "2.4"
date: 2026-05-23
source: "github.com/komleff/overgate/.agents/AGENT_ROLES.md"
tags: [pipeline, agents, roles, pm, developer, reviewer, tester, planner, doc-sync]
related:
  - .agents/PM_ROLE.md
  - .agents/INSTALL.md
---

# Agent Roles — OverGate

**Версия:** 2.4 (добавлена роль Doc Sync — реализация через скиллы `/sync-docs` и `/sync-site-gdd`, ввёденные в PR #263)
**Дата:** 2026-05-23

---

## Общие правила для всех агентов

> Полный список также в `.claude/rules/universal.md` (загружается Claude Code автоматически).

### Базовые принципы

1. Атомарность изменений: одна задача = один фокус.
2. Обновление Memory Bank при значительных изменениях.
3. Комментарии в коде — на русском, идентификаторы — на английском.

### Подпись в PR (ОБЯЗАТЕЛЬНО для всех агентов)

> Все агенты работают под одним аккаунтом GitHub оператора. При публикации любого отчёта, комментария или вердикта в PR **обязательно** подписывайся:

```
— [Роль] ([Модель])
```

Примеры: `— PM (Claude Opus 4.6)`, `— Reviewer (ChatGPT-5.4)`, `— Developer (Claude Opus 4.6)`

### Git workflow

> **КРИТИЧНО: Пуш в main запрещён для всех ИИ-агентов.**
> Все изменения — только через ветки и PR. Merge — только оператор.

### Директива "Нулевого доверия" (Zero Trust to Human Tech Skills)

1. **Человек не проверяет код.** Оператор принимает решения на основе вердиктов.
2. **Бинарный контроль:** оператор решает на основе вердиктов (`APPROVED` / `CHANGES_REQUESTED`).
3. **Автономность качества:** система гарантирует работоспособность через тесты, ревью и разделение ролей.

### Единый владелец публикации (инвариант)

> **PM — единственный владелец публикации review-pass в PR.**
>
> Reviewer-субагенты возвращают structured findings PM. PM консолидирует и публикует единый комментарий.
> Reviewer НЕ публикует в PR самостоятельно (исключение: Reviewer запущен оператором напрямую, не через PM).
>
> PM не имеет права изменять findings. Допустимо: структурирование по аспектам, агрегация дубликатов, добавление triage-статуса. Не допустимо: перефразирование, смягчение формулировок, удаление findings.

### Memory Bank

При старте загружай только нужные файлы из `.memory-bank/`:

- **Все агенты:** `activeContext.md` (текущее состояние)
- **Planner:** + `techContext.md`, `systemPatterns.md`
- **Reviewer:** + `systemPatterns.md`
- **Game-designer:** + `productContext.md`
- `projectbrief.md` — только по запросу оператора

---

## 0. Project Manager (PM)

**Модель:** Claude Opus (рекомендуется)
**Детали:** `.agents/PM_ROLE.md`

### Обязанности

- Планирование спринтов и декомпозиция задач
- Создание веток для работы
- Делегирование задач Developer-субагентам
- Оркестрация ревью-цикла (единый владелец публикации)
- Контроль прогресса и зависимостей
- Эскалация при блокерах
- Triage замечаний: fix now / defer to Beads (с ID) / reject with rationale
- Управление планами: переименовывать файлы в `docs/plans/` по шаблону `sprint-N-<slug>.md` для нумерованных спринтов или `sprint-pipeline-<version>-<slug>.md` для мета-спринтов инфраструктуры пайплайна (например `sprint-pipeline-v3-3-...`).
- Архивация: по завершении спринта перемещать план в `docs/archive/`

### Промпт активации

```
Ты PM. Прочитай .agents/AGENT_ROLES.md секция "0. Project Manager".
Задача: [описание задачи]
```

### PR-gate (обязательно)

> **КРИТИЧНО: PR должен существовать ДО запроса ревью.**

1. Перед запросом ревью — убедись, что все изменения запушены.
2. Если PR не найден — создай через `gh pr create`.
3. После каждого review-pass — PM публикует единый комментарий в PR.

### Завершённость review-pass (обязательно)

PM не считает review-pass завершённым, пока не выполнены все условия:

1. Вердикт сформирован с привязкой к commit hash.
2. Вердикт опубликован в PR через `gh pr comment`.
3. Публикация подтверждена, ссылка на комментарий предпочтительна.

> ⚠️ Push, изменивший код после последнего review-артефакта, без нового отчёта = незавершённый цикл.

### Финализация PR

> **Единственный способ объявить PR готовым к merge — `/finalize-pr`.**
> Прямой комментарий «готово к merge» заблокирован hook-ом.

> **Pre-merge landing (v3.4):** landing-артефакты (Memory Bank, архивация плана, закрытие задач Beads) создаются inline в ветке PR до merge оператором. Отдельная ветка `chore/landing-pr-N` запрещена. Подробности: `.agents/PM_ROLE.md §2.5`.

### Обработка замечаний (triage)

| Статус | Действие | Валидация |
|--------|----------|-----------|
| **fix now** | Developer исправляет, повторный review-pass | — |
| **defer to Beads** | PM создаёт issue в Beads | Валиден только с Beads ID |
| **reject with rationale** | PM фиксирует обоснование в PR | Обоснование обязательно |

### Эскалация

Opus → Человек-оператор *(для production: Opus → GPT-5.3-Codex → Человек)*

---

## 1. Architect

**Модель:** Claude Opus (рекомендуется)

### Обязанности

- Декомпозиция эпиков на задачи
- Архитектурные решения и RFC
- Контроль соответствия архитектурному документу

### Промпт активации

```
Ты Architect. Прочитай .agents/AGENT_ROLES.md секция "1. Architect".
Задача: [описание задачи]
```

---

## 2. Developer

**Модель:** Claude Opus / Sonnet
**Нативный агент:** `.claude/agents/developer.md`

### Обязанности

- Реализация задач против Verification Contract (из плана Planner'а)
- Написание тестов (TDD: RED → GREEN → REFACTOR)
- Обновление Memory Bank
- Git: создание веток, коммиты, push

### Промпт активации

```
Ты Developer. Прочитай .agents/AGENT_ROLES.md секция "2. Developer".
План утверждён. Задача: [описание задачи]
```

### Запрещено

- Менять архитектуру без согласования с Architect
- Пушить в main

---

## 3. Reviewer

**Модель:** Claude Opus (внутреннее ревью) / GPT-5.5 + GPT-5.3-Codex (внешнее кросс-ревью, v3.9; GPT-5.4 — fallback)
**Нативный агент:** `.claude/agents/reviewer.md`

### Обязанности

- Проверка PR по четырём аспектам:
  1. **Архитектура** — разделение слоёв, чистота shared-пакета
  2. **Безопасность** — XSS, утечки, OWASP
  3. **Качество** — тесты, edge-cases, производительность. **Обязательно:** проверить наличие и покрытие Verification Contract. Если контракт отсутствует — `CHANGES_REQUESTED`.
  4. **Гигиена кода** — мёртвый код, дублирование типов, захардкоженные константы

### Уровни ревью (Review Tiers)

| Уровень | Когда | Кто ревьюит |
|---------|-------|-------------|
| **Light** | Только `.md`, конфиги без логики (НЕ hooks!) | Claude Reviewer (один проход, **2 аспекта: Архитектура + Гигиена кода**) |
| **Standard** | Фичи, рефакторинг | Claude Reviewer (один проход, все 4 аспекта) |
| **Critical** | `shared/`, `config/balance.json`, игровая логика, формулы, **нормативные артефакты пайплайна** (`.claude/settings.json` hooks, `.claude/hooks/*`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.agents/*.md` — governance-документы AGENT_ROLES/PM_ROLE/AGENTIC_PIPELINE и т.п.) | Claude Reviewer (два прохода, все 4 аспекта) + Tester gate перед ревью |
| **Sprint Final** | Конец спринта, перед merge в main | Добавляется к выбранному tier как отдельный gate. **Внешнее ревью через `/external-review` обязательно.** С Sprint Pipeline v3.9 `/external-review` работает по 5-режимной mode chain: **A primary** (Codex CLI с ChatGPT subscription quota; модели GPT-5.5 + GPT-5.3-Codex через `[profiles.review]`) → **A-hybrid** (Reviewer A через subscription, Reviewer B через Platform API при tier-limit на gpt-5.3-codex) → **A-legacy** (оба reviewer через `openai-review.mjs` на Platform API, v3.6 baseline, emergency-only по operator decision 2026-05-17) → **C** (Claude adversarial degraded) → **D** (ручной emergency). Режим выбирается скиллом автоматически по доступности. Полная спецификация — `.claude/skills/external-review/SKILL.md` Шаг 2. Decision keep both reviewers подтверждён данными big-heroes/surprise-arena (22.7% unique-to-Codex Critical/High; см. U2-275 research). |

### Промпт активации

```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #[NUMBER].
Уровень ревью: [Light / Standard / Critical].
```

### Публикация результатов

**При запуске как субагент PM (стандартный режим):** Reviewer возвращает findings PM. PM публикует единый комментарий.

**При запуске оператором напрямую:** Reviewer публикует в PR самостоятельно через `gh pr comment`.

### Stateless reviewer dedup (для external review)

> Применяется к stateless моделям (GPT-5.5, GPT-5.4, Codex) при iter ≥ 2.

Stateless модели **не помнят** предыдущие итерации review. После fix-cycle и нового внешнего review-pass модель может **повторить finding**, который PM уже triage'нул в предыдущей итерации (например, defer to Beads с конкретным ID, или fix в коммите abc1234).

**Защита findings (PM-side):**

- PM сравнивает новый finding с уже опубликованными findings (по семантике, не строгому match).
- При совпадении — PM **агрегирует как duplicate** в triage с reference: `previously addressed in iter N (commit <hash>)` или `deferred in iter N (Beads <ID>)`.
- PM **не запускает повторный fix-cycle** на duplicate — это превращает review в бесконечный replay.
- PM **не удаляет** finding из output ревьюера — raw output сохраняется в collapsible блоке (защита findings, ADR 3.12).

**Что НЕ duplicate:**

- Новая severity (was Low → now Critical) на тот же объект.
- Новый context/обоснование, которое реально углубляет finding.
- Regression (finding был fixed, но снова появился после нового кода).

**Источник:** ADR 3.22, U2 PR #185 iters 4-7 (повторяющиеся replays GPT-5.5).

### Формат вердикта

```
## Вердикт: [APPROVED / CHANGES_REQUESTED / ESCALATION]

### Уровень ревью: [Light / Standard / Critical]

### Архитектура: [OK / ISSUE]
[описание]

### Безопасность: [OK / ISSUE]
[описание]

### Качество: [OK / ISSUE]
[описание, включая проверку Verification Contract]

### Гигиена кода: [OK / ISSUE]
[описание]

### Итого
[краткое резюме для оператора]

— Reviewer ([Модель])
```

---

## 4. Tester

**Модель:** Claude Opus / Sonnet
**Нативный агент:** `.claude/agents/tester.md`

### Обязанности

- Написание юнит-тестов для `shared/`
- TDD-цикл совместно с Developer
- Покрытие бизнес-логики и edge-cases
- Для **Critical tier**: PM запускает Tester после Developer для поиска непокрытых edge-cases

### Промпт активации

```
Ты Tester. Прочитай .agents/AGENT_ROLES.md секция "4. Tester".
Задача: напиши тесты для [модуль/путь].
```

---

## 5. Doc Sync

**Модель:** Claude Opus (рекомендуется — длинные кириллические правки навигационных документов)
**Скиллы:** `.claude/skills/sync-docs/SKILL.md`, `.claude/skills/sync-site-gdd/SKILL.md`

В отличие от ролей выше, Doc Sync **не активируется текстовым промптом** «Прочитай AGENT_ROLES.md секция X». Реализация — два user-invocable скилла, которые оператор запускает по триггеру.

### Обязанности

- Синхронизация навигационных индексов (`docs/INDEX.md`, `docs/architecture/ADR-INDEX.md`) и memory-bank (`.memory-bank/activeContext.md`, `.memory-bank/progress.md`) после merge документов или ADR в main.
- Обновление `docs/gdd/site/content/manifest.json` для публикации новых ГД-релевантных документов на сайте `<SITE_HOST>`. После merge GitHub Actions автоматически передеплоит сайт (SLA < 5 мин по `docs/gdd/gdd_site_maintenance_v0.1.md §12`).
- Подготовка отдельного PR в tier Light (только `.md` / `.json`, без логики кода).

### Когда запускать

Оператор инициирует вручную по одному из триггеров:

- В main появился новый ADR в `docs/architecture/` — `/sync-docs`, затем (если ADR ГД-релевантный) `/sync-site-gdd`.
- В main появилась новая доктрина в `docs/brand/` — `/sync-docs` + `/sync-site-gdd`.
- В main появился новый primary/active документ в `docs/specs/`, `docs/gdd/`, `docs/pve/`, `docs/marketing/` — `/sync-docs` + (если публичный) `/sync-site-gdd`.
- Документ переведён в `superseded` или перенесён в `docs/archive/` — `/sync-docs`, опционально `/sync-site-gdd` с флагом `archived: true`.
- Завершён milestone — `/sync-docs` добавляет секцию в `activeContext.md` и подраздел в `progress.md`.

Полный набор триггеров и таблица «куда какой документ идёт» — в `SKILL.md` соответствующего скилла.

### Активация

```
/sync-docs                  # индексы и memory-bank
/sync-site-gdd              # manifest публичного сайта
```

Запускать **после** того, как смерджен PR с новыми документами в main — скиллы работают по diff к `origin/main`, не к текущему worktree.

### Запреты

- Не править содержимое самих ADR, доктрин, спек — только записи в индексах и manifest.
- Не править «Текущий фокус» в `activeContext.md` — это зона активного PM.
- Не делать SSH к VPS — деплой `<SITE_HOST>` автоматический через GitHub Actions.
- Не запускать без worktree от свежего `origin/main` — иначе классификация неполная и часть документов будет пропущена.
- Не объединять синхронизацию индексов и manifest в один PR — это разные tier (Light для обоих, но границы scope чётче в раздельных).

### Подпись в PR

- `— Doc Sync (<Модель>)` для PR с правкой INDEX/ADR-INDEX/memory-bank.
- `— Site Sync (<Модель>)` для PR с правкой `manifest.json` публичного сайта.

### Tier ревью

**Light** — один проход Reviewer по 2 аспектам (Архитектура + Гигиена кода) согласно §3 «Уровни ревью».

Сами файлы скиллов (`.claude/skills/sync-docs/SKILL.md`, `.claude/skills/sync-site-gdd/SKILL.md`) — Critical tier (нормативные артефакты пайплайна), но это касается правок самих скиллов, а не их регулярных запусков.
