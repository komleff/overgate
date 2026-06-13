---
description: Правила работы с трекером задач Beads (bd) — Dolt/worktree/lock
globs: "**/*"
---

<!-- Generic-правило пайплайна (provenance — git history + PIPELINE_ADR ADR 3.7). -->

# Правила работы с задачами Beads (трекер задач пайплайна)

> Beads (`bd`) — **единственный** трекер задач проекта. НЕ использовать TodoWrite, TaskCreate
> или markdown-TODO для отслеживания работы (внутренний todo-list агента в рамках одной
> сессии — можно, но он не заменяет `bd`).

## Главное: backend — Dolt, но «через базу Dolt» работать НЕЛЬЗЯ

Beads хранит задачи в локальном Dolt, **но Dolt — деталь реализации, а не интерфейс**. Агенты
по инерции пытаются «синхронизировать базу» через Dolt — это и есть источник поломок.

- Source of truth для кросс-машинной синхронизации — **служебная ветка `origin/beads-backup`**
  (дефолтное имя backup-ветки самого `bd`), в ней JSONL-снапшот `.beads/backup/*.jsonl`.
- Публикация: `bd backup export-git --force`. Восстановление на другой машине: `bd backup fetch-git`.
- `bd dolt push` / `bd dolt pull` — **НЕ операционный путь синхронизации**. Если в проекте
  настраивался DoltHub-remote — это исторический fallback, не текущий стандарт.

> ⚠️ **Override upstream `bd`.** Команды `bd prime` / `bd onboard` / `bd setup` (а также
> SessionStart-хук, который авто-инжектит `bd prime`) могут рекомендовать `bd dolt push` /
> `bd dolt pull` как путь синхронизации — это upstream-дефолт Beads. **В этом пайплайне он НЕ
> применяется.** Это правило и `AGENTS.md` имеют приоритет над выводом `bd prime`: синхронизация
> — только через ветку `beads-backup` (`export-git` / `fetch-git`).

## Запуск bd — только из основного checkout, НЕ из worktree

Почти любая `bd`-команда автозапускает фоновый `bd dolt start` (dolt sql-server). Dolt runtime
привязан к конкретному checkout и **не переключается с git-веткой**. Поэтому:

- В **git-worktree** прямой `bd create/close/update/show` создаёт **новую пустую dolt-базу** →
  синхронизация рассыпается, видны 1-2 чужих issue или ничего. Возможен также lock-конфликт
  (см. troubleshooting).
- bd-мутации выполнять из **основного checkout** репозитория, где bd функционален.
- Из worktree — либо делегировать оператору с готовой командой, либо цикл из основного checkout:
  `bd backup fetch-git` → `bd <cmd>` → `bd backup export-git --force`.

## Базовый цикл работы с задачами

```bash
bd ready                 # найти доступную работу
bd show <id>             # детали задачи
bd update <id> --claim   # взять в работу
bd close <id>            # завершить
bd prime                 # справочник команд (см. override выше про sync-команды)
```

Завершая сессию с изменениями: `bd backup export-git --force` → `git pull --rebase` → `git push`.

## Troubleshooting: bd-команда зависла

Симптом: `bd doctor` (или любая `bd`-команда) висит, `.beads/dolt-server.log` раздувается циклом
`database "dolt" is locked by another dolt process`, перебирая порты.

Причина: orphan `dolt sql-server` от прошлой сессии/worktree держит эксклюзивный write-lock на
`.beads/dolt`.

Лечение:
```bash
lsof .beads/dolt/.dolt/noms/LOCK          # показать процесс-держатель
ps aux | grep -E "dolt sql-server|bd dolt start" | grep -v grep
kill -9 <pid> ...                          # убить все orphan dolt sql-server + bd dolt start
```
После освобождения lock `bd doctor` снова работает.

## Запрещено

- Работать с задачами через Dolt напрямую: `bd dolt push/pull`, ручной запуск dolt-сервера,
  правка `.beads/dolt/**`.
- Запускать `bd`-мутации из git-worktree (плодит пустые базы и lock-зависания).
- Считать локальный `.beads/issues.jsonl` источником истины — это **обрывок** (1-2 issue),
  полный набор только в ветке `beads-backup`. Руками `.beads/backup/*.jsonl` не редактировать —
  сломает manifest/consistency.
- Подменять `bd` на TodoWrite/markdown-TODO для трекинга задач проекта.
