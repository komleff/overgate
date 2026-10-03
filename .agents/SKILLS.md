---
title: "OverGate Skill Registry"
status: active
version: "4.0.0-rc.1"
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
