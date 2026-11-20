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
Повторно используй полное evidence при тех же HEAD, дереве, командах и окружении.

Проект, использующий Docker Desktop, может обернуть свои команды в
`bash .claude/tools/run-python.sh .claude/tools/docker_desktop.py run -- <command> [args]`.
Для восстановления своей прерванной операции используй `recover`. Если проект запускает
Desktop из commit gate, его адаптер должен передать `OVERGATE_COMMIT_GATE=1`, ограничить
timeout дочерней команды с запасом 120 секунд внутри дедлайна hook и выполнить `prepare`
до commit. Без такого адаптера запускай helper отдельно от commit. Свои контейнеры
помечай `--label "overgate.desktop.scope=$OVERGATE_DOCKER_SCOPE"`, когда переменная задана.
Нативная проверка macOS выполняется на macOS.
