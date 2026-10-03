# handoff

## Purpose

Передать рабочее состояние проекта, а не историю разговора.

## Trigger

Передача незавершённой работы между agent/session/model/machine либо явный запрос оператора.

## Inputs

Current role and canonical owner map, PR/branch/candidate state, product source,
plan/Verification Contract, выполненная работа, evidence, blockers и следующий шаг.

## Process

Взять role owner из canonical registry. Для Reviewer указать `PLAN_REVIEW` или `CODE_REVIEW`.
Передать точные SHA и незавершённое состояние минимально достаточным носителем:
chat block, `docs/handoffs/` либо короткий PR-native handoff.
При продолжении новый агент проверяет freshness candidate/PR; handoff — snapshot, не canon.

## Output

```text
PROJECT
BOOTSTRAP
PIPELINE

ROLE
ROLE OWNER
ROLE MODE
MISSION

TASK
MODE
PRODUCT SOURCE
PLAN / VERIFICATION CONTRACT

REPOSITORY
PR
BRANCH
BASE SHA
CANDIDATE SHA

DONE
IN PROGRESS
OPEN

EVIDENCE
BLOCKERS
PRODUCT GAP
DECLARED LIMIT

NEXT SAFE ACTION
DO NOT
```

`ROLE MODE` обязателен, когда применим; для RV обязателен всегда.

## Stop conditions

Нет надёжного current repo/candidate state — обозначить неизвестное и не выдавать stale snapshot за canon.

## Do not

Не заменять handoff пересказом чата и не выдавать snapshot за authoritative source.
