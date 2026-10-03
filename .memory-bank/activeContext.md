# Active Context

Текущий фокус: v4.0.0-rc.1 Delivery First candidate, ветка `codex/delivery-first-rc`, PR #7.
Approved refresh: `docs/plans/2026-10-03-delivery-first-rc-refresh.md` и portability amendment.
Frozen U2 source: `c450fa7b0d90fecf970f9931011255ea836da258`; старый source contract
`fb8ebfa5` и bound reports сохранены как history. Independent PLAN_READY 3/6 + 4/6 получены;
следующие verifier launches: affected QA 5/6, один scoped Code Review 6/6, свободного reserve нет.

Реализация переносит #829 dispatcher, staged/installed closure и migration fixtures;
installer QA-F1/F2 fixes `bdc92fac` сохраняются и требуют affected QA.
Оператор выбрал source-compatible recovery rc.1: только unquoted absolute простой путь.
Recovery spaces/Cyrillic/parentheses и внутренние U2-prefix cleanup deferred в `og-7sr`.
Решение оператора 2026-10-03: outside-Git placeholder `cd <корень репозитория>` —
`DECLARED_LIMIT` rc.1 при обязательном block2, новая сессия из root; literal hint deferred
в `og-7sr`. Own-subdirectory displayed literal recovery остаётся обязательной.
Native Windows76ab173: dispatcher23/23 и closure11+1skip PASS; installer20/21 FAIL из-за
fixture source-worktree CRLF против frozenblob LF. Исправляется эталон теста, runtime не меняется.
Required main `verify-reference` устанавливает оператор; агент не обходит repository guard.
Native Windows/live Claude/Codex smoke подтверждается отдельно; CI config не означает PASS.
Prior trusted finalize, operator merge и RC prerelease publication ещё pending.
Dreadnought остаётся stable/Latest. Installer не переносит Memory Bank в проекты.
