# Project — agent bootstrap

Product authority: оператор (пока проект явно не назначил другого владельца).
Project first-read route: текущий project context и один authoritative owner по теме.
Если current owners конфликтуют — эскалация оператору; search result не authority.

Pipeline: `.agents/PIPELINE.md`; role owners: `.agents/AGENT_ROLES.md`;
core skills: `.agents/SKILLS.md`. Общая policy — ADR §§3.28–3.32.
PM/Planner/Developer не выбирают missing WHAT. Ready source → PASS_THROUGH.
ИИ не merge/auto-merge и не обновляет main/master. Не обходить hooks/permissions,
не читать `.env*`, credentials, secrets. Evidence публиковать с фактической ролью/моделью.
Проверки проекта: `.agents/project/verify.sh`; до заполнения он намеренно даёт FAIL.
Личные runtime overrides и project context принадлежат проекту.

Beads: основной checkout использует `bd` и sync helpers; локальная worktree —
`scripts/bd-wt.sh` с живой основной базой; облачный агент — снимок `beads-backup` и
pending-заявки `.bd-intents/` в PR. Порядок и граница поставки applier:
`.agents/HOW_TO_USE.md`, секция Beads; project owner — `.claude/rules/beads.md`.
Авторизованный GitHub-коннектор не требует отдельного login Git CLI. Не создавать
cloud writer, не менять снимок вручную; очередь применяет оператор trusted tooling.
