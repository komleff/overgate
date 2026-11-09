# Active Context

## og-bo6 rc.5.1 — точка входа оператора (приоритет P0, 2026-11-09)

PR #18, ветка `fix/og-bo6-operator-guide` от `9addb79` (tag v4.0.0-rc.5), CRITICAL, план
`docs/plans/2026-11-09-v4.0.0-rc.5.1-operator-guide.md` v0.3. Причина: с `3766036` (PR #7,
rc.1) `HOW_TO_USE.md` без промптов ролей; GD в OverGate не было. Решение PM (вариант b):
generic GD ставится всегда (`preserve`), использование необязательно; ADR §3.36.
og-cfx (блокер): гейт коммита Claude не проходил (полный reference ~20 мин > 570 с);
`verify-reference.sh --commit-tier` (432 с, 34 шага) для `.agents/project/verify.sh`,
полный набор — `/verify` и required CI; ADR §3.37. Коммиты `0d9b644`, `d858dfd`, `39db72b`
прошли гейт. Evidence: Plan Review 1/6 PLAN_READY (v0.2, v0.3), QA 2/6 PASS, Code Review 3/6
APPROVED + scoped re-reviews APPROVED; полный verify на `d858dfd` PASS, CI Linux/macOS SUCCESS.
Pending: CI на final HEAD (включая Windows), trusted `/finalize-pr` из `9addb79`, operator
merge, затем release `v4.0.0-rc.5.1` (prerelease, not Latest). Beads snapshot не опубликован:
legacy sync изолирует git config, нужен repo-local credential helper (оператор, команда в PR).
Отложено: `og-1lg` (запас commit tier/Windows, строгость ROLE, C1 парсер шагов).
Обновление других проектов komleff — только после merge и по согласованию с оператором,
по каждому проекту отдельно; у установленных проектов `AGENTS.md` (preserve) указатель не получит.

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


## История og-159 до merge — единый исполняемый finalize gate

Приоритетная линия: `og-159`, PR #13, ветка `fix/og-159-finalize-gate-script`, база
`main@b830d5e` (rc.3). Принятый план v0.5, blob `5ab559a2`, affected PLAN_READY в той же reviewer-сессии launch 2.
Фактически использовано 4/6 launches: Plan Review 1/2, QA 3, Code Review 4.
Developer переносит frozen `SKILL.md` blob `b7e7ed1` в managed `finalize-gate.sh`: общий shell
маршрут Claude Code/Codex, code из GATE_TREE, data из WORK_TREE, private snapshot с точными
bytes и raw stdin publisher. Trusted closure не меняется. Bootstrap extractor фиксирует
исходный blob и closure; scriptSHA стабилен независимо от BODY. Runtime digest вручную
проверенного PM тела приходит из отдельного immutable attestation; og-159 финализируется им.
История RV-F1: `d85f338` получил actual macOS CI FAIL (triage 133/126) из-за en_US collation.
Текущий fix candidate добавляет только per-process `LC_ALL=C` для triage AWK и bootstrap;
frozen AWK body/closure неизменны, acceptance и exact-SHA CI остаются pending.
История AC11: literal body digest создавал цикл scriptSHA/BODY; v0.5 выносит digest в
runtime data и требует constructibility настоящего FINAL, acceptance ещё pending.
Ручные проверки accepted risk/паспорта, CI, live runtime checks, affected QA 3 и
Code Review 4 в тех же сессиях и bootstrap-finalization остаются pending; local Developer fixtures не
означают acceptance/readiness. Merge — оператор. WI-1 rc.4 v0.6 и его ветка не меняются.

## rc.3 — исторический snapshot до og-159

Текущий фокус: v4.0.0-rc.3 (`og-7d1`), Draft PR #11, ветка `fix/installer-conformance`, база
`main` `073595a` (= rc.2). План `docs/plans/2026-10-24-v4.0.0-rc.3.md` v0.3 (PLAN_READY), CRITICAL,
budget 6. Решение оператора 2026-10-24: перед upgrade u2-lab выпустить rc.3 с исправлением
установщика — побайтное соответствие managed/settings source после fresh и upgrade с rc.1/rc.2.
Исправлено: C1 `og-48u` (Codex без `permissions`), C2 `og-dp6` (`.gitignore` по таблице §4.1,
новый conflict изменённого фрагмента), C3 `og-lnt` (правило записи settings без `sort_keys`).
Prerelease, `make_latest=false`; stable `v3.9.0` остаётся Latest. Для v3.9 → rc.3 цель не заявлена.

## rc.2 (история)

Фокус rc.2: v4.0.0-rc.2 (`og-rdc`), Draft PR #10, ветка `chore/u2-pipeline-sync`, база `main`
`511023e`. План `docs/plans/2026-10-23-v4.0.0-rc.2.md` v0.2, режим CRITICAL, budget 6.
Решение оператора 2026-10-23: rc.2 — prerelease, `make_latest=false`; stable `v3.9.0` остаётся Latest.
Перенос: U2 `4a7354ea7` (#862 страж bash 3.2, #859 `bash scripts/...`) и U2 Lab `5586b43` (#30
`bd-wt.sh` embedded/server + allowlist), обезличенно. `--global` в обёртке теперь отказ (Changed).
Allow-правила settings для обёрток не переносятся; applier не поставляется; `og-7sr` отложен.
Штатной команды bd 1.2.x для восстановления `dolt_mode` нет — отказ отсылает к оператору.

## rc.1 (история)

Фокус rc.1: v4.0.0-rc.1 Delivery First candidate, ветка `codex/delivery-first-rc`, PR #7.
Approved refresh: `docs/plans/2026-10-03-delivery-first-rc-refresh.md` и portability amendment.
Frozen U2 source: `c450fa7b0d90fecf970f9931011255ea836da258`; старый source contract
`fb8ebfa5` и bound reports сохранены как history. Independent PLAN_READY 3/6 + 4/6 получены;
CODE_REVIEW 5 потребовал source-equivalent Codex fix; addressed CODE_REVIEW 6 на
`5680d633` — APPROVED. Budget 6/7 после решения оператора, слот 7 — QA, ещё не проведена.
Codex сохраняет один source repository guard; Claude runtime не меняется.

Реализация переносит #829 dispatcher, staged/installed closure и migration fixtures;
installer QA-F1/F2 fixes `bdc92fac` сохраняются и требуют affected QA.
Оператор выбрал source-compatible recovery rc.1: только unquoted absolute простой путь.
Recovery spaces/Cyrillic/parentheses и внутренние U2-prefix cleanup deferred в `og-7sr`.
Решение оператора 2026-10-03: outside-Git placeholder `cd <корень репозитория>` —
`DECLARED_LIMIT` rc.1 при обязательном block2, новая сессия из root; literal hint deferred
в `og-7sr`. Own-subdirectory displayed literal recovery остаётся обязательной.
Actual Windows smoke5680d633: Claude S1/S2/S4/S5/S7 PASS, S3/S6 — accepted DECLARED_LIMIT;
Codex live NOT RUN. Ordinary-user cp1251/Python3.14 installer24 дал 3 fixture ERROR:
два implicit text encoding и WinError1314 без symlink privilege. Адресный fixture fix
не меняет approved runtime; actual host retest и QA pending. Старые FAIL сохраняются в PR history.
Required main `verify-reference` устанавливает оператор; агент не обходит repository guard.
Native Windows/live Claude/Codex smoke подтверждается отдельно; CI config не означает PASS.
Prior trusted finalize, operator merge и RC prerelease publication ещё pending.
Dreadnought остаётся stable/Latest. Installer не переносит Memory Bank в проекты.
