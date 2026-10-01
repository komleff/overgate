---
name: sprint-pr-cycle
description: Runtime pointer for the Delivery First PM lifecycle.
---
# Sprint PR cycle

Owner — `.agents/PM_ROLE.md`; lifecycle/budget — ADR §3.29–3.31.
Accepted WHAT → plan/Verification Contract → independent PLAN_READY для PRODUCT/CRITICAL
→ implementation/tests → QA → один scoped Code Review. Findings классифицирует Reviewer.
Blocker fix → affected QA/re-review. Advisory не требует автоматической правки/confirming pass.
Sprint Final: landing/bookkeeping в этой PR-ветке, fresh checks, evidence content binding,
accepted risks, затем один `/finalize-pr` на конечном HEAD. Merge — оператор.

Evidence хранится в PR с реальными role/model. Для больших отчётов:
`.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py <PR_NUMBER> <BODY_FILE>`.
BODY_FILE — regular UTF-8 file внутри текущего repository (например ignored `.overgate-runtime/`).
Publisher проверяет и отправляет одни и те же bytes; вне finalize не используй FINALIZE_PR_TOKEN.
Tool failure → адресный стоп. Source contract/role handoff не расширяют review surface.
