# product-gap

## Purpose

Выявить missing WHAT, которое implementation не имеет права выбирать само.

## Trigger

User-facing/product behaviour не определено authoritative source.

## Inputs

Ambiguity, CANON ROUTE, relevant product source.

## Process

Сформулировать один нерешённый product question, затронутое поведение и authority решения.
Предлагать варианты только если это помогает оператору или назначенному product owner.

## Output

```text
PRODUCT GAP PG-XX
Question:
Why unresolved:
Affected behaviour:
Why implementation cannot choose:
Decision required from:
```

## Stop conditions

Решение WHAT отсутствует — вернуть gap к product authority через текущую роль.

## Do not

Не выбирать вариант за product authority, не маскировать product choice как technical default и не запускать review.

Product authority берётся из `AGENTS.md` установленного проекта. Если владелец не назначен,
`Decision required from: оператор`. Skill не создаёт обязательную designer-роль.
