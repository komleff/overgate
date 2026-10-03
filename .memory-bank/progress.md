# Progress

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
