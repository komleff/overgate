# Project — agent bootstrap

Product authority: оператор (пока проект явно не назначил другого владельца).
Project first-read route: текущий project context и один authoritative owner по теме.
Если current owners конфликтуют — эскалация оператору; search result не authority.

Оператору: копируемые промпты ролей — `.agents/HOW_TO_USE.md` (папка `.agents` скрыта
в Finder/Проводнике). Обычно начинают с «Ты PM. Прочитай .agents/PM_ROLE.md.» и задачи.

Pipeline: `.agents/PIPELINE.md`; role owners: `.agents/AGENT_ROLES.md`;
core skills: `.agents/SKILLS.md`. Общая policy — ADR §§3.28–3.36.
PM/Planner/Developer не выбирают missing WHAT. Ready source → PASS_THROUGH.
ИИ не merge/auto-merge и не обновляет main/master. Не обходить hooks/permissions,
не читать `.env*`, credentials, secrets. Evidence публиковать с фактической ролью/моделью.
Проверки проекта: `.agents/project/verify.sh`; до заполнения он намеренно даёт FAIL.
Личные runtime overrides и project context принадлежат проекту.

Memory Bank: перед задачей читать `.memory-bank/activeContext.md` и `progress.md`;
после работы обновлять оба файла, сохраняя решения проекта.

<!-- overgate:beads -->
Beads route определяется зарегистрированным protocol. В managed v1 читать опубликованный
`beads-backup` через `bash scripts/bd-read.sh` (или read route `bd-wt.sh`), готовить typed
queue v2 и применять только trusted publisher из exact target `main`. Прямой `bd-wt` write
и legacy sync отказывают; real ID/claim/published SHA подтверждать peer read-back.
В legacy v0 основной checkout использует `bd` и sync helpers, linked worktree —
`bash scripts/bd-wt.sh` с основной базой (embedded или dolt-сервер), cloud agent — снимок
и pending-заявки `.bd-intents/` в PR. Порядок и граница поставки:
`.agents/HOW_TO_USE.md`, секция Beads; project owner — `.claude/rules/beads.md`.
Авторизованный GitHub-коннектор для PR не требует отдельного login Git CLI; managed
publisher после merge требует авторизованный Git transport. Не создавать cloud writer
и не менять снимок вручную. Fresh managed activation происходит отдельно после merge
install PR из trusted `main`; существующие заявки до неё pending, real task ID не подтверждён.
Legacy DB требует preservation, fence известных old writers и отдельный принятый switch.
<!-- /overgate:beads -->
