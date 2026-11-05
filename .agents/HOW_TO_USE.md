---
title: "OverGate — как работать"
status: active
version: "4.0.0-rc.5"
date: 2026-11-05
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

## Начало работы после установки rc.5

Пошаговое поручение — `QUICKSTART.md` в exact source checkout OverGate;
детали для установленного проекта — [INSTALL](INSTALL.md).
Агент заполняет project verify.sh реальными проверками (создаёт минимальные тесты при отсутствии).
После apply в install branch он запускает `bash scripts/og-init-memory-bank.sh`, затем
`bash scripts/og-protect-main.sh`; существующий Memory Bank сохраняется. Коды защиты
2/3/4/5 фиксируются как R8 в target PR и Memory Bank; 6 останавливает. В install PR нет
`bd init`, Beads DB/task ID и записи `beads-backup`. `--no-beads` не ставит Beads closure;
upgrade старого `beads:false` сохраняет режим `none`.

После проверок и operator merge fresh managed install запускают только из чистого
trusted target `main`: `bash scripts/bd-activate.sh` с явным project prefix, реальной
задачей, qualified `bd` 1.2.2, publisher и peer checkout. Успех требует подтверждённых
ID/claim, published SHA и peer read-back.
Без принятой задачи activation останавливается до создания очереди и ID; если writer
недоступен после создания checkpoint, очередь сохраняется pending для `--resume`.
Legacy DB не активируют этим fresh route: preservation, fence известных old writers и
отдельный принятый switch описаны ниже. `bd init` может включить staged index в свой commit;
activation проверяет preconditions до native init. Не очищайте `.beads` при частичном отказе.
Запуск Claude из root: `claude --permission-mode auto`, approved fallback при недоступности auto —
`claude --permission-mode bypassPermissions` вместе с installer --mode bypass; hooks/deny сохраняются.
Режим файлов не доказывает effective runtime; actual Windows/Claude/Codex evidence отдельно.
В --no-beads defer может ссылаться на открытый GitHub issue этого PR repo, проверенный gh.

## Beads: основной checkout, worktree и облачный агент

### Managed v1 — кандидат rc.5

Этот route действует **только после** отдельной регистрации publisher на trusted target
`main`; наличие файлов WI-A в PR или установленном проекте не активирует writer. Регистрацию
готовят `scripts/bd-publisher-setup.mjs` из exact `origin/main` в отдельном publisher checkout
после проверки сохранности прежней базы, очередей и remote `beads-backup`. Qualified `bd`
проверяется по platform/binary hash и native full-field round-trip. Unknown CLI, prefix или
remote state — stop, без `bd init`/restore поверх существующей работы.

После merge fresh install PR оператор запускает `bash scripts/bd-activate.sh` из
чистого trusted `main`, указывая publisher и peer checkout, фактический project prefix,
qualified `bd`, UUID actor, название реальной задачи и новый private `--work-dir`.
До запуска в publisher repo-local Git config должны быть `user.name` и `user.email`
(либо явно заданные service author/committer). Для HTTPS нужен доверенный repo-local
`credential.helper`; для SSH — доступный `SSH_AUTH_SOCK`. Унаследованные global/system
Git config и `GIT_CONFIG_*` не используются для идентичности remote и публикации.
Секреты не записывайте в project config, очередь или PR evidence.

Если preflight остановился до checkpoint, устраните причину и начните новый запуск:
очередь/DB могли ещё не создаться. Если checkpoint уже создан, сохраните его и
очередь в private work directory, а также native DB, если она появилась.
После устранения причины повторите ту же команду с теми же аргументами и `--resume`;
helper сверит exact source/queue/CLI/local DB и remote state. При частичном `bd init`,
порче checkpoint или неизвестном remote сохраните состояние для reviewed recovery,
без удаления `.beads` и слепого повторного init. После публикации успех подтверждает только peer
read-back того же SHA и реального ID.

Агент в основном/linked checkout читает опубликованные задачи через
`bash scripts/bd-read.sh ready|list|show` либо соответствующий read route `bd-wt.sh`.
Reader сверяет managed protocol, ledger и hashes; stale `BD_READ_NO_FETCH=1` отмечается
отдельно. `bd-wt.sh` в managed mode не выполняет прямой `bd update/create/close`.

Из linked worktree или isolated reader агент сохраняет raw typed JSONL как **данные**
в своей рабочей ветке/PR или вне repo. Для публикации он использует зарегистрированный
publisher; выполняемые helper bytes берутся из его trusted `main`, не из PR ветки. В linked
worktree путь доступен через общий local Git config; isolated reader получает путь к уже
авторизованному publisher отдельно. Если пути или доступа нет, очередь остаётся pending:

```bash
publisher="$(git config --local --get overgate.beadsPublisher)"
cd "$publisher"
bash scripts/bd-apply-intents.sh --read-state
bash scripts/bd-apply-intents.sh --prepare --base <published-R> --actor <agent-UUID> \
  --output <private-temp>/queue.v2.jsonl <raw-intents.jsonl>
BD_BIN="$(git config --local --get overgate.beadsCli)" \
  bash scripts/bd-apply-intents.sh <private-temp>/queue.v2.jsonl
```

Перед первым apply в новом пустом target требуется `--bootstrap` с проверенным
preservation manifest; install PR не делает task write. Успех фиксируется только по
`published_sha`, фактическим ID, `claims.confirmed` и чтению того же SHA из второго
авторизованного checkout. При недоступном publisher или conflict очередь остаётся pending
с base/actor/queue hash и причиной; `tmp:` не выдаётся за task ID. Cloud connector может
передать только данные очереди, не выполняя helper. Второй writer из обычного clone не
создаётся. Это WI-A source route; installer/upgrade activation — отдельный WI-B.

Для уже работающего `legacy-v0` проекта этот fresh route не заменяет прежнюю DB.
Порядок WI-B: read-only preservation packet со всеми известными old-writer clones,
reviewed legacy helper upgrade и operator merge, fence каждого clone до первой
managed publication, отдельный принятый `--switch-managed` target PR и merge.
После этого trusted-main publisher setup/bootstrap использует сохранённые frozen
`R` и точный legacy snapshot; typed create→claim и peer readback подтверждают
переход. Reader проверяет весь managed segment от activation marker; старый legacy
snapshot служит базой, а отсутствие/подмена снимка после marker даёт stop.
Неразрешённая pending очередь остаётся у владельца и блокирует switch; автоматический
replay не выполняется. Точные команды и rollback граница — в
[`INSTALL.md`](INSTALL.md#beads-и-облачный-агент).

### Legacy v0 — до managed activation

Следующий порядок относится только к проекту без зарегистрированного managed publisher.
Он сохраняет прежний доступ до принятого managed switch; после fence old-writer
helpers откажут до task mutation. Product authority и project-owned правила сохраняются.
Beads хранит состояние задач; Git/PR — изменения кода и evidence.

### Сначала определить доступ к базе

Класс определяется доступом к живой базе оператора, а не наличием `.git` или `bd` в PATH.
Обычный standalone clone в облаке не становится основным checkout оператора.

| Окружение | Чтение | Запись | Кто публикует снимок |
|---|---|---|---|
| Основной checkout оператора с живой базой | `bd ready`, `bd show <id>` | `bd create/update/close` | Основной checkout через `bash scripts/bd-sync-export.sh` |
| Локальная worktree с доступом к основной базе (embedded или dolt-сервер) | `bash scripts/bd-wt.sh ready/show <id>` | `bash scripts/bd-wt.sh create/update/close` | Основной checkout |
| Облачный агент без основной базы и диска оператора | `bash scripts/bd-read.sh` или снимок через авторизованный GitHub-коннектор | Заявки `.bd-intents/<branch-slug>.jsonl` в рабочей PR-ветке | Оператор после применения заявок |

Скрипты `scripts/bd-*.sh` запускать через `bash`. Прямой запуск файла без аргументов
(`scripts/bd-sync-export.sh`) гейт коммита блокирует: имя на `sh` в позиции команды он
считает оболочкой, которая читает команды со стандартного ввода. Это задокументированное
поведение гейта.

**Граница legacy route:** прямую запись выполняют только известные авторизованные
old-writer clones до fence. После switch действует managed typed queue и trusted publisher
из установленной closure; старую очередь не переносят автоматически. Cloud agent
передаёт данные заявок через PR, но не получает самостоятельный writer.

Single-writer означает одну физическую базу/сервер основного checkout. Несколько клиентов
через `bd-wt.sh` допустимы; отдельная облачная база и самостоятельная публикация снимка — нет.
Guard отличает worktree от checkout, но не удостоверяет оператора или доверенность скрипта.

### Основной checkout оператора

1. Использовать существующую рабочую базу; не создавать вторую поверх неё.
2. Если другая машина опубликовала новый снимок, выполнить `bash scripts/bd-sync-restore.sh`
   до новых мутаций; конфликты состояния сверить с оператором.
3. Выполнять `bd ready`, `bd show <id>`, `bd update <id> --claim`, затем работу по задаче.
4. Публиковать изменения задач через `bash scripts/bd-sync-export.sh`.

Служебная ветка `beads-backup` содержит экспорт `.beads/issues.jsonl`. Живая база первична
для текущей работы, снимок — опубликованное состояние для других сред. Export/restore
запускаются только из основного checkout. Last-seen/drop guards и non-force push сохраняются;
их override не является обычным способом разрешать конфликт. `bd dolt push/pull` не применять.

### Локальная worktree

В worktree использовать обёртку для каждой команды:

```bash
bash scripts/bd-wt.sh ready
bash scripts/bd-wt.sh show <id>
bash scripts/bd-wt.sh update <id> --claim
bash scripts/bd-wt.sh close <id> --reason 'Результат и evidence опубликованы в PR'
```

Обёртка сама подставляет `--db` основной базы по `dolt_mode` из
`<основной checkout>/.beads/metadata.json`: `embedded` → `.beads/embeddeddolt` (сервер не
нужен), `server` → `.beads/dolt` и живой dolt-сервер основного checkout (оператор сначала
запускает там обычную `bd ready`). Нет или невалиден `metadata.json`, пуст или неизвестен
`dolt_mode`, нет каталога базы или исправного Python для чтения файла — отказ до запуска
bd с путём и причиной. Восстановление режима — решение оператора, `.beads/**` руками не
править. Из основного checkout обёртка — прозрачный pass-through без `--db`.

В любом окружении обёртка пропускает только allowlist подкоманд: `ready show list search
blocked children create q update close reopen dep comment comments note label`. Прочие
подкоманды (`delete`, `config`, `sql`, `export`, `import`, `dolt` и т.д.), пустая подкоманда,
неизвестный глобальный флаг до подкоманды, а также `--db`, `-C`/`--directory`, `--global`,
`--ignore-schema-skew`, `--repo`, флаги чтения локального файла (`--body-file`,
скрытый алиас `--description-file`, `--design-file`, `--reason-file`, `--file`, `--graph`, `-f`, `--metadata @файл`) в любой
позиции и непустые `BEADS_DIR`/`BEADS_DB` — отказ кодом 2 до запуска bd. Значение аргумента,
равное такому флагу (`--title -C`), тоже отклоняется — осознанный fail-closed. Длинный текст —
через `--stdin` или `--description`. Allowlist — защитный слой обёртки, а не граница
безопасности: прямой `bd` остаётся доступен в рамках прав сессии.

Прямой `bd` с auto-discovery в worktree может создать пустую базу. Если основной сервер
недоступен, не запускать второй: прочитать снимок и передать оператору заявку. Embedded Dolt
допускает одного писателя за раз: одновременные команды из основного checkout и worktree
могут упасть на блокировке — повторить позже, базу не править. Публикация остаётся в
основном checkout.

### Облачный агент: GitHub-коннектор достаточен

При уже авторизованном GitHub-коннекторе дополнительный login для Git CLI не нужен.
Коннектор и shell Git имеют разные каналы доступа: работа с PR через коннектор не означает,
что `git fetch`/`gh` в контейнере тоже авторизованы. Отказ shell Git не блокирует весь task.

1. Прочитать `.beads/issues.jsonl` **из ветки `beads-backup` текущего проекта**. При доступном
   shell Git: `bash scripts/bd-read.sh ready`, `list` или `show <id>`.
2. Если shell Git недоступен, через коннектор получить HEAD `beads-backup`, затем файл по
   этому exact SHA. Зафиксировать repository, snapshot SHA и время чтения в PR evidence.
   Для локального разбора сохранить полученные bytes во временный файл вне repo:

   ```bash
   BD_READ_FIXTURE=/tmp/project-beads-snapshot.jsonl bash scripts/bd-read.sh ready --json
   BD_READ_FIXTURE=/tmp/project-beads-snapshot.jsonl bash scripts/bd-read.sh show <id> --json
   ```

   `BD_READ_FIXTURE` здесь — способ разбора полученного снимка, не проверка его свежести.
   Не брать `.beads/issues.jsonl` из `main` или другого проекта. Отсутствующий снимок означает
   неизвестное состояние, а не отсутствие задач. Явное `BD_READ_NO_FETCH=1` даёт только
   кэшированное чтение; stale-снимок обозначить в evidence.
3. Добавлять заявки в `.bd-intents/<branch-slug>.jsonl` своей рабочей ветки; коммит и PR
   можно опубликовать через коннектор. Заявка — **pending**, пока trusted publisher
   (либо авторизованный legacy writer до fence) не применил её.
   Не объявлять `claim` или закрытие выполненным только по наличию строки в PR.
4. Не ставить `bd` ради создания отдельной облачной базы, не импортировать снимок для
   собственного writer, не править Dolt и не пушить изменённый снимок в `beads-backup`.
5. Недоступность снимка или writer указать как ограничение task state и передать очередь
   оператору; независимую работу над разрешённым кодом/документами продолжать.

### Очередь и применение

Для managed v1 формат и preconditions задаёт установленный `.bd-intents/README.md`;
применяет только зарегистрированный trusted publisher из exact target `main`.
Облачный агент передаёт данные очереди через PR и не объявляет `tmp:` реальным task ID.
В legacy v0 существующие project-owned заявки остаются pending до reviewed применения
авторизованным old writer. Не переносите U2-specific формат или runtime receipts в
новый проект. После принятого switch старая очередь не replay автоматически.

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



Три guards идут последовательно: repository mutation, PR readiness, project commit tests.
Быстрая фаза сужает окно настоящего `.agents/project/verify.sh` через
`OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS`; явный более узкий override сохраняется.
Custom runtime hooks проекта сохраняются при upgrade. Codex использует source U2 adapter:
одна repository mutation guard запись, без commit/readiness hook entries и без dispatcher.
Его actual activation и платформенные пределы проверяются отдельно; Claude evidence не является Codex PASS.
