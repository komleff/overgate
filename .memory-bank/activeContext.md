# Active Context

## WI-1 rc.4 — implementation candidate, acceptance pending

PR #12, branch plan/v4.0.0-rc.4-adoption, approved plan v0.6 blob d9d760d unchanged.
Upstream og-159 MERGED fa0681a6, Beads CLOSED (текущий факт, подтверждён PM);
интегрирован pure merge 4120e674; trusted finalize source fa0681a6.
Реализация WI-1: modes/settings fingerprints, protection/Memory/Beads helpers, --no-beads,
relative install-state/rollback, tracker defer, QUICKSTART/ADR3.33. Developer TDD и local
reference checks — evidence реализации, не acceptance. PM ведёт independent QA → один Code Review,
затем operator live Windows/Claude/Codex, exact-HEAD CI и trusted finalize. Live receipts пока NOT RUN.
WI-2 og-7sr, merge и выпуск rc.4 — отдельно; Latest v3.9.0 не меняется.


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
