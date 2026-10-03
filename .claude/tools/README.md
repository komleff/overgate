# Runtime tools

`run-python.sh` переносимо выбирает Python 3; `with-timeout.sh` ограничивает процесс/группу;
`publish-pr-comment.py` читает regular UTF-8 body внутри repo, проверяет readiness shared policy
и передаёт gh те же bytes через stdin. Hook/parser dependencies лежат в `.claude/hooks/`.

`openai-review.mjs`, `smoke-test.mjs`, `codex-account-switch.ps1` — optional legacy capabilities,
не обязательная часть RC install. Без явного выбора оператора не запускать auth/install/account
setup, не выбирать жёсткий модельный профиль и не передавать credentials. История — CODEX_AUTH.md.
Штатный review route и budget определяет ADR §3.29; extra/external требует named risk/request.
