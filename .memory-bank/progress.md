# Progress

**Сделано:** канонический reference OverGate (отчуждён из dogfood-проекта U2) + **первый публичный beta `v3.9.0-beta.1`** (PR #5).
**Дальше:** GitHub release `v3.9.0-beta.1` (prerelease) после merge оператором; публичная beta-обкатка адаптерами через `.agents/INSTALL.md`.

## Последние изменения

- **PR #5** (релиз `v3.9.0-beta.1`, Sprint Final): первый публичный beta. MIT `LICENSE` + `CHANGELOG.md`; де-догфудинг операционных U2-утечек (`D:\GitHub\u2`→`<REPO_ROOT>`, `docs.u2game.space`→`<SITE_HOST>`, манифест→`<SITE_MANIFEST>`, `@u2/`→`@overgate/`; provenance U2 сохранена); onboarding-hardening (таблица пререквизитов Python/gh/Node/bd, fail-closed placeholder-гейт `/verify` + advisory для EXAMPLE sync-скиллов, bd version-gate portable awk, cost-warning Mode A-legacy); гигиена (tracked `.pyc` удалён, `.gitignore`). Internal Critical (2 прохода) + external A-hybrid (GPT-5.5 via Codex sub + gpt-5.3-codex via Platform API, 4 итерации до сходимости) — APPROVED. Defer **og-w98** (P3, §B.4 adaptation-таблица стейл U2→OverGate, pre-existing).
- **PR #4** (og-xxj, Critical): фикс примера `/verify` под npm-workspace — `npm ci` из
  корня + root-скрипты `npm run build`/`npm test -- --run`, превентивная заметка про
  workspace. Internal review (3 прохода) + external cross-model (gpt-5.5 + gpt-5.3-codex,
  iteration 2) APPROVED. Внешнее ревью поймало watch-режим vitest (убранный `-- --run`) —
  исправлено. Follow-up og-4m1: решить судьбу untracked `.agents/skills/` (Codex-зеркало).
