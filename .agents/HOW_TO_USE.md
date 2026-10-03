---
title: "OverGate — как работать"
status: active
version: "4.0.0-rc.1"
date: 2026-10-03
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

## Claude Bash и каталог сессии

Для автоматической загрузки project hooks запускайте Claude из корня checkout и
подтвердите загрузку settings/hooks. Shared `.claude/settings.json` не наследуется
из родительских каталогов: новый запуск в подкаталоге без дополнительной настройки
не включает root hooks. Если hooks уже загружены, Bash cwd в подкаталоге, включая
пакет монорепо, включает режим восстановления до возврата в root.
Для нового native CLI запуска из подкаталога явно загрузите неизменённый installed
root файл через `--settings <ROOT>/.claude/settings.json`, разрешите root как workspace
через `--add-dir <ROOT>` и используйте `--permission-mode manual`. Без разрешения root
runtime может принять `cd`, затем вернуть cwd в стартовый подкаталог; это не успешное
восстановление. Такой startup проверяется отдельно от автоматического root startup.
Семантика загрузки: [Claude settings](https://code.claude.com/docs/en/settings) и
[CLI options](https://code.claude.com/docs/en/cli-reference). В rc.1 допускается только одна unquoted команда
`cd <absolute-checkout-path>`; допустимые символы пути — латиница, цифры, `_ : / . -`.
Пробелы, кириллица, скобки и кавычки в этой форме не поддерживаются. Для такого пути
завершите сессию и откройте новую непосредственно в корне checkout через интерфейс
runtime/терминала. Root-запуск не зависит от `CLAUDE_PROJECT_DIR`, даже если переменная
указывает на соседний checkout. Исправление recovery paths и внутренних U2-префиксов
отложено в `og-7sr`; rc.1 сохраняет исходную семантику U2 #829.

Если Bash cwd находится вне любого Git-репозитория, rc.1 блокирует команду кодом 2,
но печатает заглушку `cd <корень репозитория>`, а не готовую literal-команду.
Это `DECLARED_LIMIT`, принятый оператором для совместимости с U2: завершите сессию
и запустите её заново из root нужного checkout. Literal-подсказка вне Git отложена
в `og-7sr`. Для подкаталога собственного checkout напечатанная absolute-команда
возврата в root остаётся обязательной и должна сама проходить hook.

Три guards идут последовательно: repository mutation, PR readiness, project commit tests.
Быстрая фаза сужает окно настоящего `.agents/project/verify.sh` через
`OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS`; явный более узкий override сохраняется.
Custom runtime hooks проекта сохраняются при upgrade. Codex использует существующий adapter;
его activation и платформенные пределы проверяются отдельно.
