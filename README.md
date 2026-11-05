# OverGate

**Ваш проект должен жить дольше одного чата с ИИ.**

Переносимый AI-пайплайн разработки для оператора, который задаёт цель и принимает результат.
Delivery First связывает принятую спецификацию, реализацию, независимую QA и один scoped Code Review.

Начните с [QUICKSTART — первого проекта с агентом](QUICKSTART.md).

**Текущий candidate: v4.0.0-rc.5 (managed Beads, установка и восстановление пути).**
Опубликованный `v4.0.0-rc.4.1` остаётся отдельным prerelease; Stable Dreadnought
сохраняет прежний snapshot `466ad20` и статус Latest. Здесь живёт generic reference из
[U2](https://github.com/komleff/u2), без его product/game data.

```text
Accepted WHAT → plan + Verification Contract → PLAN_READY
→ implementation/tests → QA → one scoped Code Review
→ affected blocker fix → landing + fresh checks → one finalize → operator merge
```

FAST подходит для безопасных docs/content/parameters; PRODUCT — обычная feature;
CRITICAL — явно названный высокий риск. Бюджет independent verifier launches: **2 / 5 / 6**.
External review доступен по named risk или прямому запросу. Advisory не создаёт автоматическую
правку, а движение base при доказанной эквивалентности содержания не требует нового LLM review.

| Слой | Владелец |
|---|---|
| Doctrine/lifecycle | [PIPELINE_ADR §§3.28–3.33](.agents/PIPELINE_ADR.md), [краткая карта](.agents/PIPELINE.md) |
| Шесть delivery roles | [PM, SV, PL, DEV, QA, RV](.agents/AGENT_ROLES.md) |
| Пять core skills | [canon-router, product-gap, product-handoff, diagnose, handoff](.agents/SKILLS.md) |
| Project authority | AGENTS.md установленного проекта; fallback — оператор |
| Runtime adapters | `.claude/`, `.codex/hooks.json` |
| Distribution | [explicit inventory](.agents/distribution-manifest.json), [установка и rollback](.agents/INSTALL.md) |

Поручите агенту: «Установи OverGate в этот проект по `.agents/INSTALL.md`, сохрани
мою product authority, команды тестов и custom hooks; подготовь target Draft PR».
Source нужен как чистый **Git checkout**, полученный через `git clone` с выбранным RC tag
и exact commit SHA; распакованный release ZIP без `.git` installer не принимает.
Нужны Git, Bash (на Windows — Git Bash), Python 3; `gh` или коннектор для PR, Node.js для Beads reader,
jq для finalize. Квалифицированный `bd` 1.2.2 нужен для Beads activation; облачный
агент читает опубликованный снимок и передаёт typed заявки через Git/PR, в том
числе через авторизованный GitHub-коннектор. Для PR через коннектор отдельный
login Git CLI не нужен; post-merge publisher требует авторизованный Git push.
[Порядок доступа к Beads](.agents/HOW_TO_USE.md#beads-основной-checkout-worktree-и-облачный-агент)
различает основной checkout, linked worktree и isolated reader.

Начните с [инструкции работы](.agents/HOW_TO_USE.md) или [установки](.agents/INSTALL.md).
Установщик сначала создаёт plan/inventory на frozen source SHA. Target Draft PR, Verification
Contract и независимый PLAN_READY предшествуют копированию. Project owner, tests, context и
runtime overrides сохраняются; conflict останавливает upgrade. Backup позволяет вернуть исходные
managed bytes. Агент заполняет project tests (при отсутствии создаёт минимальные); шаблон до этого намеренно не проходит.
После apply агент создаёт Memory Bank, настраивает и проверяет защиту main. Fresh install PR не
создаёт Beads DB, task ID или `beads-backup`: после operator merge отдельный
`bd-activate.sh` из доверенного target `main` публикует реальную задачу с peer
read-back. Для существующего `legacy-v0` нужен preservation packet, fence всех
известных старых writers и отдельный принятый switch; `--no-beads` оставляет режим `none`.
Режим --mode auto/bypass сопровождается явным запуском Claude --permission-mode; file settings
не доказывают эффективный режим. Код helper защиты 2/3/4/5 требует записи R8 в PR и Memory Bank;
6 — stop. Живые Windows/Claude/Codex receipts остаются отдельной границей.

Для reference: Git, Bash, Python 3, Node.js и jq; `bash scripts/verify-reference.sh` выполняет
структурные, parser/guard/publisher, activation, fresh/upgrade/rollback и Beads fixtures.
Для PR publication используется gh; для local Beads — bd по правилам проекта. External tooling
не настраивает аккаунты автоматически и не требует конкретного модельного профиля.

Local guards проверяют shell-команды; они не защищают remote connectors. Защита main включается
на GitHub, а merge выполняет оператор. Static adapter fixtures не доказывают activation в любом
runtime. Windows и live Claude/Codex activation требуют отдельного smoke; accepted-risk validation
в finalize остаётся ручной. Точные платформенные результаты и declared limits публикуются в candidate PR.

Лицензия OverGate — [MIT](LICENSE), copyright Dmitriy Komlev. [Credits и provenance](.agents/REFERENCES.md)
отделяют источники идей от перенесённых файлов и не распространяют MIT автоматически на весь U2.

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
[CLI options](https://code.claude.com/docs/en/cli-reference). Из подкаталога checkout
с dispatcher в canonical Git root отказ печатает одну shell-safe команду
`cd '<canonical-root>'`; скопированная целиком команда проходит тот же parser для путей
с пробелами, кириллицей, скобками и апострофами. Допустим также прежний unquoted
`cd <absolute-checkout-path>` для простого ASCII-пути. Tail, substitution, relative path
и второй checkout при доказанном cwd-root блокируются до исполнения. Если cwd-root
не доказан (включая вне Git), hook не угадывает сложный путь: начните новую сессию
непосредственно из корня нужного checkout. Прежний простой unquoted absolute `cd`
к target с dispatcher при этом остаётся разрешённым. После отдельного вызова `cd`
проверьте в следующей Bash-команде, что runtime сохранил cwd. Root-запуск не зависит
от `CLAUDE_PROJECT_DIR`, даже если переменная указывает на соседний checkout.
