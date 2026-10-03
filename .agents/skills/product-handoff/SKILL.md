# product-handoff

## Purpose

Условно перевести принятое решение product owner в implementation-ready product contract.

## Trigger

Передача product → PM, когда риск неоднозначной реализации требует проверки готовности WHAT.

## Inputs

Current product source/spec, принятое product authority решение, область реализации.

## Process

Первый вопрос: можно ли реализовать WHAT без угадывания? Если current source уже содержит
достаточные behaviour, states, parameters/units, expected/error/edge behaviour, non-goals и
Acceptance Criteria, выбрать `PASS_THROUGH`. При недостатке структуры выбрать
`AMEND_EXISTING` или `CREATE_SPEC` только для уже принятого WHAT.
Недостающая product semantics сначала становится PRODUCT GAP.

## Output

Ровно один маршрут: `PASS_THROUGH`, `AMEND_EXISTING` или `CREATE_SPEC`;
при unresolved WHAT — PRODUCT GAP перед продолжением.

## Stop conditions

Нельзя структурировать источник без нового product decision.

## Do not

Не «дописывать для полноты» product rules. Не навязывать class hierarchy, method names, network transport или другую HOW-архитектуру.
