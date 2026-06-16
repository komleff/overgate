# Progress

**Сделано:** канонический reference OverGate (отчуждён из dogfood-проекта U2).
**Дальше:** установка в целевой проект через `.agents/INSTALL.md`.

## Последние изменения

- **PR #4** (og-xxj, Critical): фикс примера `/verify` под npm-workspace — `npm ci` из
  корня + root-скрипты `npm run build`/`npm test -- --run`, превентивная заметка про
  workspace. Internal review (3 прохода) + external cross-model (gpt-5.5 + gpt-5.3-codex,
  iteration 2) APPROVED. Внешнее ревью поймало watch-режим vitest (убранный `-- --run`) —
  исправлено. Follow-up og-4m1: решить судьбу untracked `.agents/skills/` (Codex-зеркало).
