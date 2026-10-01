---
title: "OverGate — agent bootstrap"
status: primary
version: "4.0.0-rc.1"
date: 2026-10-01
tags: [agents, bootstrap, delivery-first]
---
# OverGate — agent bootstrap

OverGate — generic reference Delivery First. Product/game data сюда не переносится.
Первое чтение: `.memory-bank/activeContext.md` + `.memory-bank/progress.md`, `README.md`,
один owner из `.agents/AGENT_ROLES.md`; для architecture/process — `.agents/PIPELINE_ADR.md`
§§3.28–3.31 и `docs/architecture/ADR-INDEX.md`. Archive/history читать только по необходимости.
Search находит candidate, не authority. Конфликт current owners эскалируется оператору.

**Product authority: оператор.** PM/Planner/Developer не выбирают missing WHAT.
Implementation-ready source принимается без новой spec. Роли и пять core skills:
`.agents/AGENT_ROLES.md`, `.agents/SKILLS.md`; adapters не владеют policy.

- Работа в рабочей ветке; ИИ не merge/auto-merge и не обновляет main/master напрямую.
- Не обходить hooks/permissions, не читать/публиковать `.env*`, credentials, secrets.
- Verifier только с AC / FAIL / named risk. Значимое evidence в PR с role/model.
- Одна финализация на final HEAD после landing, fresh checks и необходимого affected recheck.
- Не принимать за оператора missing product decisions и реальные Important/Critical risks.
- User interrupt приоритетен. Временные файлы вне repo; в Git только durable result.

Reference проверяется `bash scripts/verify-reference.sh`; установленный проект задаёт свои
команды в `.agents/project/verify.sh`. Язык — русский; пути/идентификаторы — английские.

Beads — task state; Git/PR — code/evidence. `bd --help`, `.claude/rules/beads.md`, штатные
`scripts/bd-sync-*` определяют текущий route. Не писать Dolt напрямую, не mutating bd из
worktree, не считать local `.beads/issues.jsonl` авторитетным. Triage lookup использует
`scripts/beads-evidence.py` и frozen snapshot `origin/beads-backup` текущего проекта.
Не откатывать Beads/Memory Bank вслепую. Личный runtime state не коммитится.

Большие PR reports публикуются `.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py`;
readiness — только trusted `/finalize-pr`. Полномочия публикации определяет задача;
subagent возвращает report PM. Merge всегда выполняет оператор.
