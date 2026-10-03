---
name: verify
description: Run the actual deterministic checks configured by the current project.
---
# Verify

В reference выполни `bash scripts/verify-reference.sh`; в установленном проекте —
`bash .agents/project/verify.sh`. Это project-owned entrypoint; installer создаёт fail-closed
шаблон, если команд ещё нет. Незаполненный шаблон — NOT RUN/FAIL, не PASS.
Не подменяй project tests structural reference checks. Укажи HEAD, команду, exit status,
PASS/FAIL/NOT RUN и not-tested surface. Ошибка инструмента не является зелёным результатом.
