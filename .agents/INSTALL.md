---
title: "Install, upgrade and rollback — OverGate 4 RC"
status: active
version: "4.0.0-rc.1"
date: 2026-10-03
tags: [installation, upgrade, rollback, delivery-first]
---
# Установка и обновление

Единый путь — `scripts/install-overgate.py plan → apply → rollback` из чистого trusted
OverGate **Git checkout с `.git` и exact SHA**. ZIP/tarball release без Git metadata
не является trusted source этого установщика. Получите source через `git clone`, затем
выберите RC tag или полный commit SHA в source checkout. Скрипт ничего не скачивает, не настраивает аккаунты и не публикует GitHub.
Legacy `install-all.ps1`/per-skill scripts не использовать для RC. Stable Dreadnought остаётся
прежним snapshot; RC выбирается явно по release/tag и exact commit SHA. Старые refs не двигать.

Пререквизиты: Git, Bash, Python 3 (3.10+ для reference/native fixtures); jq для finalize, Node.js для Beads snapshot reader и reference
tests, gh для PR evidence. `bd` нужен только проекту, использующему local Beads. Проверяйте
текущий `bd --help`. macOS/Linux deterministic fixtures — граница reference evidence;
На Windows нужен настоящий Git Bash; Python запускается нативно (`py -3` либо `python`),
не через WSL. Windows и live Claude/Codex activation требуют отдельного smoke и не объявляются PASS автоматически.

## Каталог Claude-сессии

Installer читает canonical Git blobs и записывает Bash scripts с LF. Для последующих
checkout сохраните LF этих project-owned путей через политику `.gitattributes` проекта
(например, `*.sh text eol=lf`); чужой `.gitattributes` автоматически не перезаписывается.

Для полного Claude Bash dispatcher запускайте сессию из корня checkout. Новая сессия
в подкаталоге, включая пакет монорепо, работает в режиме восстановления: остальные Bash
команды блокируются до возврата в root. В rc.1 допускается только одна unquoted команда
`cd <absolute-checkout-path>`; допустимые символы пути — латиница, цифры, `_ : / . -`.
Пробелы, кириллица, скобки и кавычки в этой форме не поддерживаются. Для такого пути
завершите сессию и откройте новую непосредственно в корне checkout через интерфейс
runtime/терминала. Root-запуск не зависит от `CLAUDE_PROJECT_DIR`, даже если переменная
указывает на соседний checkout. Исправление recovery paths и внутренних U2-префиксов
отложено в `og-7sr`; rc.1 сохраняет исходную семантику U2 #829.

Codex сохраняет прежний adapter contract; Claude dispatcher evidence не является Codex PASS.

## До копирования

1. Создай рабочую ветку target проекта. Прочитай project authority/context и legacy overrides.
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
ровно пять core skills, thin adapters, hook parser/policy/launcher/timeout/publisher closure,
Beads readers и необходимые instructions. Не копируются каталоги U2, game data, credentials,
Memory Bank, personal runtime state или весь `.claude/skills/`.

AGENTS.md, `.agents/project/verify.sh` и project rules `beads.md`, `tests.md`, `universal.md`
сохраняются. `.claude/rules/large-payloads.md` — managed publication policy: известная v3.9 версия
обновляется вместе с publisher/finalize, а project modification даёт conflict без записи.
Остальные project-owned rules вне inventory не затрагиваются. Settings merge
сохраняет project env/permissions/custom hooks, заменяет только известные old managed hooks и
добавляет required guards; изменённый managed hook даёт conflict. Known v3.9 и previous-RC
entries заменяются по точной JSON identity; custom Bash hooks сохраняются. Ровно одна
managed entry с timeout 600 с вызывает `.claude/hooks/pre-bash.sh` и не содержит backslashes. `.gitignore` сохраняет
project entries и делает исключение для tracked `.codex/hooks.json`; прочий Codex state ignored.
Product authority берётся из project AGENTS; если не назначен — оператор.

v3.9 upgrade сверяет managed files с frozen legacy inventory. Изменённая роль или customized
`.claude/skills/verify/SKILL.md` даёт адресный stop. Сначала перенеси project commands в
`.agents/project/verify.sh` и сохрани custom instructions как project-owned файл в target PR;
затем явно согласуй возвращение managed file к прежнему known baseline, пересоздай план.
Installer не разрешает конфликт за оператора. Fresh verify template намеренно FAIL до заполнения.
Reference `/verify` запускает `scripts/verify-reference.sh`, consumer — реальные project tests.

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
только managed pipeline files, не secrets. После commit — revert upgrade PR и адресно восстанови
saved overrides; команды rollback применимы только к соответствующему snapshot.

Для самого reference возврат к stable — revert candidate PR либо checkout неизменного stable
release/tag в отдельной рабочей ветке. Не передвигай опубликованные теги. RC не становится Latest;
promotion в stable — отдельное решение.
