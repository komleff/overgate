---
title: "Install, upgrade and rollback — OverGate 4 RC"
status: active
version: "4.0.0-rc.5"
date: 2026-11-05
tags: [installation, upgrade, rollback, delivery-first]
---
# Установка и обновление

Единый путь — `scripts/install-overgate.py plan → apply → rollback` из чистого trusted
OverGate **Git checkout с `.git` и exact SHA**. ZIP/tarball release без Git metadata
не является trusted source этого установщика. Получите source через `git clone`, затем
выберите RC tag или полный commit SHA в source checkout. Скрипт ничего не скачивает, не настраивает аккаунты и не публикует GitHub.
Legacy `install-all.ps1`/per-skill scripts не использовать для RC. Stable Dreadnought остаётся
прежним snapshot; RC выбирается явно по release/tag и exact commit SHA. Старые refs не двигать.

Windows Git for Windows обычно checkout'ит текст с CRLF через system `core.autocrlf=true`,
а trusted installer/publisher игнорирует system/global Git config. Для установки
создайте **оба** source OverGate и target project как новые LF clone:
`git clone -c core.autocrlf=false '<repo-url>' '<checkout-path>'`. Локальная настройка
записывается до checkout. После merge publisher и peer создаются такими же новыми
LF clone; перед activation сверьте `git config --local --get core.autocrlf` = `false`
в source/target/publisher/peer и чистый tracked status. Для fresh checkout без
Beads state при CRLF drift сохраните работу и создайте новый LF clone; не делайте
`reset`, `clean` или in-place смену Git config. Если **любая** Beads DB, queue,
receipt или local-only task state уже существует, оставьте старый checkout и
сначала выполните B4 reviewed inventory/preservation всех известных writers.
Новый clone не заменяет и не переносит эту базу/очередь; switch только отдельным
принятым PR после fence, неизвестное состояние — stop.

Пререквизиты: Git, Bash, Python 3 (3.10+ для reference/native fixtures); jq для finalize, Node.js для Beads snapshot reader и reference
tests, gh или авторизованный коннектор для PR evidence. `bd` 1.2.2 обязателен для post-merge
Beads activation; `--no-beads` — для разовых проектов. Для публикации первого `beads-backup`
нужен отдельный авторизованный Git push; helper не скачивает bd, его ставит агент по ОС. Проверяйте
текущий `bd --help`. macOS/Linux deterministic fixtures — граница reference evidence;
На Windows нужен настоящий Git Bash; Python запускается нативно (`py -3` либо `python`),
не через WSL. Windows и live Claude/Codex activation требуют отдельного smoke и не объявляются PASS автоматически.

### Beads и облачный агент

Fresh Beads install ставит полный managed closure и `beads_protocol: managed-v1` без
создания DB или задачи в install PR. Существующий rc.4 Beads target остаётся
`legacy-v0` до отдельного reviewed перехода; `--no-beads` ставит `none`.
Не применять managed publisher из install PR или поверх существующей базы без этого перехода.

Fresh `managed-v1` install PR ставит только source bytes. После merge activation из
trusted target `main` использует тот же вход в Git, что и обычный `git push` пользователя:
`user.name`/`user.email` из Git config (или явную service identity) и HTTPS
`credential.helper` (osxkeychain, `gh auth setup-git`, Git Credential Manager) либо SSH
remote с `SSH_AUTH_SOCK`. Ручная repo-local настройка не нужна. Из global/system config
переносятся только `credential.*`, `user.name`, `user.email` и только в сетевые вызовы
(`ls-remote`/`fetch`/`push`) и `commit-tree` снимка; origin, `url.*.insteadOf`, alias,
hooks и `GIT_CONFIG_*` вызывающего не влияют (ADR §3.39). Installer читает remote проекта
тем же способом. Отсутствующая identity/auth останавливает setup до task write;
`bash scripts/lib/bd-env.sh --diagnose ls-remote` показывает найденные ключи без значений.
Не сохраняйте credentials в репозитории или отчёте.
Если activation остановилась после native init/setup, сохраните DB, private work
directory и очередь; тот же вызов `bd-activate.sh --resume` сверяет checkpoint и
продолжает. Частично созданная DB без полного checkpoint требует reviewed recovery,
а не удаления `.beads` или автоматического rollback.

Для существующего `legacy-v0` target fresh `bd-activate.sh` не применяют. Сначала
перечислите все известные авторизованные standalone old-writer clones и создайте
read-only packet на их точных bytes:

```bash
python3 /trusted/overgate/scripts/bd-upgrade-preserve.py --target /project \
  --writer-root /project --writer-root /other-known-clone \
  --bd-bin /qualified/bd --actor <agent-UUID> \
  --outcome verified-clean --output /private/legacy-packet.json
```

Packet и snapshot остаются вне репозитория. `pending-retained` сохраняет очередь
и владельца, но блокирует switch до отдельного разрешения. Сверьте frozen `R`,
native export каждого clone, DB/queue/receipt/config/hooks, fetch и все push URL
origin. Каждый push destination должен показывать те же `main` и task `R`, что
fetch; plan/apply заново сверяют frozen Git snapshot и native local export,
включая pending и executable mode hook. Unknown/unupgraded writer, drift либо
неполный список — stop. Сначала
установите проверенную legacy helper closure во всех перечисленных клонах через
отдельный project PR, выполните operator merge и обновите клоны до одного trusted
`main`. Повторно создайте packet и включите fence до первой managed publication:

```bash
python3 /project/scripts/bd-upgrade-fence.py --packet /private/legacy-packet.json
```

Fence блокирует штатные old-writer helpers в этих клонах до task mutation и
публикации, включая период после switch. После fence создайте **новый** private
packet тем же read-only вызовом; он связывает исходный packet SHA с неизменным
task state и установленными fence receipts. Отдельный reviewed target PR с
`install-overgate.py plan --preservation /private/post-fence-packet.json
--switch-managed` меняет installed protocol/closure только после принятого packet;
`--preservation` без `--switch-managed` оставляет `legacy-v0`. После operator merge
используйте trusted-main WI-A `bd-publisher-setup.mjs` и
`bd-apply-intents.sh --bootstrap` с frozen legacy `R` и verified-clean manifest,
затем реальную typed очередь и peer readback того же published SHA/полного task
state. До первой publication installer rollback возможен при точном checkpoint;
после неё откат protocol запрещён. DB и pending intents не удаляются.

Fresh `bd-activate.sh` принимает явный project prefix только после merge install PR,
сверяет его с фактическим native `bd` после подтверждённо пустой инициализации.
Перед последующей работой проверьте effective prefix, опубликованный snapshot и
peer read-back. Existing DB/config этим fresh route не переписывается; при
неизвестном состоянии — stop.

Порядок для трёх окружений — [`HOW_TO_USE.md`, секция Beads](HOW_TO_USE.md#beads-основной-checkout-worktree-и-облачный-агент).
`bd`/Dolt нужны основному checkout оператора; облачному агенту достаточно снимка задач и
канала публикации PR, включая уже авторизованный GitHub-коннектор. Авторизация shell
Git/gh не является обязательным шагом для этого канала.
Managed install содержит reader, typed queue и applier, но writer запускается только через
зарегистрированный trusted publisher после отдельной post-merge activation. До регистрации
заявки pending. Не инициализировать облачную базу.
В `legacy-v0` локальная worktree и агент основного checkout работают через
`bash scripts/bd-wt.sh`: база
выбирается по `dolt_mode` из `.beads/metadata.json` (embedded или dolt-сервер), проходит
только allowlist подкоманд, флаги смены базы/каталога и чтения файла отклоняются; чтение
`metadata.json` идёт через `.claude/tools/run-python.sh`. Скрипты `scripts/bd-*.sh`
запускать через `bash`: прямой запуск файла без аргументов блокирует гейт коммита.
При upgrade `AGENTS.md` и `.claude/rules/beads.md` сохраняются: явно сверить их Beads route
с этой инструкцией в target PR. Наличие обновлённой инструкции не обновляет preserved
project rules автоматически: правила запуска `bash scripts/bd-*.sh` и класса локального
окружения (allowlist, embedded/server) перенести в них вручную по diff reference-файлов
между exact source SHA прежней и новой установки. Изменённые проектом managed
`scripts/bd-wt.sh` и `scripts/lib/bd-env.sh` дают адресный conflict по каждому файлу, а не
тихую перезапись; решение — в target PR. Существующий applier и его project policy не
перезаписывать.

## Каталог Claude-сессии

Installer читает canonical Git blobs и записывает Bash scripts с LF. Для последующих
checkout сохраните LF этих project-owned путей через политику `.gitattributes` проекта
(например, `*.sh text eol=lf`); чужой `.gitattributes` автоматически не перезаписывается.

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



Codex сохраняет source U2 adapter: один repository mutation guard, без commit/readiness
hook entries и без dispatcher. Exact known previous-RC Codex entries заменяются, custom Bash
hooks сохраняются; изменённая managed запись требует разрешения конфликта в target PR.
Claude dispatcher evidence не является Codex actual activation PASS.

## До копирования

1. До plan проверь доступ для target Draft PR: `gh auth status` при shell `gh` либо
   авторизованный GitHub-коннектор. Отдельно подготовь post-merge Git transport,
   если выбран Beads; отсутствие shell `gh` не принуждает к `--no-beads`.
   Если репозитория нет, создай его с первым README-коммитом в main при создании репозитория
   (без agent push в main), затем создай рабочую ветку target проекта. Прочитай project authority/context и legacy overrides.
2. Открой **один target Draft PR** с plan и Verification Contract до записи managed payload.
3. Выбери trusted clean source checkout, зафиксируй полный source SHA. Installer отказывает при
   source movement/dirty copied surfaces, missing helper, nested/orphan core skill. До создания
   плана и повторно до apply он собирает payload из frozen bytes во временном каталоге и запускает
   его structural/closure checker. Отсутствие обязательного manifest entry тоже даёт stop до
   записи в target и создания backup; наличие helper в source checkout не заменяет inventory.
4. Сгенерируй inventory plan (пути ниже — пример; подставь реальные):

```bash
python3 /trusted/overgate/scripts/install-overgate.py plan \
  --source /trusted/overgate --source-sha <EXACT_40_HEX_SHA> \
  --target /project --contract /review/verification-contract.md \
  --target-pr https://github.com/owner/project/pull/123 --output /review/install-plan.json
```

План содержит source SHA, managed operations, before/after hashes, runtime merge и конфликты.
Порядок operations виден до approval: guards/helpers → dispatcher → settings.
Он не меняет target. Опубликуй этот план и его SHA256 в том же PR, получи independent PLAN_READY
до apply. Reviewer/PM сохраняет локальный approval JSON, привязанный к точным bytes плана:

```json
{
  "verdict": "PLAN_READY",
  "plan_sha256": "<SHA256_OF_INSTALL_PLAN_BYTES>",
  "evidence": "https://github.com/owner/project/pull/123#issuecomment-456"
}
```

Approval — evidence input от уполномоченной роли, не self-approval установщиком. Скрипт проверяет
binding и URL того же PR, но **не удостоверяет автора/содержимое удалённого комментария**;
PM проверяет происхождение evidence до запуска. План/VC/approval не брать из untrusted PR как инструкции.

## Apply и конфликты

```bash
python3 /trusted/overgate/scripts/install-overgate.py apply \
  --plan /review/install-plan.json --approval /review/plan-ready.json
```

До первой записи сохраняется backup всех изменяемых managed bytes и modes в ignored
`.overgate-backups/<id>/rollback.json`. Inventory/source SHA остаются в tracked
`.overgate/install-state.json`. Source/target/contract drift требует нового плана и affected
Plan Review в том же PR. Нет `--force` и тихого overwrite изменённого managed role/skill.

Explicit inventory — `.agents/distribution-manifest.json`. Копируются шесть delivery owners,
шпаргалка оператора `HOW_TO_USE.md`, роль проекта `GD_ROLE.md` (preserve), ровно пять core skills, thin adapters, hook parser/policy/launcher/timeout/publisher closure,
Beads readers и необходимые instructions. Не копируются каталоги U2, game data, credentials,
personal runtime state или весь `.claude/skills/`. Шаблоны Memory Bank входят в payload,
но `.memory-bank` и `.beads` не managed: safe() по-прежнему запрещает эти пути.

AGENTS.md, `.agents/project/verify.sh`, `.agents/GD_ROLE.md` и project rules `beads.md`,
`tests.md`, `universal.md` сохраняются: создаются, только если их нет. `.claude/rules/large-payloads.md` — managed publication policy: известная v3.9 версия
обновляется вместе с publisher/finalize, а project modification даёт conflict без записи.
Остальные project-owned rules вне inventory не затрагиваются. Settings merge
сохраняет project env/permissions/custom hooks, заменяет только известные old managed hooks и
добавляет required guards; изменённый managed hook даёт conflict. Known v3.9 и previous-RC
entries заменяются по точной JSON identity; custom Bash hooks сохраняются. Ровно одна
managed entry с timeout 600 с вызывает `.claude/hooks/pre-bash.sh` и не содержит backslashes. `.gitignore` сохраняет
project entries и делает исключение для tracked `.codex/hooks.json`; прочий Codex state ignored.
Product authority берётся из project AGENTS; если не назначен — оператор.

### Запись settings и `.gitignore`

Для custom settings (`.claude/settings.json`, `.codex/hooks.json`) из source переносятся только
`hooks.PreToolUse` и `permissions.deny`. `permissions` и его поля создаются, только если они
есть в source: Codex adapter `permissions` не получает. Правило записи результата merge:
1. по смыслу равен source → записываются байты source;
2. иначе равен текущему файлу проекта → файл не меняется побайтно;
3. иначе — JSON в порядке ключей файла проекта, новые ключи в конце, `indent=2`, без
   сортировки ключей, UTF-8 без `\u`-экранирования, финальный LF.

«По смыслу» — строгое по типам сравнение распарсенного JSON: `true`, `1` и `1.0` различаются.

`.gitignore` (managed fragment `.agents/templates/gitignore.fragment`):
- сначала удаляется legacy-строка `.codex/` (v3.9) вместе с её EOL, прочие байты сохраняются;
- блок фрагмента ищется построчно без учёта EOL: CRLF и LF равны, отсутствие перевода строки
  в конце файла не считается отличием;
- файла нет или он пуст → ровно байты фрагмента;
- целый блок уже есть в любом месте → файл не меняется; несколько целых блоков → первый
  остаётся, повторные удаляются, прочие байты не меняются;
- заголовок `# OverGate personal state (managed fragment)` вне целого блока →
  `conflict: managed .gitignore fragment modified; resolve in target PR`, без записи. Это новое
  поведение upgrade с rc.3 (прежде дописывался второй фрагмент): в target PR верните блок к
  фрагменту source или удалите изменённый блок, затем пересоздайте план;
- фрагмента нет → байты файла сохраняются, недостающий перевод строки в конце добавляется,
  затем пустая строка и фрагмент в EOL файла: CRLF, если все строки CRLF, иначе LF.

Повторный `plan` сразу после `apply` даёт operations только с `before == after`.
**Граница:** побайтное соответствие managed- и settings-файлов source после upgrade заявлено
для точных установок rc.1–rc.3 без project overrides. Для upgrade v3.9 оно не
заявляется: settings merge переносит из source только hooks и `deny`.

v3.9 upgrade сверяет managed files с frozen legacy inventory. Изменённая роль или customized
`.claude/skills/verify/SKILL.md` даёт адресный stop. Сначала перенеси project commands в
`.agents/project/verify.sh` и сохрани custom instructions как project-owned файл в target PR;
затем явно согласуй возвращение managed file к прежнему known baseline, пересоздай план.
Installer не разрешает конфликт за оператора. Fresh verify template намеренно FAIL до заполнения.
Reference `/verify` запускает `scripts/verify-reference.sh`, consumer — реальные project tests.

## Выбор runtime

Установка доступна из Codex и Claude Code: откройте target project root в выбранном runtime,
подтвердите загрузку проектных hooks. Claude-specific auto/bypass startup ниже относится только
к Claude Code; permissions Codex этим пакетом не меняются, отдельная Claude binary для Codex не нужна.
Одинаковые роли, helper/checker/finalize executable и Verification Contract применяются в обоих;
реальная activation фиксируется отдельно, static fixtures её не заменяют.

## Режимы rc.5 и helpers

`plan --mode auto` / `--mode bypass` выбирает source вариант; bypass отличается ровно значением
`defaultMode`. Без флага fresh выбирает auto. Канонические строгие JSON fingerprints manifest
распознают source rc.1–rc.3, текущий source и bypass; известный старый source обновляется на auto
с сообщением смены режима. Текущий source/bypass без флага сохраняется; явный флаг переключает.
Custom settings без флага сохраняют permissions/defaultMode/env/language и печатают это в plan;
с --mode — stop: режим проекта со своими settings меняется вручную в target PR.
Install-state mode — auto/bypass/custom, при следующих RC известный mode сохраняется.
Codex артефакт пустого permissions.deny снимается; прочие project keys сохраняются.

Для фактического старта из root используйте `claude --permission-mode auto`. Current Claude Code
может игнорировать auto/bypass из project settings, поэтому file bytes не являются evidence режима.
Недоступный auto проявляется Manual/ошибкой/рутинными вопросами; пересоздайте plan с --mode bypass
и запускайте `claude --permission-mode bypassPermissions`. Global/user settings не меняются.
R6: если доступный auto блокирует штатный pipeline, записать FAIL в PR и передать оператору,
не скрывать отказ bypass-перезапуском. [Primary runtime docs](https://code.claude.com/docs/en/permission-modes).

`plan --no-beads` исключает всю Beads closure и Beads-блок AGENTS template.
Memory Bank создаётся всегда. При upgrade прежний `beads:false` остаётся `none`,
`legacy-v0` остаётся legacy до отдельного preservation/fence/accepted `--switch-managed`;
смена `none` на Beads не выполняется. Старый/отсутствующий/нечитаемый state checker/finalize трактуют как beads:true. Unreadable state
самого installer требует устранения ошибки, не разрешает новую установку поверх неизвестной.
Triage без Beads принимает только открытый существующий GitHub issue этого PR repo (#N или URL),
проверенный gh issue view; PR/foreign/closed/malformed/missing gh — stop.

После apply в install branch выполняются:

```bash
bash scripts/og-init-memory-bank.sh
bash scripts/og-protect-main.sh
```

Memory helper создаёт шесть файлов из templates только при отсутствующем каталоге;
существующий даже частичный — no-op со списком недостающих файлов. Install PR не
инициализирует Beads DB, не создаёт task ID и не публикует `beads-backup`. Fresh
managed activation — только после operator merge из trusted target `main`, по секции
«Beads и облачный агент». Для legacy нужен отдельный accepted switch; `bd-bootstrap.sh`
остаётся legacy recovery helper, не install step.

Protection helper запускается после появления main на GitHub. Поручение на установку подтверждает
эту удалённую запись (§3.33): PR required (0 approvals), enforce_admins:true, force/delete:false.
Более строгие classic rules сохраняются; readback обязателен. Коды 2 (нет admin), 3 (нет gh auth),
4 (тариф private repo), 5 (ruleset, сверить правила) позволяют продолжить только с записью R8
в target PR и уже созданном Memory Bank; code6 — stop. Коды2/3/4 не обеспечивают remote protection,
code5 не изменяет ruleset. R7/og-9ic.10 прямого снятия защиты API остаётся вне WI-1.

Tracked state format2 содержит source_sha, manifest_version, mode, beads и installed relative
paths/hashes; legacy state rc.1–rc.3 читается. Абсолютный backup path только в ignored journal,
apply печатает его, rollback принимает --backup явно. Approval привязывается к plan modes тоже:
apply пересобирает exact plan и останавливает drift.
Агент заполняет verify.sh реальными project tests, при их отсутствии создаёт минимальные.
Реальные Windows/Claude/Codex и native activation receipts проверяются отдельно;
reference unit-тесты не заменяют их. FINAL указывает trusted SHA, SKILL blob и final PR
HEAD; mismatch stop, self-certification запрещена.

## Проверка и завершение

Запусти `python3 scripts/check-reference.py` в target и `bash .agents/project/verify.sh`.
Проверь реальные runtime hooks в свежей сессии доступного Claude/Codex; static wiring не является
live activation proof. QA → один scoped Review → landing → current checks → один `/finalize-pr`.
Evidence в PR, merge выполняет оператор. Missing WHAT/Important/Critical known risk не принимается
агентом. Обычные большие reports идут через `.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py`;
readiness — только trusted finalize. Новый governance package проверяется prior trusted bootstrap.

## Rollback

```bash
python3 /trusted/overgate/scripts/install-overgate.py rollback \
  --target /project --backup /project/.overgate-backups/<id>/rollback.json
```

Rollback сравнивает current managed hashes с installed state: последующая правка даёт stop,
чтобы не потерять работу. Затем восстанавливает исходные bytes/modes или удаляет только созданные
managed files. Обратный порядок сначала возвращает settings, затем удаляет новый
dispatcher. Apply не является multi-file atomic update; при ошибке используется сохранённый
journal и тот же обратный порядок. Project overrides, Beads и Memory Bank не откатываются вслепую. Backup содержит
только managed pipeline files, не secrets. Rollback применим сразу после apply, до helpers
и project правок; install-state восстанавливается побайтно (fresh — удаляется). После helpers
или изменений — revert install PR. Memory Bank, база Beads, beads-backup и GitHub protection
не снимаются автоматически: решение принимается отдельно в target PR.

Для самого reference возврат к stable — revert candidate PR либо checkout неизменного stable
release/tag в отдельной рабочей ветке. Не передвигай опубликованные теги. RC не становится Latest;
promotion в stable — отдельное решение.

Fresh managed Beads prefix задаётся явно при post-merge activation и сверяется с
native CLI/project-owned pin. Существующие база и task ID не меняются.
