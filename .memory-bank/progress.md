# Progress

## og-159 — implementation candidate, acceptance pending

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
