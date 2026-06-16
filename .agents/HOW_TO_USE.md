---
title: "Pipeline operator guide"
status: active
version: "2.4"
date: 2026-05-23
source: "github.com/komleff/overgate/.agents/HOW_TO_USE.md"
tags: [pipeline, operator, guide, sprint, finalize-pr, install, doc-sync]
related:
  - .agents/PIPELINE.md
  - .agents/PM_ROLE.md
  - .agents/INSTALL.md
---

# Как пользоваться пайплайном

**Для:** оператора (менеджера), который не читает код
**Версия:** 2.4 (добавлен блок про роль Doc Sync и скиллы `/sync-docs` + `/sync-site-gdd`)
**Обновлён:** 2026-05-23

---

## 1. Быстрый старт

### Что нужно

- Терминал или VS Code с Claude Code
- Открыта папка целевого проекта
- Доступ к GitHub (для PR и merge)

### Первый запуск

1. Открой Claude Code в папке проекта
2. Напиши в чат:

   ```
   Ты PM. Прочитай .agents/AGENT_ROLES.md секция "0. Project Manager".
   Задача: покажи текущее состояние проекта
   ```

3. Claude прочитает Memory Bank и расскажет, что сейчас происходит

---

## 1.5 Установка пайплайна в новый проект (один раз на проект)

> Это особый случай: ты впервые ставишь OverGate-пайплайн в новый проект. Полная инструкция — `.agents/INSTALL.md` (короткая для оператора + детальная для AI-агента).

### Промпт активации (копируй целиком)

> **Source of truth:** `.agents/INSTALL.md` §A.2. Эта копия — операторская шпаргалка для quick reference; при расхождении доверяй INSTALL.md §A.2.

```
Ты — установщик OverGate-пайплайна. Прочитай .agents/INSTALL.md секцию B
(полную инструкцию для AI-агента) в reference-репозитории
[путь к reference, например ~/GitHub/overgate/.agents/INSTALL.md].

Контекст текущего проекта:
- Имя проекта: [например, my-new-game]
- GitHub-репо: [https://github.com/user/repo]
- Стек: [например, Node.js + React, или .NET + Unity]
- Reference-репозиторий: [например, ~/GitHub/overgate/]
- Префикс Beads: [например, mng-* для my-new-game]

Действуй автономно по шагам a-j. Останавливайся только на:
1. Шаг f (Bootstrap PR) — мне нужно подтвердить структуру PR
2. Шаг j (финальный merge) — мерджу я

После каждого шага кратко отчитывайся, что сделал. На спорных решениях
(adapt vs copy-as-is) — выбирай consistency с reference и продолжай.
```

### Что ты контролируешь

- Шаг f (Bootstrap PR) — подтверждение структуры PR.
- Шаг j (final merge) — **только ты** мержишь после `## ✅ Готов к merge` без warning.

Всё остальное — автономно. См. `.agents/INSTALL.md §A.3` для полной таблицы control points.

### Когда установка завершена

См. `.agents/INSTALL.md §D` — критерии завершения. После merge Bootstrap PR в main → переходи на §2 ниже (обычные спринты).

---

## 2. Как запустить спринт

### Активация PM

```
Ты PM. Прочитай .agents/AGENT_ROLES.md секция "0. Project Manager".
Задача: спланируй Sprint N — [название/цель спринта]
```

PM сделает:

- Прочитает текущее состояние (`activeContext.md`)
- Создаст задачи в Beads (`bd create`)
- Определит приоритеты и зависимости
- Создаст Verification Contract (критерии приёмки, edge-cases, список тестов)
- Предложит план спринта

### После планирования

Скажи PM:

```
Начинай реализацию. Делегируй задачи Developer-субагентам.
```

---

## 3. Скиллы (автоматизированные команды)

### `/verify` — healthcheck проекта

Запускает сборку и тесты. Единая точка проверки.

```
/verify
```

### `/sprint-pr-cycle` — полный ревью-цикл

После завершения кодирования спринта. Проводит через все шаги: verify → PR → внутреннее ревью (4 аспекта) → фиксы → внешнее ревью.

```
/sprint-pr-cycle
```

### `/external-review <PR_NUMBER>` — кросс-модельное ревью

Запускает внешних ревьюверов (GPT-5.5 + GPT-5.3-Codex; GPT-5.4 — fallback) через Codex CLI. Автоматически выбирает режим из 5-режимной mode chain v3.9 (`A primary` / `A-hybrid` / `A-legacy` / `C` / `D`) по доступности subscription/Platform API.

```
/external-review 42
```

### `/finalize-pr <PR_NUMBER>` — финализация PR

**Единственный способ объявить PR готовым к merge.** Автоматически проверяет: verify на текущем commit, review привязан к этому commit, external review для Sprint Final, статус всех замечаний.

```
/finalize-pr 42
```

Аварийный режим (только по твоей явной команде, при сбое скилла):

```
/finalize-pr 42 --force
```

### `/pipeline-audit` — проверка консистентности

Проверяет, нет ли расхождений между документами пайплайна. Запускай после каждых 3–5 спринтов.

```
/pipeline-audit
```

### `/sync-docs` — синхронизация навигации после merge документов

Когда в main сливается PR с новыми ADR, доктринами, спеками или гейм-дизайн-документами — скилл одним PR подтягивает `docs/INDEX.md`, `docs/architecture/ADR-INDEX.md` и memory-bank к актуальному состоянию. Tier Light, отдельный PR.

```
/sync-docs
```

Не трогает содержимое самих документов и «Текущий фокус» в activeContext.md — только записи в индексах. Полные триггеры — `.agents/AGENT_ROLES.md §5 «Doc Sync»` или `.claude/skills/sync-docs/SKILL.md`.

### `/sync-site-gdd` — публикация документов на публичный сайт (опционально)

> ⚙️ Опциональный U2-специфичный site-sync скилл. Если у проекта нет публичного сайта документации — удали скилл; иначе адаптируй пути и manifest под свой сайт.

После merge новых ГД-релевантных документов (ADR, доктрины бренда, GDD/PvE/audit) — скилл добавляет их в manifest сайта (путь см. в SKILL.md, плейсхолдер `<SITE_MANIFEST>`) отдельным PR. После merge GitHub Actions автоматически передеплоит публичный сайт за < 5 мин. SSH к VPS не требуется.

```
/sync-site-gdd
```

Обычно запускается **после** `/sync-docs` и **только** если в порции есть ГД-релевантные документы (технические спеки, research, infrastructure — на публичный сайт не идут). Таблица соответствия — в `.claude/skills/sync-site-gdd/SKILL.md`.

---

## 4. Как принимать решение о merge

### Что смотреть

Только финальный комментарий от `/finalize-pr` в PR:

```
✅ Готов к merge
Commit: abc1234
Verify: ✅
Internal review: ✅ (commit abc1234)
External review: ✅ (commit abc1234)
```

**С v3.4 (pre-merge landing) `/finalize-pr` для Sprint Final PR публикует комментарий `## ✅ Готов к merge` ДВАЖДЫ:**

1. **Первый комментарий** содержит строку `⏳ Pre-merge landing commit впереди — жди второй /finalize-pr, не мерджи сейчас.` Это промежуточная точка: PM сейчас сделает landing commit (activeContext.md, plan archive, bd close, memory entry) в эту же ветку PR.
2. **Второй комментарий** (после landing commit, новый HEAD) — без warning. Это и есть единственный сигнал к merge.

**Правило:** мерджишь только когда видишь `✅ Готов к merge` **без** строки `⏳ Pre-merge landing commit впереди` (полный префикс warning из первого комментария). Если warning присутствует — жди следующий `/finalize-pr` от PM. Ты не читаешь код, только вердикты.

Для tier ≠ Sprint Final (Light/Standard/Critical без `Tier: Sprint Final` в body) `/finalize-pr` вызывается один раз — мержи сразу после `## ✅ Готов к merge`.

### Что делать при проблемах

| Ситуация | Действие |
|----------|----------|
| `CHANGES_REQUESTED` | Скажи PM: «устрани замечания» |
| Аспект «не проверен» | PM запустит повторный `/external-review` |
| `⚠️ Force finalize` | Прочитай причину, реши сам — мержить или нет |
| `⚠️ Degraded mode` | Ревью прошло не в полном объёме — решай по ситуации |

---

## 5. Шаблоны вызова агентов

> Копируй нужный шаблон в чат и подставляй свои значения в `[скобках]`.

### PM — планирование и оркестрация

```
Ты PM. Прочитай .agents/AGENT_ROLES.md секция "0. Project Manager".
Задача: [описание задачи]
```

**Примеры задач:** спланируй Sprint 2 — BattleSystem; покажи текущее состояние; устрани все CHANGES_REQUESTED; начинай реализацию, делегируй задачи Developer-субагентам.

### Architect — архитектура и декомпозиция

```
Ты Architect. Прочитай .agents/AGENT_ROLES.md секция "1. Architect".
Задача: [описание задачи]
```

**Примеры задач:** декомпозируй эпик «Инвентарь» на задачи; проверь соответствие текущего кода архитектурному документу.

### Developer — реализация

```
Ты Developer. Прочитай .agents/AGENT_ROLES.md секция "2. Developer".
План утверждён. Задача: [описание задачи]
```

**Примеры задач:** реализуй BattleScene по плану sprint-2; исправь баг в SceneManager.

### Reviewer — ревью PR

```
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #[NUMBER].
Уровень ревью: [Light / Standard / Critical].
```

**Уровни:** Light — доки/конфиги; Standard — фичи; Critical — shared/баланс/формулы.

### Tester — написание тестов

```
Ты Tester. Прочитай .agents/AGENT_ROLES.md секция "4. Tester".
Задача: напиши тесты для [модуль/путь].
```

**Примеры задач:** напиши тесты для shared/src/formulas; покрой edge-cases для BattleSystem.

---

## 6. Частые команды (краткая шпаргалка)

| Что нужно | Что сказать / сделать |
|-----------|----------------------|
| Начать спринт | PM → «спланируй Sprint N — [цель]» |
| Запустить реализацию | PM → «начинай реализацию, делегируй Developer-субагентам» |
| Быстрая проверка | `/verify` |
| Ревью-цикл (авто) | `/sprint-pr-cycle` |
| Внешнее ревью вручную | `/external-review <PR_NUMBER>` |
| Финализация PR | `/finalize-pr <PR_NUMBER>` |
| Аудит пайплайна | `/pipeline-audit` |
| Ревью PR вручную | Reviewer → «проверь PR #N, уровень: Standard» |
| Исправить замечания | PM → «устрани все CHANGES_REQUESTED» |
| Архитектурный вопрос | Architect → «декомпозируй [эпик]» |
| Написать тесты | Tester → «напиши тесты для [модуль]» |
| Показать статус | PM → «покажи текущее состояние» |
| Обновить индексы после merge | `/sync-docs` |
| Опубликовать новые документы на сайте | `/sync-site-gdd` |

---

## 7. Чего не нужно делать

- **Не читай код.** Доверяй вердиктам.
- **Не мержи без `/finalize-pr`.** Даже если PM говорит «готово» в чате.
- **Не запускай `--force` без причины.** Только при реальном сбое скилла.
- **Не пропускай Sprint Final.** External review обязателен перед merge в main.
