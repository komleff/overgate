#!/usr/bin/env bash
# Восстановление задач Beads из служебной ветки beads-backup на другой машине.
# Замена несуществующей в bd 1.0.2 команды `bd backup fetch-git`.
#
# Снапшот извлекается во временный файл ($TMPDIR) и импортируется через `bd import`
# (upsert). В рабочее дерево .beads/issues.jsonl НЕ пишется.
#
# Предусловие: bd-воркспейс уже инициализирован (`bd init --skip-agents`), config.yaml
# взят из git (export.auto=false, без sync.remote). Скрипт НЕ запускает `bd init`
# сам, чтобы не переустановить запрещённый Dolt-remote/sync.remote.
#
# Запускать ТОЛЬКО из основного checkout (не из git-worktree) — см. .claude/rules/beads.md.
set -euo pipefail

BRANCH="beads-backup"
TMP="${TMPDIR:-/tmp}"
SNAP="${TMP}/bd-snap-$$.jsonl"
cleanup() { rm -f "$SNAP"; }
trap cleanup EXIT

# 0. Проверка инициализации воркспейса.
if ! bd where >/dev/null 2>&1; then
  echo "ОШИБКА: bd-воркспейс не инициализирован. Сначала: bd init --skip-agents" >&2
  exit 1
fi

# 1. Получить ветку. Явный destination-refspec: на single-branch/CI-клонах обычный
#    `git fetch origin <branch>` может заполнить только FETCH_HEAD и НЕ создать
#    refs/remotes/origin/<branch> → `git show origin/<branch>:...` ниже не нашёл бы снапшот.
git fetch -q origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}"

# 2. Извлечь снапшот во временный файл. Основной путь — .beads/issues.jsonl;
#    fallback — .beads/backup/issues.jsonl (снапшоты до стандартизации пути).
if git show "origin/${BRANCH}:.beads/issues.jsonl" > "$SNAP" 2>/dev/null; then
  :
elif git show "origin/${BRANCH}:.beads/backup/issues.jsonl" > "$SNAP" 2>/dev/null; then
  echo "ВНИМАНИЕ: использован legacy-путь .beads/backup/issues.jsonl" >&2
else
  echo "ОШИБКА: снапшот не найден в origin/${BRANCH}" >&2
  exit 1
fi

# 3. Импорт (upsert: новые создаются, существующие обновляются).
if [ ! -s "$SNAP" ]; then
  echo "OK: снапшот пуст — импортировать нечего."
  exit 0
fi
bd import "$SNAP"

echo "OK: задачи восстановлены из origin/${BRANCH}"
