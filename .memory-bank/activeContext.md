# Active Context

Текущий фокус: v4.0.0-rc.1 Delivery First candidate, ветка `codex/delivery-first-rc`, PR #7.
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
