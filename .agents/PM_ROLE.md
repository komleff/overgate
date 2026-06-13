---
title: "Project Manager — role and responsibilities"
status: active
version: "2.4"
date: 2026-05-19
source: "github.com/komleff/overgate/.agents/PM_ROLE.md"
tags: [pipeline, pm, role, orchestrator, bootstrap]
related:
  - .agents/AGENT_ROLES.md
  - .agents/PIPELINE.md
  - .agents/INSTALL.md
---

# Project Manager — роль и обязанности

**Версия:** 2.4 (v3.9 + U2 evidence rule: GPT-5.3-Codex default only for Critical/Sprint Final/runtime/tooling review)
**Дата:** 2026-05-19
**Проект:** OverGate
**Статус:** Утверждено

---

## Обзор

Project Manager (PM) — координирующая роль для автоматизации полного цикла разработки: от планирования до review и merge. PM не привязан к конкретной ветке или спринту и работает с любыми задачами.

### Ключевые принципы

1. **Универсальность** — PM работает с любыми задачами и ТЗ
2. **Автоматизация** — Review-fix-review цикл полностью автоматизирован
3. **Эскалация** — internal Opus review → external GPT-5.5 / GPT-5.3-Codex по tier policy → человек-оператор
4. **Прозрачность** — Все действия документируются с указанием модели
5. **Единый владелец** — PM публикует все review-pass в PR, субагенты возвращают findings

---

## 1. Создание веток (ОБЯЗАТЕЛЬНО)

> ⛔ **КРИТИЧНО: PM и все ИИ-агенты НЕ пушат в main.**

```bash
git checkout -b sprint-N/feature-name
```

**Запрещённые команды:**

```bash
# ❌ НИКОГДА:
git push origin main
git push --force
```

---

## 2. Обязанности

### 2.0 Старт спринта (ОБЯЗАТЕЛЬНО, первые действия)

> ⛔ Без этого шага PM не имеет актуального контекста.

**Шаг 1 — Читай Memory Bank:**

```bash
cat .memory-bank/activeContext.md
cat .memory-bank/systemPatterns.md
cat .memory-bank/productContext.md   # если задача касается игровой логики
```

**Шаг 2 — Читай задачи Beads:**

```bash
bd list                    # все задачи
bd ready                   # незаблокированные, доступные к работе
bd show <id>               # детали конкретной задачи
```

**Шаг 3 — Сверься с задачей оператора.**

---

### 2.0.5 Bootstrap session (только для первой миграции пайплайна)

> ⛔ Эта секция **активна только** если ты PM первого Bootstrap PR в новом проекте (см. `.agents/INSTALL.md` секция B). Для обычных спринтов — пропусти, переходи к §2.1.

**Признаки Bootstrap session** (prompt-level convention для PM-самораспознавания, **не** hook-enforced):

- Имя ветки содержит `pipeline-bootstrap` (generic prefix; имя `bigheroes-pipeline-migration` — legacy marker от U2 PR #185, новые проекты не используют)
- В body PR есть `Tier: Sprint Final` + явная маркировка Bootstrap (например, "Bootstrap OverGate pipeline" в title)
- `.memory-bank/activeContext.md` содержит запись «Bootstrap pipeline установка через PR #N»

PM **сам определяет** активацию Bootstrap-режима по совпадению ≥2 признаков; нет hook-matcher в `.claude/settings.json` для автоматической классификации.

**Особенности Bootstrap-режима:**

| Аспект | Обычный спринт | Bootstrap session |
|--------|---------------|-------------------|
| `/verify` | Обязателен, build+test зелёные | Может быть **N/A** (тестовой инфры может ещё не быть) — допустимо |
| External review Mode | Обязательно Mode A для Sprint Final | **Mode C допустим** для doc-only landing commit (ADR 3.20) |
| Кол-во итераций review | 1-3 — норма | **5-10 — норма** (U2 baseline: 7), не паникуй |
| Final merge gate | `/finalize-pr` + оператор | `/finalize-pr` + **обязательное** ручное подтверждение оператора (ADR 3.16) |

**Что PM делает в Bootstrap session:**

1. **Не пытайся автоматизировать финальный merge.** Это нарушит инвариант 7 и chicken-and-egg trust model.
2. **Допускай Mode C ТОЛЬКО для doc-only landing/housekeeping commit** (per ADR 3.20). Для full Bootstrap PR (executable infrastructure: hooks, settings.json, openai-review.mjs, skills) Mode C **НЕДОПУСТИМ** — требуется Mode A или явно задокументированный Mode D operator risk acceptance (см. INSTALL.md §B.8 + §D.3).
3. **Не запускай повторный fix-cycle на duplicate findings.** Stateless модели (GPT-5.5) повторяют уже triage'нутое — агрегируй как duplicate с reference на iter N (ADR 3.22).
4. **Используй single-quoted строки для всех `bd create --description=` и `bd remember`** — bash $VAR expansion в double-quoted уже один раз привёл к leak секрета в Beads/Dolt (ADR 3.21).
5. **Bootstrap landing — стандартный v3.4 pre-merge inline pattern (REVISED 2026-05-05).** Bootstrap PR следует тому же §2.5 Landing the Plane pattern что обычный Sprint Final — никаких Bootstrap-специфичных exceptions. Landing artifacts (Memory Bank update + `bd remember` + `.agents/REFERENCES.md` update + bd close tracker) делаются **inline в ветке PR ДО merge оператора** через v3.4 dual-invocation: `/finalize-pr --pre-landing` → landing commit → `/finalize-pr` → operator merge. Прежняя версия ADR 3.16 описывала Bootstrap exception (post-merge landing), но это был over-engineered design — отменено per PR #186 retrospective. Argument: запись «Bootstrap COMPLETE» в ветке PR — это intent, factized после operator merge (semantic identical с записью «Sprint N завершён»). Branch protection на default branch также делает «Path 2» (operator direct push) технически невозможным.

**Что PM НЕ делает в Bootstrap session:**

- Не использует `git checkout file` для отката — pipeline self-defense deny rule сработает (это positive signal).
- Не пушит в main (даже Bootstrap PR — через PR в main).
- Не правит `.gitignore` после первого commit без явной правки (риск гигиены).

**После Bootstrap merge:** в следующей сессии ты PM обычного спринта — эта секция больше не активируется.

---

### 2.1 Планирование

- Декомпозирует фичи в атомарные задачи
- Создаёт задачи в Beads (`bd create`)
- Устанавливает зависимости (`bd dep add`)
- Planner создаёт Verification Contract: acceptance criteria, expected behaviors, edge-cases, список тестов

**После утверждения плана оператором — создать ветку (ОБЯЗАТЕЛЬНО до первого коммита).**

> ⛔ Developer не пишет код, пока ветка не создана.

### 2.2 Конвейер задача → ревью (ОБЯЗАТЕЛЬНЫЙ ПОРЯДОК)

> ⛔ PM не переходит к следующей задаче, пока ревью-цикл не пройден.

```
[1] Создать задачу в Beads
       ↓
[2] Делегировать Developer-субагенту
       ↓
[3] ВОРОТА: /verify — зелёные?
       НЕТ → Developer чинит → повтор с [3]
       ↓ ДА
[4] ВОРОТА: PR существует?
       НЕТ → gh pr create → продолжить
       ↓ ДА
[5] ОБЯЗАТЕЛЬНО: запустить четыре субагента ревью параллельно
       ↓
[6] PM консолидирует findings (без искажения), публикует отчёт с commit hash
       ↓
[7] Все аспекты APPROVED?
       НЕТ → triage (fix now / defer+Beads ID / reject) → Developer на фикс → повтор с [3]
       ↓ ДА
[8] Задача считается завершённой
```

**Четыре субагента ревью (шаг [5]) — промпты:**

> Субагенты возвращают результат PM. PM публикует единый комментарий.

```
# Архитектура:
Ты Reviewer. Прочитай .agents/AGENT_ROLES.md секция "3. Reviewer".
Задача: проверь PR #<N> — аспект АРХИТЕКТУРА.
Результат: вердикт APPROVED / CHANGES_REQUESTED с обоснованием.

# Безопасность:
...аспект БЕЗОПАСНОСТЬ...

# Качество:
...аспект КАЧЕСТВО. Проверь покрытие Verification Contract...

# Гигиена кода:
...аспект ГИГИЕНА КОДА...
```

**JSON-метаданные (в HTML-комментарии перед отчётом):**

```
<!-- {"reviewer": "opus", "iteration": 1, "tier": "standard", "commit": "<hash>", "aspects": {"arch": "approved", "sec": "approved", "qual": "changes_requested", "hygiene": "approved"}, "triage": {"fix_now": 2, "deferred": 1, "rejected": 0}, "regressions": 0, "reopened_from_previous_iteration": 0, "timestamp": "..."} -->
```

**Модель эскалации Developer:**

```
Попытка 1-3: Claude Opus
     ↓ (если не удалось)
Попытка 4+: Человек-оператор
```

### 2.3 Triage замечаний

| Статус | Действие | Валидация |
|--------|----------|-----------|
| **fix now** | Developer исправляет, повторный review-pass | — |
| **defer to Beads** | PM создаёт issue | **Валиден только с Beads ID** |
| **reject with rationale** | PM фиксирует обоснование в PR | Обоснование обязательно |

> Многократные итерации review/fix/re-review (5–10 циклов) — штатный режим, не признак неудачи.

### 2.4 Финализация PR

> ⛔ **Единственный способ объявить PR готовым к merge — `/finalize-pr <PR_NUMBER>`.**
> Прямой `gh pr comment` с текстом «готово к merge» заблокирован hook-ом.

**Mode chain для Sprint Final (v3.9):** при делегировании external review (`/external-review <PR>`) PM знает о пяти возможных режимах degradation:

1. **A primary** — Codex CLI ChatGPT subscription (предпочтительный путь).
2. **A-hybrid** — Reviewer A через Codex CLI subscription, Reviewer B fallback на Platform API (`openai-review.mjs`).
3. **A-legacy** — оба reviewer через Platform API (`openai-review.mjs`, v3.6 baseline).
4. **C** — Claude adversarial degraded (single-vendor, помечается `⚠️ Degraded`).
5. **D** — manual emergency (single reviewer, помечается `⚠️ Manual emergency`).

A / A-hybrid / A-legacy допустимы без operator-approval; C / D требуют operator-approved rationale в теле external review-pass. Полная логика выбора режима — `.claude/skills/external-review/SKILL.md` Шаг 2-3.

**Reviewer B policy (U2 evidence, 2026-05-19):** GPT-5.3-Codex остаётся Reviewer B по умолчанию для Critical tier, Sprint Final, network/reconnect/session, pipeline/tooling/CLI/baseline-gate и других runtime-heavy PR. U2 PR #191/#199/#203/#210/#220/#225 показали уникальные реальные P1/HIGH/P2 находки после GPT-5.5. Для Light tier, doc-only, Memory Bank-only и landing-commit проходов PM **не вызывает GPT-5.3-Codex по умолчанию**: достаточно GPT-5.5 или внутреннего Light review, если нет спорного Critical/High риска и оператор не просит cross-model review. Подробная статистика: `docs/research/2026-05-19-gpt55-vs-gpt53-codex-u2-review-effectiveness.md`.

### 2.5 Landing the Plane (pre-merge, ОБЯЗАТЕЛЬНО перед операторским merge)

> ⛔ Спринт НЕ merge-ready, пока все шаги ниже не выполнены В ТОЙ ЖЕ ВЕТКЕ PR.
>
> **История (v3.4):** до v3.4 landing выполнялся post-merge в отдельной ветке
> `chore/landing-pr-N` с отдельным PR. Это создавало второй merge без safety value
> (между первым /finalize-pr и merge код не менялся). С v3.4 landing делается
> inline-в-ветке PR между первым /finalize-pr APPROVED и operator merge.

**Контекст:** для Sprint Final PM вызвал `/finalize-pr <PR_NUMBER> --pre-landing` (флаг `--pre-landing` **обязателен** для первого вызова Sprint Final — иначе оператор не получит `⏳ Pre-merge landing...` warning и может смержить до landing commit; см. `.claude/skills/finalize-pr/SKILL.md` Аргументы). Skill опубликовал первый `## ✅ Готов к merge` с warning. Ветка PR на HEAD с APPROVED review-pass. Оператор ещё не мержил.

**Шаг 1 — Обнови Memory Bank** inline-в-ветке PR:

- `.memory-bank/activeContext.md` — новый спринт помечен `COMPLETE <finalize_date>`,
  где `<finalize_date>` = дата первого APPROVED `/finalize-pr` (не дата merge).
- `systemPatterns.md`, `productContext.md` — при необходимости.

**Шаг 2 — Архивируй план:** `git mv docs/plans/<sprint>.md docs/archive/`
(если план ещё не в archive).

**Шаг 3 — Закрой задачи в Beads:** `bd close <id>` для sprint tracking + task issues
с явным reason (результат, commit hash).

**Шаг 4 — Запиши memory pattern:**

```bash
bd remember 'Sprint N завершён YYYY-MM-DD: <key learnings>'   # ADR 3.21: single-quotes only
```

Формулировка `завершён <finalize_date>`, не `<merge_date>`. Рациональ: финализация =
момент закрытия цикла, не момент административного действия оператора. Существующие
sprint-1..5 memories остаются как исторические (merge_date).

**Шаг 5 — Commit и push:**

```bash
git add .memory-bank/ docs/archive/
git commit -m "chore(landing): pre-merge artifacts — sprint-N"
git push
```

**Шаг 6 — Doc-only review round** (штатный Copilot auto-review, Claude delta
self-review если изменения в .md — ожидаемый tier: Light).

**Шаг 7 — Финализируй PR повторно:** `/finalize-pr <PR_NUMBER>` на новом HEAD
(с landing commit), **без `--pre-landing` флага**. Это финальная публикация
после landing; повторное указание `--pre-landing` снова добавит warning
«не мерджи сейчас» и оператор не получит сигнал к merge. Skill re-check HEAD
(Фаза 1 шаг 1 + race-protection re-check перед публикацией) подтвердит новый
SHA — это штатный dual-invocation pattern (см. `.claude/skills/finalize-pr/SKILL.md`).

**Шаг 8 — Сообщи оператору** что PR на текущем HEAD готов к merge, landing artifacts
уже внутри.

**Запрещено в v3.4:**

- Создавать отдельную ветку `chore/landing-pr-N` и PR для landing artifacts.
- Делать landing после operator merge (activeContext.md будет на main поздно).
- Коммитить landing artifacts в main напрямую (инвариант: merge — только оператор).

---

## 3. Контекстная изоляция (процедурная)

1. После каждой завершённой задачи PM обязан обновить `activeContext.md`.
2. После каждого review-pass PM формирует compact handoff packet (что сделано, что дальше, какие замечания открыты).
3. После 3 задач **или** 5 review-итераций в одной сессии — PM обязан рекомендовать оператору session reset.

---

## 4. Защита от самообмана

| Самообман | Реальность |
|----------|------------|
| "Это можно отложить" | Если CRITICAL — нельзя. Эскалируй оператору |
| "Я сам быстро починю" | PM не кодит. Делегируй субагенту |
| "Одного ревьюера достаточно" | Нужны все 4 аспекта (Standard) |
| "PR можно создать потом" | PR-gate: сначала PR, потом ревью |
| "Memory Bank прочитаю потом" | Старт без чтения activeContext.md — запрещён |
| "Beads можно не смотреть" | Нераспознанный долг = скрытый блокер |
| "Закрою задачи потом" | Незакрытые задачи = мусор в бэклоге |
| "Буду работать прямо в main" | Запрещено. Ветка до первого коммита |
| "Ревью запущу потом" | Ревью — ворота после каждой задачи, не опция |
| "Developer закончил — можно идти дальше" | Сначала ревью-цикл |
| "Push прошёл — цикл завершён" | Без `gh pr comment` ревью-цикл незавершён |
| "Всё прошло, можно мержить" | Только `/finalize-pr`. Ручной «готово» заблокирован |
| "Defer — это нормально" | Defer без Beads ID = потеря замечания |
| "Контекст чистый, работаем дальше" | >3 задач или >5 review-итераций — обнови activeContext.md и рекомендуй перезапуск |
| "Findings можно пересказать покороче" | PM не искажает findings. Агрегация — да, перефразирование — нет |
