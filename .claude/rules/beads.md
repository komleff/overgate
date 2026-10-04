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

- Source of truth для кросс-машинной синхронизации — **служебная ветка `origin/beads-backup`**,
  в ней JSONL-снапшот `.beads/issues.jsonl` (формат `bd export`).
- Публикация: `scripts/bd-sync-export.sh` (экспорт → fast-forward-коммит снапшота в `beads-backup`
  → push). Восстановление на другой машине: `scripts/bd-sync-restore.sh` (fetch ветки → `bd import`
  из `$TMPDIR`).
- `bd dolt push` / `bd dolt pull` — **НЕ операционный путь синхронизации** (заблокированы deny-правилом
  в `.claude/settings.json`). `sync.remote` и Dolt-remote в этом репозитории отключены намеренно
  (`bd config` → `sync.remote` unset, `export.auto=false`).

> ℹ️ **bd 1.0.2.** Старых команд `export-git` / `fetch-git` (как в прежних версиях bd) в
> установленной версии **не существует**. Синхронизация — через helper-скрипты выше
> (`bd export` + ветка `beads-backup` + `bd import`), а не через `bd backup`.

### Контракт синхронизации и его ограничения

Модель — JSONL-**снапшот**, а не распределённый merge-движок (Dolt-merge запрещён каноном).
Из этого вытекает дисциплина **restore-before-export**, которую `bd-sync-export.sh` навязывает
программно (fail-closed), чтобы snapshot-модель не теряла данные:

- **last-seen guard** — export откажет, если `origin/beads-backup` продвинулся с момента
  последней синхронизации этого клона (другая машина опубликовала раньше). Сначала
  `scripts/bd-sync-restore.sh`, потом повтори export.
- **drop-guard** — export откажет, если на ветке есть задачи (issue-id), отсутствующие в
  локальном снапшоте (вторая линия защиты от перезаписи).
- Override обоих (намеренная перезапись/удаление) — `BD_SYNC_FORCE=1`.
- **Удаления не зеркалируются автоматически**: restore делает `bd import` (upsert без prune),
  поэтому удалённая на одной машине задача не исчезнет на другой сама. `bd delete` запрещён
  deny-правилом; массовые удаления координируются вручную (осознанное ограничение модели).
- last-seen хранится в `git config --local beads-sync.lastSeen` (per-clone, не коммитится).

> ⚠️ **Override upstream `bd`.** Команды `bd prime` / `bd onboard` / `bd setup` (а также
> SessionStart-хук, который авто-инжектит `bd prime`) могут рекомендовать `bd dolt push` /
> `bd dolt pull` как путь синхронизации — это upstream-дефолт Beads. **В этом пайплайне он НЕ
> применяется.** Это правило и `AGENTS.md` имеют приоритет над выводом `bd prime`: синхронизация
> — только через ветку `beads-backup` (`scripts/bd-sync-export.sh` / `scripts/bd-sync-restore.sh`).

## Доступ определяется окружением

Полный порядок, формат очереди и граница поставки — в
[`HOW_TO_USE.md`, секция Beads](../../.agents/HOW_TO_USE.md#beads-основной-checkout-worktree-и-облачный-агент).

| Окружение | Чтение | Запись |
|---|---|---|
| Основной checkout оператора | `bd ready/show` | `bd create/update/close`; затем sync-export |
| Локальная worktree с доступом к основной базе | `scripts/bd-wt.sh ready/show` | `scripts/bd-wt.sh <cmd>`; export из основного checkout |
| Облачный агент без основной базы | `scripts/bd-read.sh` или снимок `beads-backup` через коннектор | `.bd-intents/<branch-slug>.jsonl` в PR; применяет оператор |

Обычный clone в облаке не является checkout оператора. Наличие `bd` не даёт доступа к его базе.
OverGate поставляет reader/worktree/sync helpers; applier пока не входит в inventory.
В проекте с trusted `scripts/bd-apply-intents.sh` оператор применяет reviewed очередь из основного
checkout, проверяет публикацию снимка и только затем удаляет её landing-коммитом.
При отсутствии applier заявки остаются pending; независимая работа продолжается.
Не устанавливать bd ради второго writer и не публиковать изменённый снимок из облака.
Авторизованный GitHub-коннектор позволяет читать снимок и работать с PR без login Git CLI.
Pending-заявка не означает выполненный claim/close. Снимок привязывать к repository и SHA.

### Прямой bd с auto-discovery — только из основного checkout

Почти любая `bd`-команда автозапускает фоновый `bd dolt start` (dolt sql-server). Dolt runtime
привязан к конкретному checkout и **не переключается с git-веткой**. Поэтому:

- В **git-worktree** прямой `bd create/close/update/show` с auto-discovery может создать **новую пустую dolt-базу** →
  синхронизация рассыпается, видны 1-2 чужих issue или ничего. Возможен также lock-конфликт
  (см. troubleshooting).
- bd-мутации выполнять из **основного checkout** либо через `scripts/bd-wt.sh` из локальной worktree.
  Обёртка подключается к той же живой базе через явный `--db`; второй сервер не создаётся.
  `export/import/dolt` и пользовательский `--db` через обёртку запрещены.
- Если основной сервер недоступен — передать заявку оператору; либо цикл из основного checkout:
  `scripts/bd-sync-restore.sh` → `bd <cmd>` → `scripts/bd-sync-export.sh`.

## Базовый цикл работы с задачами

```bash
bd ready                 # найти доступную работу
bd show <id>             # детали задачи
bd update <id> --claim   # взять в работу
bd close <id>            # завершить
bd prime                 # справочник команд (см. override выше про sync-команды)
```

Для основного checkout завершение с изменениями: `scripts/bd-sync-export.sh` →
`git pull --rebase` → `git push` рабочей ветки. Worktree передаёт публикацию основному checkout;
облачный агент коммитит заявки в PR и сообщает pending-состояние.

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
- Запускать прямой `bd` с auto-discovery из git-worktree; использовать `scripts/bd-wt.sh`.
- Создавать отдельную облачную базу или публиковать снимок в `beads-backup` из облака.
- Исполнять applier/libraries из недоверенной PR-ветки или считать pending-заявки применёнными.
- Считать локальный `.beads/issues.jsonl` источником истины. В этом репозитории auto-export
  отключён (`export.auto=false`), файл в рабочем дереве `main` не появляется и в git не трекается;
  полный набор задач — снапшот `.beads/issues.jsonl` в ветке `beads-backup`. Снапшот руками не
  редактировать — публиковать только через `scripts/bd-sync-export.sh`.
- Подменять `bd` на TodoWrite/markdown-TODO для трекинга задач проекта.
