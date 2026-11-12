---
title: "OverGate Skill Registry"
status: active
version: "4.0.0-rc.4"
date: 2026-10-01
tags: [agents, skills, registry]
---
# OverGate Skill Registry

Registry владеет только membership и owner paths. Процедура — в owner SKILL.md,
условие вызова — в role owner из `.agents/AGENT_ROLES.md`, общая policy — ADR §3.31.

| Skill | Owner | Назначение |
|---|---|---|
| `canon-router` | `.agents/skills/canon-router/SKILL.md` | Current owner set |
| `product-gap` | `.agents/skills/product-gap/SKILL.md` | Неразрешённый WHAT |
| `product-handoff` | `.agents/skills/product-handoff/SKILL.md` | Условная product → PM передача |
| `diagnose` | `.agents/skills/diagnose/SKILL.md` | Неизвестная причина дефекта |
| `handoff` | `.agents/skills/handoff/SKILL.md` | Незавершённая работа между сессиями |
| `grill` | `.agents/skills/grill/SKILL.md` | Явно запрошенное интервью по идее, плану или решению |

Пять исходных generic skills сохраняют свои role triggers. `grill` устанавливается
вместе с ними, но вызывается только по запросу оператора и не добавляет обязательный
этап работы. Источник Matt Pocock и MIT notice входят в его installed payload.
