# Progress

## Grill — implementation candidate (2026-11-12)

По прямому поручению оператора добавлен optional explicit-use `grill`; frozen source,
MIT и [проверка переноса](../docs/baselines/2026-11-12-grill-import.md) сохранены.
Детерминированные targeted fixtures PASS; behavioral RED без skill / GREEN с ним;
scoped Code Review APPROVED0/0. Full suite/CI/merge фиксируются в delivery PR отдельно.
Установленные проекты и их task state не менялись, live discovery не заявлен.

## og-4py rc.5.2 — обычный вход в Git для Beads, реализация (2026-11-10)

PR #20, ветка `fix/og-4py-beads-credentials`, план v0.5 PLAN_READY. Сетевые вызовы Beads
(legacy sync, reader, bd-wt, managed publisher, activation, upgrade, installer) получают
перенос `credential.*`/`user.*` из пользовательского config; прочее — полная изоляция
(ADR §3.39). RED → GREEN тестами `bd-network-git`, preflight, B-09 chains. Pending: QA
(живые B-01/B-01a на Mac, B-08 на Windows через диагностический режим), Code Review, CI,
finalize, merge, release rc.5.2 вместе с PR #19.

## og-bo6 + og-cfx rc.5.1 — готово к финализации (2026-11-09)

PR #18. Шпаргалка оператора, generic GD, GUIDE-001/002, commit tier для гейта коммита Claude
(первые коммиты Claude в overgate прошли гейт). PLAN_READY, QA PASS, Code Review APPROVED,
полный verify PASS. Pending: CI final HEAD, trusted finalize, operator merge, release rc.5.1,
публикация Beads snapshot, согласованное обновление проектов.

## WI-1 rc.4 — implementation candidate, acceptance pending

PR #12, branch plan/v4.0.0-rc.4-adoption. WI-1 AC/source plan v0.6 blob d9d760d сохранён
как baseline; v0.7 меняет только release boundary по решению оператора 2026-11-03.
Affected PLAN_REVIEW: PLAN_READY, 0 BLOCKER/ADVISORY; Windows/live/CI acceptance pending.
Upstream og-159 MERGED fa0681a6, Beads CLOSED (текущий факт, подтверждён PM);
интегрирован pure merge 4120e674; trusted finalize source fa0681a6.
Реализация WI-1: modes/settings fingerprints, protection/Memory/Beads helpers, --no-beads,
relative install-state/rollback, tracker defer, QUICKSTART/ADR3.33. Developer TDD и local
reference checks — evidence реализации, не acceptance.

История RV-WI1-F1: на source `0eeb492` тарифный403 предварительного GET protection давал6
без R8; исправлен в `75677f9` (code4/R8 до PUT, прочие403 stop6, strict/readback сохранены).
История RV-WI1-F2: actual installed Codex0.153.4 на source756 отвергал все пять inherited
core SKILL.md без YAML metadata. Source `cc0f3f2` добавил только name/description из прежних
names/Trigger, полностью сохранив тела процедур. Affected QA2 PASS; same Reviewer3 закрыл F1/F2;
affected CODE_REVIEW APPROVED, 0 открытых findings; публикацией closure evidence управляет PM.

Actual macOS target PR1: первоначальная native установка source756, затем отдельно approved
upgrade sourcecc0 → target `1f64a07`. State auto/Beads JSONtrue, 73 операции сверены по bytes/modes.
Native Codex catalog показывает все пять skills без прежних loader errors; actual canon-router
invocation/read подтверждён в Codex, explicit canonical-owner Read route сохранён в Claude auto.
Это адресная installed qualification, не fresh-native clean-project run прямо сcc0 и не полная
приёмка WI-1. CI-budget fix ниже не меняет manifest/payload bytes/modes: прежние Mac receipts
наследуются только для доказанно идентичного component scope, не как новые whole-HEAD runs.

CI sourcecc0 run40719436761: Linux/macOS SUCCESS; Windows CANCELLED по job budget30m,
не assertion failure: dispatcher/install/rollback SUCCESS27:58, installer50/50; wrapper
прерван на30m. Предыдущий source756 Windows run40711543487 SUCCESS29:33, запас лишь27с.
Windows job budget увеличен до40m; команды/tests/runtime и Linux15m/macOS30m неизменны.
Требуется новый exact-HEAD CI с фактическим завершением Windows suite; его PASS ещё не заявлен.

Mandatory pending: actual operator Windows simple/complex-path checklist, real server rejection
прямого main push, оставшиеся live variants по contract и trusted whole AC16 finalization.
PM ведёт affected QA2/same Reviewer3 recheck и exact-HEAD CI; overall acceptance/readiness
не объявлены. Решение оператора 2026-11-03: WI-2 og-7sr перенесён в rc.5; release rc.4
после полной приёмки WI-1, trusted finalize и operator merge. План v0.7 меняет только
release boundary; WI-1 AC-01…AC-17 остаются. Latest v3.9.0 не меняется.


## История og-159 до merge — implementation candidate, acceptance pending

В PR #13 реализован перенос автоматического `/finalize-pr` в managed executable script
с `--check`/`--publish`; SKILL сохраняет описание и ручной `--force`. Добавлены tests обоих
hook routes, stubbed e2e, capture bytes/LF/cleanup, trusted-tree closure, migration assertions
и non-vacuity mutations, fresh/rc.3 upgrade, deterministic bootstrap extractor и CHANGELOG.
Перед implementation зафиксирован RED отсутствующего script; локальные итоги Developer
с exact candidate SHA публикуются PM в PR после проверки reference. Closure из rc.3 сохранён.
RV-F1: macOS CI на `d85f338` дал 133 PASS /126 FAIL; isolated en_US locale воспроизвёл
тот же отказ. План v0.5 (`5ab559a2`, affected PLAN_READY) задаёт единственный per-process
`LC_ALL=C` prefix parser awk и bootstrap, без изменений frozen AWK body/closure и golden cases.
Bootstrap v0.5 снимает scriptSHA/BODY cycle: стабильный script, runtime digest из отдельного
immutable attestation; actual FINAL constructibility и negative digest cases обязательны.
Budget 4/6 использован (Plan Review 1/2, QA 3, Code Review 4); affected проверки в тех же сессиях.
Pending: affected QA и scoped Code Review, fresh exact-HEAD CI, live Claude/Codex `--check`
(PR #13 и #11), PM manual body validation, trusted bootstrap-finalization и operator merge.
Новый candidate/release rc.4 здесь не объявляется; WI-1 ждёт merge og-159.

## rc.3 — исторический snapshot до og-159

В работе: v4.0.0-rc.3 (`og-7d1`), Draft PR #11, ветка `fix/installer-conformance`, план
`docs/plans/2026-10-24-v4.0.0-rc.3.md` v0.3 (PLAN_READY). Реализованы шаги 1–4: RED-тесты §4,
C1–C3 в `scripts/install-overgate.py`, INSTALL/версия/CHANGELOG, AC-09 на офлайн-клоне u2-lab.
Pending: QA, Code Review, CI `verify-reference`/`windows-native`, finalize, operator merge,
затем тег `v4.0.0-rc.3` и prerelease (шаг 5), Latest = `v3.9.0`.

## rc.2 (история)

Сделано в rc.2: v4.0.0-rc.2 (`og-rdc`), Draft PR #10, ветка `chore/u2-pipeline-sync`, план
`docs/plans/2026-10-23-v4.0.0-rc.2.md` v0.2 (PLAN_READY). Реализованы шаги 1–7: страж bash 3.2,
`bd-wt.sh` embedded/server + allowlist, тесты обёртки, `bash scripts/...` в предписаниях,
upgrade-фикстура rc.1 → rc.2, Windows Git Bash шаг CI, версия/CHANGELOG/provenance.
Pending: QA, Code Review, finalize, operator merge, затем тег/prerelease (шаг 8). Windows CI
результат подтверждается только фактическим прогоном GitHub Actions.

## rc.1 (история)

В работе: PR #7 / `og-uw7`, approved refresh frozen source `c450fa7b`.
Generic шесть owners и пять skills сохранены; добавлен Claude dispatcher и точные previous-RC
managed identities, native Windows CI, real installed project verifier/budget fixtures.
QA-F1/F2 fixes сохранены. Verification: `bash scripts/verify-reference.sh`; exact tested SHA/logs
публикуются в PR. Platform/live results остаются pending до фактического evidence.
Budget 5/6: actual OPUS CODE_REVIEW 5 — CHANGES_REQUESTED, Codex source deviation blocker.
В работе source-equivalent один Codex repository guard + previous-RC migration/custom hook regression.
QA slot 6/6 и addressed RV recheck с explicit дополнительным бюджетом управляет PM.
Finalization/merge/release pending; Developer tests не являются independent acceptance.
Windows recovery для spaces/Cyrillic/parentheses + косметический prefix cleanup — следующий `og-7sr`.
Outside-Git placeholder принят оператором 2026-10-03 как `DECLARED_LIMIT` rc.1, block2
обязателен, root restart ожидаем; literal hint также `og-7sr`. Own-subdirectory literal recovery сохраняется.
Адресные native fixtures: cleanup readonly Git objects, snapshot POSIX keys и LF frozenblob
эталон при clean CRLF checkout. Полный native Windows PASS требует нового exact-SHA CI.
Required main check включает оператор; protection/finalization/publication остаются pending.
Stable/beta identities не изменяются; installer сохраняет overrides и rollback snapshot.

## История до v4 RC (reference only)

**Сделано:** канонический reference OverGate (отчуждён из dogfood-проекта U2) + **первый публичный beta `v3.9.0-beta.1`** (PR #5).
**Дальше:** GitHub release `v3.9.0-beta.1` (prerelease) после merge оператором; публичная beta-обкатка адаптерами через `.agents/INSTALL.md`.

## Последние изменения

- **PR #5** (релиз `v3.9.0-beta.1`, Sprint Final): первый публичный beta. MIT `LICENSE` + `CHANGELOG.md`; де-догфудинг операционных U2-утечек (hardcoded Windows-пути dogfood-репо → `<REPO_ROOT>`, хост публичного сайта → `<SITE_HOST>`, manifest → `<SITE_MANIFEST>`, npm-скоп → `@overgate/...`; provenance U2 сохранена); onboarding-hardening (таблица пререквизитов Python/gh/Node/bd, fail-closed placeholder-гейт `/verify` + advisory для EXAMPLE sync-скиллов, bd version-gate portable awk, cost-warning Mode A-legacy); гигиена (tracked `.pyc` удалён, `.gitignore`). Прошёл internal Critical + external Sprint Final (GPT-5.5 + gpt-5.3-codex; итеративная сходимость через operator-findings; финальные пере-ревью — GPT-5.5 via Platform API после revoked Codex token). Полный ревью-трейл — в комментах PR #5. Defer **og-w98** (P3, §B.4 adaptation-таблица стейл U2→OverGate, pre-existing).
- **PR #4** (og-xxj, Critical): фикс примера `/verify` под npm-workspace — `npm ci` из
  корня + root-скрипты `npm run build`/`npm test -- --run`, превентивная заметка про
  workspace. Internal review (3 прохода) + external cross-model (gpt-5.5 + gpt-5.3-codex,
  iteration 2) APPROVED. Внешнее ревью поймало watch-режим vitest (убранный `-- --run`) —
  исправлено. Follow-up og-4m1: решить судьбу untracked `.agents/skills/` (Codex-зеркало).
