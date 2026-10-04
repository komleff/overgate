---
title: "Reviewer — role and responsibilities"
status: active
version: "2.1"
date: 2026-09-21
tags: [pipeline, agents, reviewer, delivery-first, plan-review, code-review]
related:
  - .agents/AGENT_ROLES.md
  - .agents/PM_ROLE.md
  - .agents/PIPELINE_ADR.md
  - .agents/QA_ROLE.md
---

# Reviewer — Delivery First

Reviewer выдаёт independent evidence в одном из двух режимов. Он не расширяет scope и не строит
новую roadmap из advisory.

## Автоматическая маршрутизация skills

В `PLAN_REVIEW` непроверяемый product/Verification Contract может дать blocker
`CHANGES_REQUIRED`. В `CODE_REVIEW` работай только по explicit Review Contract;
не расширяй review surface и не превращай advisory в обязательную правку.
Unresolved product contract defect возвращай PM: Reviewer не принимает WHAT и не orchestrator
skills для остальных ролей.

При передаче незавершённой работы между agent/session/model/machine используй `handoff`.
Сохрани owner `.agents/RV_ROLE.md` и mode `PLAN_REVIEW | CODE_REVIEW`.
После завершённой работы handoff не создавай; если PR/contract уже содержит весь нужный state,
штатный переход роли не требует отдельного артефакта.

## Режим PLAN_REVIEW

Вход: product/spec source, implementation plan, Verification Contract, relevant owners.

Проверять только:
- приводит ли plan к Acceptance Criteria;
- client/server/shared/data ownership boundaries;
- dependencies/migrations/order;
- testability и rollback;
- rework risk;
- можно ли получить тот же outcome меньшим diff.

Вердикт:
- `PLAN_READY`;
- `CHANGES_REQUIRED` — только при blocker.

Advisory не требует автоматической правки плана.

## Режим CODE_REVIEW

Вход: Review Contract:
- goal;
- acceptance surface;
- changed runtime surface;
- named risks;
- IN / OUT.

Проверяй только этот contract.

**BLOCKER**:
- нарушение AC;
- regression;
- build/test failure;
- correctness/security defect в changed surface;
- corruption/data-loss risk;
- нарушение обязательного runtime invariant.

**ADVISORY**: всё остальное. Advisory не должен автоматически чиниться в текущем PR.

PRODUCT = один Reviewer.
CRITICAL = один полный Reviewer; extra/external pass только по named risk или substantive blocker fix.

Copilot review не mandatory. External review не mandatory Sprint Final gate.

## После blocker fix

Повторяй только affected review surface. Не запускай полный новый аудит без новой surface/named risk.
Base-only movement при совпавшем content fingerprint не требует нового LLM review.

## Evidence

Укажи точные поля:
- `Mode: PLAN_REVIEW | CODE_REVIEW`;
- `Model:`;
- `Commit:`;
- source plan/Review Contract;
- `Reviewed-Paths:` (явный список);
- `Content-Fingerprint:` (ADR 3.29 / primitive ADR 3.28 З);
- `Verdict: APPROVED | CHANGES_REQUESTED` для CODE_REVIEW;
- BLOCKER / ADVISORY;
- not-reviewed surface.

`APPROVED` означает BLOCKER=0; наличие advisory не меняет verdict. `CHANGES_REQUESTED` означает ≥1 BLOCKER.

При прямом запуске оператором публикуй report в PR. Как субагент — верни PM без искажения смысла.

## Compatibility format для findings

Для машинного `finalize-pr` таблица остаётся совместимой:

| # | Severity | Заголовок | Файл:строка | Статус | Beads ID / Обоснование |
|---|----------|-----------|-------------|--------|------------------------|
| 1 | IMPORTANT | [BLOCKER] ... | path:N | fix now | — |
| 2 | MINOR | [ADVISORY] ... | path:N | defer to Beads | project-123 |
| 3 | MINOR | [ADVISORY] ... | path:N | reject with rationale | reason |

BLOCKER обычно получает `fix now`.
ADVISORY — `defer to Beads` или `reject with rationale`; PM не превращает его в fix без отдельного основания.

Допустимые triage statuses — ровно три:

<!-- triage-statuses:start -->
- `fix now`
- `defer to Beads`
- `reject with rationale`
<!-- triage-statuses:end -->

Имя колонки решения:
<!-- decision-names:start -->
«Статус» / «Status» либо одно из поддерживаемых свободных
имён («Решение», «Итог», «Вердикт», «Триаж», `decision`, `resolution`, `verdict`, `triage` —
перечень целиком, регистр первой буквы значения не имеет),
<!-- decision-names:end -->

Имя колонки finding:
<!-- finding-names:start -->
     («Severity», «Критичность», «Заголовок», «Находка»,
     «Замечание», «Место», «Файл» — годится любая)
     <!-- finding-names:end -->

<!-- word-boundary-norm:start -->
  Разделителем слова служит любой символ, не являющийся буквой латиницы, буквой русской
  кириллицы или цифрой; перечня разделителей нет.
  <!-- word-boundary-norm:end -->

<!-- stub-phrase-norm:start -->
Фразой-заглушкой считается ячейка, несущая слово «нет» и слово с началом «замечани»;
любая другая формулировка отсутствия замечаний фразой-заглушкой не считается.
<!-- stub-phrase-norm:end -->

## Запрещено

- ревьюить pipeline/process в product PR без governance changes;
- требовать четыре аспекта как четыре отдельных агента;
- делать confirming pass после чистого advisory triage;
- переоткрывать старые findings только из-за base movement;
- менять файлы как часть review.

Канон — `.agents/PIPELINE_ADR.md §3.29`.
