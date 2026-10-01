---
description: Project tests and deterministic evidence.
---
# Проверки

Expected/error/edge cases происходят из Verification Contract, не из implementation.
Для исполняемых изменений получи релевантный RED, затем GREEN и affected regression.
Reference: `bash scripts/verify-reference.sh`; project: `.agents/project/verify.sh`.
Missing test commands или отсутствующая среда — NOT RUN, не PASS. Hook exact commit
запускает project entrypoint независимо от package manager. Не отключай failing tests.
Tests принадлежат Developer; QA независимо проверяет AC и не меняет requirements.
