---
title: "Pipeline overview — Delivery First"
status: active
version: "3.1"
date: 2026-09-21
tags: [pipeline, overview, delivery-first]
related:
  - .agents/PIPELINE_ADR.md
  - .agents/PM_ROLE.md
  - .agents/AGENT_ROLES.md
---

# OverGate Delivery First Pipeline

Текущая операционная карта. Канон норм — `PIPELINE_ADR.md §3.29–3.32`.
Условные role triggers skills см. в [реестре ролей](AGENT_ROLES.md) и
[реестре skills](SKILLS.md); исторические источники — в [REFERENCES.md](REFERENCES.md).

```text
product source/spec
  ↓
PM: accepted WHAT (ready source → PASS_THROUGH) + gap analysis + plan + Verification Contract
  ↓
PRODUCT/CRITICAL: independent Plan Review → PLAN_READY
  ↓
Developer: implementation + deterministic tests
  ↓
QA: AC → tests → evidence
  ↓
one scoped Code Review
  ↓
BLOCKER? → minimal fix → affected QA + scoped re-review
  ↓
Sprint Final? → landing/bookkeeping in PR → fresh deterministic checks
  ↓
content-equivalent? keep evidence : affected recheck
  ↓
one /finalize-pr on final HEAD
  ↓
operator merge
```

## Режимы

- FAST — safe docs/content/parameters; verifier only by risk.
- PRODUCT — default feature path.
- CRITICAL — named high technical risk, not path-count ceremony.

## Что больше не является обязательным gate

- четыре reviewer-субагента;
- Copilot review/re-review;
- второй Critical pass;
- Sprint Final external review;
- confirming pass после advisory triage;
- fresh LLM review только из-за base movement;
- W-driven recovery loop.

External review остаётся инструментом named-risk/operator request. Sprint Final landing сам по себе нового external/LLM pass не создаёт.
Незавершённая работа при передаче получает role-aware handoff; завершённая работа не требует
отдельного handoff. Skill invocation не считается новым verifier launch.

## Что остаётся hard

- deterministic `/verify`, CI/build/tests;
- correctness/security/data-loss blockers;
- valid PR contract/evidence;
- explicit accepted risk для реального Important/Critical known risk;
- branch protection, no direct push/merge by agents;
- operator merge decision.

## Content equivalence

Verifier report несёт reviewed/tested paths + content fingerprint.
На новом HEAD deterministic checks повторяются всегда.
Совпал fingerprint и surface → LLM evidence сохраняется.
Изменилась surface → recheck only affected surface.

## Evidence

PR хранит Plan Review, QA Execution, Code Review, Fix Verification при необходимости и Final Acceptance.
Operator chat не является единственным источником технической истории.

## Supervisor

Supervisor нужен для portfolio/dependencies/scope/budget stop-loss, не как обязательная оболочка single PR.
