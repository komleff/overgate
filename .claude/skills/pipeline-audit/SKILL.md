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

Claude closure: одна managed Bash entry без backslashes, timeout 600 → `pre-bash.sh` →
mutation/readiness/commit guards + launcher/timeout helpers. Installed custom Bash entries
не входят в managed count. Codex проверяется по existing `.codex/hooks.json` contract.
Проверь apply order helpers/guards/dispatcher до settings и обратный rollback order;
missing dependency в staged manifest обязана блокировать до записи. Native Windows использует
Python + настоящий Git Bash; WSL и U2 smoke не заменяют installed platform evidence.
Recovery limits rc.1 перечислены в `.agents/INSTALL.md`; не объявляй произвольный path support.
