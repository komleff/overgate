# canon-router

## Purpose

Определить минимальный current owner set для задачи.

## Trigger

Новая domain/product work, если current owner context ещё не установлен.

## Inputs

Task/question, role, known product source if any.

## Process

Прочитать `AGENTS.md` и следовать его текущему authority/first-read route,
не копируя порядок здесь. Открыть только target owner и обязательные domain dependencies
(включая ADR-INDEX, когда того требует current bootstrap). Search result — candidate, не authority.

## Output

```text
CANON ROUTE
Domain:
Primary owner(s):
Supporting:
Excluded:
Conflict:
```

## Stop conditions

Неразрешённый конфликт current sources → `CANON CONFLICT` соответствующему authority.

## Do not

Не принимать product decision, не переписывать product source и не читать весь репозиторий «для уверенности».
