---
title: "OverGate rc.5 WI-B — install and activate managed Beads"
status: draft
version: "0.1"
date: 2026-11-05
tags: [overgate, beads, installer, release-candidate]
related:
  - docs/plans/2026-11-03-v4.0.0-rc.5-beads.md
  - .agents/INSTALL.md
  - .agents/PIPELINE_ADR.md
---

# rc.5 WI-B — установка и активация managed Beads

## Цель и граница

Довести уже реализуемый WI-A publisher до установки в новый проект: install PR доставляет
точные байты и выбранный protocol, но не пишет Beads; после merge агент из доверенного
target `main` активирует writer, публикует первую typed задачу и подтверждает её из второго
checkout. Существующая работа Beads и незнакомое состояние останавливают установку до
проверенного preservation. Основание — [план rc.5](2026-11-03-v4.0.0-rc.5-beads.md)
§3 WI-B, AC1/2/7/8/9/10. WI-A source/guard и WI-C Bash recovery не меняются здесь.
Режим **CRITICAL**: installer и migration могут потерять общую task authority.

Это stacked Draft PR к WI-A; implementation начинается после WI-A source acceptance и
синхронизации с его конечным SHA. Реальные U2/Toon/OverGate базы не мигрируются этим PR.

## Target → as-built → gap

| Surface | Сейчас | Target WI-B |
|---|---|---|
| Distribution | Manifest/check-reference ставят legacy Beads reader/wrappers; WI-A publisher не входит в closure | Полный versioned managed closure, byte-exact installed source; `--no-beads` исключает его весь |
| Installer state | `format:2`, `beads` boolean, `manifest_version:4.0.0-rc.4` | Добавлен `beads_protocol: managed-v1 / legacy-v0 / none`; выбор protocol не выдаёт activation |
| Fresh target | Инструкция запускает `bd-bootstrap.sh` и legacy snapshot из install branch | PR не делает `bd init`/Beads write; post-merge trusted target main запускает `bd-activate.sh`, затем typed create→claim→publish→peer read-back |
| Existing target | Installer видит свои managed bytes, но не полное local/remote/pending Beads состояние | До записи read-only inventory/frozen R; unknown/legacy/pending → fail-closed preservation packet, никакой silent migration |
| Upgrade/rollback | Byte rollback managed files; старый writer может остаться | Legacy остаётся до явно принятого перехода; retained queues/receipts/DB сохраняются, все известные writers fenced до первой managed publication, rollback только до неё |

## Поставка

1. Добавить closure WI-A в `.agents/distribution-manifest.json` и
   `scripts/check-reference.py` с зависимостями, режимами и порядком установки;
   тест должен краснеть при удалении любого import/helper. `--no-beads` исключает
   весь Beads closure и не добавляет Beads rule в project-owned `AGENTS.md`.
   Сохранить прежние project hooks/settings/verifier, Memory Bank и main protection.
2. В `scripts/install-overgate.py plan/apply` записать выбранный protocol в plan и
   tracked `.overgate/install-state.json`. Fresh Beads → `managed-v1`, fresh
   `--no-beads` → `none`, старый state без protocol с `beads:true` → `legacy-v0`,
   с `beads:false` → `none` без добавления Beads closure.
   Установка байтов не означает, что writer зарегистрирован. При upgrade
   `legacy-v0` не переключается молча; `none` не превращается в Beads mode.
3. Перед **любой target записью** inventory читает `.beads`/Dolt metadata,
   `origin/beads-backup` (включая fetch error), `.bd-intents/`, receipts/queues,
   registered writers и локальные overrides. Plan сохраняет точные статусы,
   hashes и frozen R; apply повторяет чтение и останавливается при drift.
   Подтверждённо пустой target допускает install; существующий/неизвестный state
   возвращает preservation packet с причиной и никакой Beads init/restore/export.
   `--no-beads` также не трогает обнаруженную существующую Beads работу.
4. Добавить `scripts/bd-activate.sh` и минимальные необходимые helpers: команда
   работает только в exact trusted target `main` после operator merge install PR,
   проверяет installed closure/source SHA, `managed-v1` state, origin/local
   verified-absent inventory, qualified native CLI и project prefix. Затем
   использует WI-A setup/bootstrap; первую typed create→claim→publish выполняет по
   принятой задаче проекта с явно переданными title/actor, не создавая sample-task,
   сообщает настоящий ID/ `claims.confirmed`/ `published_sha` и требует peer read-back.
   Если actor/publisher недоступны, сохраняет queue/base/actor и точный blocker;
   `tmp:` не считается готовой задачей. Никаких PR-branch publisher writes.
5. Для rc.4 upgrade сделать read-only preservation packet: frozen remote R,
   local DB/queues/receipts/config/hooks/writers, immutable bytes+SHA256 и
   disposable rehearsal. Unknown/unreconciled pending state блокирует activation;
   доказанный retained pending state допустим только при сохранении его bytes,
   владельца и очереди для отдельного разрешения без silent replay. Для
   подтверждённого clean/retained перехода protocol меняется только в отдельном
   target PR после просмотра packet и operator merge. До первой managed publication
   все известные авторизованные old writers в других клонах получают проверенный
   shared guard/fence; неизвестный writer или незащищённый clone — stop. Test
   показывает отказ old writer до publication, после неё и отсутствие task loss.
   Activation следует из trusted main. До первой managed publication возможен
   installer rollback; после неё old writer не возобновляется, ledger/snapshot
   сохраняются.
6. Обновить `QUICKSTART`, README, INSTALL/HOW_TO_USE, template и CHANGELOG:
   fresh install PR без Beads ID, порядок после merge, actual task ownership,
   writer-unavailable queue/blocker, safe upgrade. Не переносить U2-specific
   state и не превращать оператора в routine task applier.

## Verification Contract

| AC | Условие принятия | Метод |
|---|---|---|
| B1 | Fresh install plan/apply на рабочей ветке ставит полный byte-exact managed closure и `managed-v1`, без `bd init`, DB/remote publication; `--no-beads` и rc.4 `beads:false` upgrade сохраняют `none` без Beads closure | Disposable before/after bytes, rc.4 no-Beads upgrade + mutation-negative manifest fixtures |
| B2 | Unreviewed existing/unknown local/remote/pending state или drift между plan/apply останавливаются до первой записи; fetch failure не равна absent | Fresh target со старым Beads, queued intents, bad remote, symlink/path/permission negatives |
| B3 | Только после merge exact trusted target main activation проверяет installed source/prefix/CLI, делает verified-absent bootstrap и typed create→claim→update→close с real ID, confirmed claim, published SHA и peer read-back | Native Windows/macOS/Linux fresh two-clone project + pre-merge negative |
| B4 | Legacy rc.4 upgrade сохраняет DB/queues/receipts/remote R и writer hooks; `legacy-v0` не переключается молча; retained pending не replay автоматически; все известные old writers fenced в авторизованных клонах до первой managed publication, unknown writer стоп; rehearsal+separate accepted switch, rollback до первой publication без потери task state | Disposable populated/empty/pending upgrade, two-clone old-writer negative до/после publication, immutable inventory and byte rollback |
| B5 | Project-owned AGENTS/rules/settings/hooks/verifier, Memory Bank и main protection сохраняются; linked/isolated/writer-unavailable дают опубликованный результат или точный queue/blocker | Installed Claude/Codex sessions, routes and negative cases |
| B6 | Final WI-B HEAD проходит `verify-reference.sh`, CI Linux/macOS/Windows, installed verifier и trusted finalize; native writer и `NOT RUN` названы раздельно | Exact-SHA logs/PR evidence and affected recheck |

**Named risks:** I1 потеря старой/pending task state; I2 переключение до trusted merge;
I3 неполный installer closure или `--no-beads` leak; I4 ложная успешная activation без
peer SHA; I5 project-owned override/rollback loss; I6 невалидный CLI/prefix/OS;
I7 old writer после первого managed publish.

**Rollback:** до первой managed publication штатный byte rollback установленного closure
и reviewed publisher setup rollback, не трогая `.beads`/queues/remote. После публикации
остановить запись и сохранить ledger/receipts/snapshot; старый export/restore не запускать,
восстановление только отдельным reviewed plan. Merge кода и acceptance риска — оператор.
