---
name: pipeline-audit
description: Inspect a named pipeline risk and managed package closure.
---
# Pipeline audit

Только по AC / FAIL / named risk. Выполни `python3 scripts/check-reference.py`, затем relevant
fixtures из `scripts/verify-reference.sh`. Managed payload — `.agents/distribution-manifest.json`.
Проверь owner/runtime paths, пять core skills, source/install inventory и local overrides.
Reference suite не заменяет project suite и не доказывает live Claude/Codex hook activation.
Known limits фиксируй как NOT RUN/DECLARED_LIMIT. Не добавляй review cycle, не чини advisory автоматически.

Публикация: `.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py <PR_NUMBER> <BODY_FILE>`.
Без readiness/token; report подписывается фактическими role/model.
