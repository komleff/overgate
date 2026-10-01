---
title: "OverGate — как работать"
status: active
version: "4.0.0-rc.1"
date: 2026-10-01
tags: [pipeline, usage]
---
# Как работать

Дайте агенту роль и цель. Один PR обычно ведёт PM; Supervisor нужен только для portfolio.
Product authority задаётся в AGENTS проекта, иначе вопрос возвращается оператору.
Готовый принятый source не требует новой spec. Missing WHAT — PRODUCT GAP.

PM выбирает FAST/PRODUCT/CRITICAL по ADR §3.29 и строит plan + Verification Contract.
PRODUCT/CRITICAL начинают с Draft PR и независимого PLAN_READY. Developer реализует,
QA проверяет AC, один Reviewer проверяет explicit IN/OUT. Blocker fix возвращается тем же
проверяющим для affected recheck. Advisory не становится обязательной работой.

Перед single finalize: landing artifacts в ветке, fresh deterministic checks, evidence binding,
triage и accepted risks. Merge выполняет оператор. Base-only movement не требует нового LLM
review при доказанном fingerprint. Evidence публикуется в PR с role/model.

`/verify` выполняет реальные команды проекта. `/external-review` — optional named-risk
capability, без автоматического login/setup/модельного профиля. `/pipeline-audit` — адресная
проверка пакета по named risk, не обязательный дополнительный gate.

Unfinished handoff использует `.agents/skills/handoff/SKILL.md`; завершённой работе отдельный
handoff не нужен. Установка/upgrade/rollback: `.agents/INSTALL.md`.
