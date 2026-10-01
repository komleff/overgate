#!/usr/bin/env bash
# Чтение задач Beads из снимка origin/beads-backup без bd и без базы.
# Для облачного контейнера (нет bd) и для быстрого чтения из worktree. правила проекта .claude/rules/beads.md.
#
# Usage:
#   scripts/bd-read.sh list  [--status S] [--priority N] [--assignee A] [--type T] [--json]
#   scripts/bd-read.sh show  <id> [--json]
#   scripts/bd-read.sh ready [--json]
#
# Env:
#   BD_READ_REF=origin/beads-backup   ref снимка (по умолчанию); авто-fetch только для него,
#                                     кастомный ref читается как есть (fetch'ит вызывающий)
#   BD_READ_NO_FETCH=1                не делать fetch (читать закэшированный ref)
#   BD_READ_FIXTURE=path              читать из локального JSONL (для тестов)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/bd-env.sh
. "${SCRIPT_DIR}/lib/bd-env.sh"

REF="${BD_READ_REF:-origin/${BD_BACKUP_BRANCH}}"
ENGINE="${SCRIPT_DIR}/lib/bd-read-engine.mjs"

if [ $# -lt 1 ]; then
  echo "Usage: bd-read.sh <list|show <id>|ready> [флаги]" >&2
  exit 1
fi

# Источник снимка: фикстура (тесты) либо git-объект ref'а.
read_snapshot() {
  if [ -n "${BD_READ_FIXTURE:-}" ]; then
    cat "$BD_READ_FIXTURE"
    return
  fi
  # Авто-fetch только для КАНОНИЧЕСКОГО ref (origin/beads-backup): bd_env_fetch_backup
  # обновляет именно его. Кастомный BD_READ_REF (напр. локальный/другой ref) читается
  # как есть — им управляет вызывающий (иначе fetch не соответствовал бы REF).
  if [ -z "${BD_READ_NO_FETCH:-}" ] && [ "$REF" = "origin/${BD_BACKUP_BRANCH}" ]; then
    # fail-closed по умолчанию: устаревший снимок → неверные заявки. Stale-чтение —
    # только явным BD_READ_NO_FETCH=1.
    if ! bd_env_fetch_backup; then
      echo "ERROR: fetch ${REF} не удался — снимок мог устареть (fail-closed)." >&2
      echo "       Проверьте git-доступ; для чтения закэшированного снимка — BD_READ_NO_FETCH=1." >&2
      return 1
    fi
  fi
  if ! git show "${REF}:.beads/issues.jsonl" 2>/dev/null; then
    echo "ERROR: снимок ${REF}:.beads/issues.jsonl не найден." >&2
    echo "       Проверьте git-доступ к origin и наличие ветки beads-backup." >&2
    return 1
  fi
}

# Снимок получаем целиком ДО движка: при ошибке git show node иначе получил бы пустой stdin
# и напечатал «(нет задач)» прежде, чем pipeline упадёт по pipefail — двусмысленный вывод.
SNAP="$(mktemp "${TMPDIR:-/tmp}/overgate-bd-read.XXXXXX")"
trap 'rm -f "$SNAP"' EXIT
if ! read_snapshot > "$SNAP"; then
  exit 1
fi
node "$ENGINE" "$@" < "$SNAP"
