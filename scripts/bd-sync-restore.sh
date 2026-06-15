#!/usr/bin/env bash
# Восстановление задач Beads из служебной ветки beads-backup на другой машине.
# Замена несуществующей в bd 1.0.2 команды `bd backup fetch-git`.
#
# Снапшот извлекается во временный файл (приватный mktemp-каталог) и импортируется
# через `bd import` (upsert). В рабочее дерево .beads/issues.jsonl НЕ пишется.
#
# Параметры через env: BD_SYNC_REMOTE (default origin), BD_SYNC_BRANCH (default beads-backup).
#
# Предусловие: bd-воркспейс уже инициализирован (`bd init --skip-agents`), config.yaml
# взят из git (export.auto=false, без sync.remote). Скрипт НЕ запускает `bd init` сам,
# чтобы не переустановить запрещённый Dolt-remote/sync.remote.
set -euo pipefail

REMOTE="${BD_SYNC_REMOTE:-origin}"
BRANCH="${BD_SYNC_BRANCH:-beads-backup}"

# Валидация env + guard окружения — общий код с export-скриптом (sourced-helper).
# shellcheck source=scripts/bd-sync-common.sh
. "$(cd "$(dirname "$0")" && pwd)/bd-sync-common.sh"
bd_sync_validate || exit 1

umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/bd-sync.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
SNAP="$WORK/snap.jsonl"

# 0. Проверка инициализации воркспейса.
if ! bd where >/dev/null 2>&1; then
  echo "ОШИБКА: bd-воркспейс не инициализирован. Сначала: bd init --skip-agents" >&2
  exit 1
fi

# 1. Получить ветку. Явный destination-refspec: на single-branch/CI-клонах обычный
#    `git fetch origin <branch>` может заполнить только FETCH_HEAD и НЕ создать
#    remote-tracking ref → `git show <remote>/<branch>:...` ниже не нашёл бы снапшот.
git fetch -q "$REMOTE" "+refs/heads/${BRANCH}:refs/remotes/${REMOTE}/${BRANCH}"
remote_tip=$(git rev-parse "refs/remotes/${REMOTE}/${BRANCH}")

# 2. Извлечь снапшот во временный файл. Основной путь — .beads/issues.jsonl;
#    fallback — .beads/backup/issues.jsonl (снапшоты до стандартизации пути).
if git show "${REMOTE}/${BRANCH}:.beads/issues.jsonl" > "$SNAP" 2>/dev/null; then
  :
elif git show "${REMOTE}/${BRANCH}:.beads/backup/issues.jsonl" > "$SNAP" 2>/dev/null; then
  echo "ВНИМАНИЕ: использован legacy-путь .beads/backup/issues.jsonl" >&2
else
  echo "ОШИБКА: снапшот не найден в ${REMOTE}/${BRANCH}" >&2
  exit 1
fi

# 2a. Conflict-guard (зеркало last-seen guard в export). restore делает upsert remote поверх
#     локальной БД. Если локальная БД изменена с момента последней синхронизации И remote tip
#     при этом продвинулся — это конкурентная правка (same-id конфликт): безусловный upsert
#     молча затёр бы локальные неэкспортированные изменения. Fail-closed, требуем ручного
#     разрешения / BD_SYNC_FORCE=1. (lastSeen хранит коммит, base — его снапшот.)
last_seen=$(git config --local --get beads-sync.lastSeen 2>/dev/null || true)
if [ "${BD_SYNC_FORCE:-}" != "1" ]; then
  local_now="$WORK/local.jsonl"
  bd export --all -o "$local_now" 2>/dev/null || : > "$local_now"; touch "$local_now"
  # Проверяем риск потери ТОЛЬКО если в локальной БД есть данные.
  if [ -s "$local_now" ]; then
    # base — снапшот, с которым локальная БД синхронизирована. Если lastSeen нет (клон ни разу
    # не синхронизировался) — base пуст, т.е. любые локальные данные считаются несинхронизированными.
    base="$WORK/base.jsonl"; : > "$base"
    if [ -n "$last_seen" ]; then
      git show "${last_seen}:.beads/issues.jsonl" > "$base" 2>/dev/null \
        || git show "${last_seen}:.beads/backup/issues.jsonl" > "$base" 2>/dev/null || : > "$base"
    fi
    # Конфликт, если: локальная БД ≠ remote-снапшот (есть расхождение) И локальная БД ≠ base
    # (есть несинхронизированные локальные правки, которые upsert remote затёр бы).
    # lastSeen пуст + непустая локальная БД ≠ remote → подпадает (base пуст). Зеркало export-guard.
    if ! diff -q <(sort "$local_now") <(sort "$SNAP") >/dev/null 2>&1 \
       && ! diff -q <(sort "$local_now") <(sort "$base") >/dev/null 2>&1; then
      echo "ОШИБКА: конфликт синхронизации — локальная БД содержит несинхронизированные изменения," >&2
      echo "а ${REMOTE}/${BRANCH} отличается. restore (upsert) затёр бы локальные правки тех же id." >&2
      echo "  last-seen: ${last_seen:-<нет>}" >&2
      echo "  remote:    $remote_tip" >&2
      echo "Сверь задачи вручную или принудительно: BD_SYNC_FORCE=1 (локальные правки будут перезаписаны remote)." >&2
      exit 1
    fi
  fi
fi

# 3. Импорт (upsert: новые создаются, существующие обновляются).
#    Зафиксировать sync-состояние: после restore локальная БД синхронизирована с этим tip,
#    поэтому последующий export пройдёт last-seen guard.
if [ ! -s "$SNAP" ]; then
  git config --local beads-sync.lastSeen "$remote_tip"
  echo "OK: снапшот пуст — импортировать нечего."
  exit 0
fi
bd import "$SNAP"
git config --local beads-sync.lastSeen "$remote_tip"

echo "OK: задачи восстановлены из ${REMOTE}/${BRANCH}"
