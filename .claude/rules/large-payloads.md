---
description: Safe publication of large PR reports.
---
# Большие отчёты и публикация

Не помещай недоверенные тела отчётов в shell-interpolated строки. Сохрани regular UTF-8 файл
внутри repository (ignored `.overgate-runtime/`) и используй trusted publisher:

```bash
.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py <PR_NUMBER> <BODY_FILE>
```

Publisher проверяет и отправляет один bytes buffer через stdin gh; последующая замена пути
не меняет опубликованное тело. Symlink/invalid UTF-8/empty body дают отказ. Tool failure — стоп.
Большой размер сам по себе не требует finalize. Readiness публикует только `/finalize-pr`;
FINALIZE_PR_TOKEN никогда не ставится для ordinary reports и не хранится в файлах/settings.
Субагенты возвращают отчёты PM; прямые verifier reports подписываются фактическими ролью/моделью.
