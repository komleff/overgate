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

## Beads: основной checkout, worktree и облачный агент

Это документационное дополнение для планируемой v4.0.1. Оно переносит порядок работы
из [U2 ADR-0042](https://github.com/komleff/u2/blob/cdc490e3517c8455f662f82579c45813cdbb9a76/docs/architecture/ADR-0042-Beads-Access-By-Environment.md),
не объявляя выпуск новой версии. Product authority и project-owned правила сохраняются.
Beads хранит состояние задач; Git/PR — изменения кода и evidence.

### Сначала определить доступ к базе

Класс определяется доступом к живой базе оператора, а не наличием `.git` или `bd` в PATH.
Обычный standalone clone в облаке не становится основным checkout оператора.

| Окружение | Чтение | Запись | Кто публикует снимок |
|---|---|---|---|
| Основной checkout оператора с живой базой | `bd ready`, `bd show <id>` | `bd create/update/close` | Основной checkout через `scripts/bd-sync-export.sh` |
| Локальная worktree, доступен сервер основного checkout | `scripts/bd-wt.sh ready/show <id>` | `scripts/bd-wt.sh create/update/close` | Основной checkout |
| Облачный агент без основной базы и диска оператора | `scripts/bd-read.sh` или снимок через авторизованный GitHub-коннектор | Заявки `.bd-intents/<branch-slug>.jsonl` в рабочей PR-ветке | Оператор после применения заявок |

**Граница поставки:** OverGate содержит `bd-wt.sh`, `bd-read.sh` и sync helpers.
`bd-apply-intents.sh`, `lib/bd-apply-engine.mjs` и очередь пока не входят в distribution
inventory. Облачный режим с применением заявок требует отдельно установленного и
проверенного project tooling. Эта инструкция не выдаёт отсутствующий applier за готовый.
В U2 он уже есть; новому проекту нужно подготовить его до первого apply.

Single-writer означает одну физическую базу/сервер основного checkout. Несколько клиентов
через `bd-wt.sh` допустимы; отдельная облачная база и самостоятельная публикация снимка — нет.
Guard отличает worktree от checkout, но не удостоверяет оператора или доверенность скрипта.

### Основной checkout оператора

1. Использовать существующую рабочую базу; не создавать вторую поверх неё.
2. Если другая машина опубликовала новый снимок, выполнить `scripts/bd-sync-restore.sh`
   до новых мутаций; конфликты состояния сверить с оператором.
3. Выполнять `bd ready`, `bd show <id>`, `bd update <id> --claim`, затем работу по задаче.
4. Публиковать изменения задач через `scripts/bd-sync-export.sh`.

Служебная ветка `beads-backup` содержит экспорт `.beads/issues.jsonl`. Живая база первична
для текущей работы, снимок — опубликованное состояние для других сред. Export/restore
запускаются только из основного checkout. Last-seen/drop guards и non-force push сохраняются;
их override не является обычным способом разрешать конфликт. `bd dolt push/pull` не применять.

### Локальная worktree

Из основного checkout оператор сначала запускает обычную `bd ready`, чтобы сервер работал.
В worktree использовать обёртку для каждой команды:

```bash
scripts/bd-wt.sh ready
scripts/bd-wt.sh show <id>
scripts/bd-wt.sh update <id> --claim
scripts/bd-wt.sh close <id> --reason 'Результат и evidence опубликованы в PR'
```

Она сама вычисляет основную базу и передаёт `--db`, проверяет живой сервер и запрещает
`export/import/dolt` и пользовательский `--db`. Прямой `bd` с auto-discovery в worktree
может создать пустую базу. Если основной сервер недоступен, не запускать второй:
прочитать снимок и передать оператору заявку. Публикация остаётся в основном checkout.

### Облачный агент: GitHub-коннектор достаточен

При уже авторизованном GitHub-коннекторе дополнительный login для Git CLI не нужен.
Коннектор и shell Git имеют разные каналы доступа: работа с PR через коннектор не означает,
что `git fetch`/`gh` в контейнере тоже авторизованы. Отказ shell Git не блокирует весь task.

1. Прочитать `.beads/issues.jsonl` **из ветки `beads-backup` текущего проекта**. При доступном
   shell Git: `scripts/bd-read.sh ready`, `list` или `show <id>`.
2. Если shell Git недоступен, через коннектор получить HEAD `beads-backup`, затем файл по
   этому exact SHA. Зафиксировать repository, snapshot SHA и время чтения в PR evidence.
   Для локального разбора сохранить полученные bytes во временный файл вне repo:

   ```bash
   BD_READ_FIXTURE=/tmp/project-beads-snapshot.jsonl scripts/bd-read.sh ready --json
   BD_READ_FIXTURE=/tmp/project-beads-snapshot.jsonl scripts/bd-read.sh show <id> --json
   ```

   `BD_READ_FIXTURE` здесь — способ разбора полученного снимка, не проверка его свежести.
   Не брать `.beads/issues.jsonl` из `main` или другого проекта. Отсутствующий снимок означает
   неизвестное состояние, а не отсутствие задач. Явное `BD_READ_NO_FETCH=1` даёт только
   кэшированное чтение; stale-снимок обозначить в evidence.
3. Добавлять заявки в `.bd-intents/<branch-slug>.jsonl` своей рабочей ветки; коммит и PR
   можно опубликовать через коннектор. Заявка — **pending**, пока оператор не применил её.
   Не объявлять `claim` или закрытие выполненным только по наличию строки в PR.
4. Не ставить `bd` ради создания отдельной облачной базы, не импортировать снимок для
   собственного writer, не править Dolt и не пушить изменённый снимок в `beads-backup`.
5. Недоступность снимка или applier указать как ограничение task state и передать очередь
   оператору; независимую работу над разрешённым кодом/документами продолжать.

### Формат очереди и применение оператором

Project owner формата — установленный `.bd-intents/README.md` и trusted applier.
Совместимый с U2 формат: одна JSON-заявка на строку, уникальные стабильные `intent_id`,
`op`, необязательные `created_at`/`actor`. Очередь append-only; повтор не получает новый ID.

| `op` | Обязательные поля | Дополнительные поля U2 |
|---|---|---|
| `create` | `title` | `handle`, `type`, `priority`, `description`, `assignee`, `acceptance`, `labels`, `notes` |
| `close` | `ref`, `close_reason` | — |
| `update` | `ref` | `status`, `priority`, `assignee`, `type` |
| `dep_add` | `ref`, `blocked_by` | `dep_type` |
| `note` / `comment` | `ref`, `text` | — |

`ref`/`blocked_by` — существующий ID текущего проекта или `tmp:<slug>` из `handle`
предшествующего `create` в том же файле. Не выдумывать будущий Beads ID; forward refs
не разрешены. Пример (ID намерений глобально уникальны; фактические значения создаёт агент):

```jsonl
{"intent_id":"8b109450-6c18-49d1-9c16-9702c66f1a76","op":"create","handle":"tmp:beads-docs","title":"Уточнить доступ к Beads по окружениям","type":"task"}
{"intent_id":"cce16115-672d-48e9-b2f2-dc3c0bb26e08","op":"note","ref":"tmp:beads-docs","text":"Изменения и проверки представлены в PR; применение ожидается"}
```

До включения apply в новом проекте перенести **весь** проверенный набор из frozen U2 source:
`scripts/bd-apply-intents.sh`, `scripts/lib/bd-apply-engine.mjs`, его imports, совместимые
`bd-env.sh`/sync helpers, `.bd-intents/README.md` и соответствующие tests. Проверить closure,
project prefix/receipt paths, совместимость `bd --help`, защиту от stale snapshot, повтора
и частичного исполнения; добавить пути в inventory проекта. Один shell wrapper без движка
не работает. Не копировать базу, runtime receipts, credentials или очереди чужого проекта.
Tooling проходит обычный review/merge до исполнения оператором. Это отдельное изменение,
а не скрытая часть установки документационного дополнения.

При установленном applier оператор из основного checkout использует **доверенную merged
версию скрипта и libraries**; из PR извлекает только данные очереди, во временный файл:

```bash
scripts/bd-apply-intents.sh --dry-run /tmp/reviewed-beads-queue.jsonl
scripts/bd-apply-intents.sh /tmp/reviewed-beads-queue.jsonl
```

Предварительно сверить содержимое очереди с reviewed PR и свежесть основной базы. Не
переключать checkout на недоверенное tooling ради apply. Валидация всей очереди предшествует
мутациям; ошибка валидации даёт ноль мутаций, ошибка исполнения может оставить часть.
Повторять ту же очередь с теми же ID: маркеры в базе обеспечивают идемпотентность, receipt
лишь локальный кэш вне worktree. После успеха проверить реальные ID и опубликованный снимок;
если export не прошёл, отдельно завершить публикацию, даже если повтор apply уже не меняет базу.
В PR записать результат и соответствие `tmp:` реальным ID, удалить применённую очередь
landing-коммитом и выполнить affected checks на новом HEAD. Не удалять очередь до подтверждения.
Merge выполняет оператор. `--no-export` и skip/trust overrides не входят в обычный workflow.

### Ограничение ожидания инструментов

Сетевой вызов должен иметь конечный бюджет (например, 30 секунд); ограничить shell-процесс
можно `.claude/tools/with-timeout.sh 30 <command> ...`. Для коннектора использовать доступный
runtime timeout/yield. Нет ответа — сообщить, сменить канал или передать handoff, не ждать
бесконечно. Timeout записи не доказывает, что записи не было: сначала прочитать branch/PR
и сверить результат, затем решать о повторе. Не повторять мутацию вслепую.

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
Custom runtime hooks проекта сохраняются при upgrade. Codex использует source U2 adapter:
одна repository mutation guard запись, без commit/readiness hook entries и без dispatcher.
Его actual activation и платформенные пределы проверяются отдельно; Claude evidence не является Codex PASS.
