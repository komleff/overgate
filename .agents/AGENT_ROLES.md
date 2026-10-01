---
title: "Agent Roles — Delivery First registry"
status: active
version: "4.1"
date: 2026-09-21
tags: [pipeline, agents, roles, delivery-first]
related:
  - .agents/PM_ROLE.md
  - .agents/SV_ROLE.md
  - .agents/PIPELINE_ADR.md
---

# Agent Roles — OverGate

Этот файл — registry. Детальная policy живёт в owner role/skill.
Состав и owner paths core skills — в `.agents/SKILLS.md`; conditional role triggers описаны в
соответствующих owner-документах ниже. Вызов skill — внутренняя процедура, не новый lifecycle
stage и не independent verifier launch.

## Общие правила

- direct push/merge в `main` запрещён всем ИИ; merge делает оператор;
- значимое evidence публикуется в PR с подписью `— [Role] ([Model])`;
- не создавай новый verifier без `AC / FAIL / named risk`;
- Delivery First канон — `PIPELINE_ADR.md §3.29`.

## Project Manager

Owner: `.agents/PM_ROLE.md`.

Планирует, строит Verification Contract, оркестрирует implementation → QA → scoped review → finalize.

## Supervisor

Owner: `.agents/SV_ROLE.md`.

Portfolio/dependencies/scope/budget stop-loss. Не обязателен для single PR.

## Product authority проекта

Назначается установленным проектом в `AGENTS.md`. Если адресата нет — оператор.
Это полномочие выбирать WHAT, а не седьмая обязательная delivery роль.
PM/Planner/Developer не принимают отсутствующее product решение самостоятельно.

## Developer

Owner: `.agents/DEV_ROLE.md`.

Claude adapter: `.claude/agents/developer.md`.

Реализует plan/AC, пишет automated tests, чинит blockers. Не меняет product requirements молча.

## Planner

Owner: `.agents/PL_ROLE.md`.

Claude adapter: `.claude/agents/planner.md`.

Исследует repo и строит implementation plan + Verification Contract. PRODUCT/CRITICAL plan идёт на Plan Review.

## Reviewer

Owner: `.agents/RV_ROLE.md`.

Claude adapter: `.claude/agents/reviewer.md`.

Два режима:
- `PLAN_REVIEW` → `PLAN_READY | CHANGES_REQUIRED`;
- `CODE_REVIEW` → BLOCKER/ADVISORY по explicit Review Contract.

PRODUCT = один Code Reviewer. CRITICAL второй pass не автоматический.

## QA / Tester compatibility name

Owner: `.agents/QA_ROLE.md`.

Claude compatibility adapter: `.claude/agents/tester.md`.

Независимо проверяет AC и evidence. Automated tests пишет Developer; QA их исполняет/дополняет
verification methods, но не чинит продуктовый код.

## Review depth

- FAST: verifier only by named risk.
- PRODUCT: Plan Review + QA + one scoped Code Review.
- CRITICAL: stronger Plan Review + QA + one full Code Review; extra/external only by named risk.

Sprint Final остаётся landing/milestone marker, но **не создаёт обязательный external review**.

## Публикация

Субагент возвращает structured report PM; PM публикует без изменения смысла.
Агент, запущенный оператором напрямую, публикует свой report сам.


## Runtime adapters

Общая role/pipeline policy живёт в `.agents/`. Vendor/runtime-файлы (`.claude/`, `.codex/`) —
только adapters и executable integration. Новый runtime считается подключённым только когда:
1. он читает `AGENTS.md`;
2. роли маршрутизируются к owner-файлам `.agents/*_ROLE.md`;
3. repository mutation guard проверяемо подключён либо declared platform limit записан явно.
