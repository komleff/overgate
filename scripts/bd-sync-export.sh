#!/usr/bin/env bash
# Публикация снапшота задач Beads в служебную ветку beads-backup.
# Замена несуществующей в bd 1.0.2 команды `bd backup export-git --force`.
#
# Канон: source of truth — снапшот .beads/issues.jsonl в ветке beads-backup.
# Скрипт НИКОГДА не пишет .beads/issues.jsonl в рабочее дерево (только приватный
# mktemp-каталог), коммитит снапшот в beads-backup через temp-index плюминг и делает
# fast-forward push (force-push/branch-delete запрещены политикой репозитория).
#
# Параметры через env: BD_SYNC_REMOTE (default origin), BD_SYNC_BRANCH (default beads-backup),
# BD_SYNC_FORCE=1 (разрешить публикацию, теряющую задачи с remote — напр. намеренное удаление).
set -euo pipefail

REMOTE="${BD_SYNC_REMOTE:-origin}"
BRANCH="${BD_SYNC_BRANCH:-beads-backup}"

# Guard: запуск только из основного checkout. В git-worktree bd привязан к чужой
# dolt-базе и export опубликовал бы некорректный/пустой снапшот (known failure mode,
# см. .claude/rules/beads.md). В linked-worktree git-dir != git-common-dir.
if [ "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ]; then
  echo "ОШИБКА: запуск из git-worktree запрещён — bd привязан к основному checkout." >&2
  exit 1
fi

# Приватная временная директория (umask 077) — снапшот задач не должен быть читаем
# другим локальным пользователям; mktemp устраняет symlink/race на предсказуемых путях.
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/bd-sync.XXXXXX")
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
SNAP="$WORK/snap.jsonl"
IDX="$WORK/index"

# 1. Экспорт всех задач во временный файл (в рабочее дерево ничего не пишем).
bd export --all -o "$SNAP"
touch "$SNAP"   # гарантируем существование файла даже при нуле задач
blob=$(git hash-object -w "$SNAP")

# 2. Родитель коммита — ВСЕГДА актуальный remote tip. Явный destination-refspec нужен
#    для single-branch/CI-клонов (remote.origin.fetch сужен): обычный `git fetch origin <b>`
#    там не обновляет remote-tracking ref. Локальную ветку берём только если remote-ветки нет.
parent=""
if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git fetch -q "$REMOTE" "+refs/heads/${BRANCH}:refs/remotes/${REMOTE}/${BRANCH}"
  parent=$(git rev-parse "refs/remotes/${REMOTE}/${BRANCH}")
elif git rev-parse --verify -q "refs/heads/${BRANCH}" >/dev/null; then
  parent=$(git rev-parse "refs/heads/${BRANCH}")
fi

# 2a. Снапшот, лежащий сейчас на remote (канонический путь либо legacy .beads/backup/).
remote_snap=""
if [ -n "$parent" ]; then
  remote_snap="$WORK/remote.jsonl"
  if ! git show "${parent}:.beads/issues.jsonl" > "$remote_snap" 2>/dev/null; then
    git show "${parent}:.beads/backup/issues.jsonl" > "$remote_snap" 2>/dev/null || : > "$remote_snap"
  fi
fi

# 2b. Drop-guard (защита от потери задач при multi-clone). Снапшот строится из локальной
#     БД; если на remote есть задачи, отсутствующие локально (другая машина опубликовала
#     раньше, а мы не сделали restore) — fast-forward push молча затёр бы их. Отказываемся,
#     перечисляя теряемые id. Покрывает и пустой-поверх-непустого (все id теряются).
#     Override намеренного удаления — BD_SYNC_FORCE=1.
if [ -n "$remote_snap" ] && [ -s "$remote_snap" ] && [ "${BD_SYNC_FORCE:-}" != "1" ]; then
  remote_ids=$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]+"' "$remote_snap" 2>/dev/null | sort -u || true)
  new_ids=$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]+"' "$SNAP" 2>/dev/null | sort -u || true)
  dropped=$(comm -23 <(printf '%s\n' "$remote_ids") <(printf '%s\n' "$new_ids") | grep -v '^$' || true)
  if [ -n "$dropped" ]; then
    echo "ОШИБКА: на ${BRANCH} есть задачи, отсутствующие в локальном снапшоте — публикация затёрла бы их:" >&2
    printf '%s\n' "$dropped" | sed 's/^/  - /' >&2
    echo "Сначала: scripts/bd-sync-restore.sh (подтянуть удалённое состояние), затем повтори export." >&2
    echo "Если потеря намеренная (удаление задач) — BD_SYNC_FORCE=1." >&2
    exit 1
  fi
fi

# 2c. No-op skip: если снапшот идентичен тому, что уже на remote — не плодим пустой коммит.
if [ -n "$parent" ]; then
  prev_blob=$(git rev-parse -q --verify "${parent}:.beads/issues.jsonl" 2>/dev/null || true)
  if [ "$prev_blob" = "$blob" ]; then
    echo "OK: снапшот не изменился относительно ${REMOTE}/${BRANCH} — публикация не требуется."
    exit 0
  fi
fi

# 3. Дерево из единственного файла .beads/issues.jsonl (стандартный путь снапшота).
#    Сборка во временном индексе — рабочий индекс/дерево не трогаем.
GIT_INDEX_FILE="$IDX" git read-tree --empty
GIT_INDEX_FILE="$IDX" git update-index --add --cacheinfo "100644,${blob},.beads/issues.jsonl"
tree=$(GIT_INDEX_FILE="$IDX" git write-tree)

# 4. Fast-forward-коммит поверх remote tip + обновление локального ref.
msg="beads-backup: snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$parent" ]; then
  commit=$(git commit-tree "$tree" -p "$parent" -m "$msg")
else
  commit=$(git commit-tree "$tree" -m "$msg")
fi
git update-ref "refs/heads/${BRANCH}" "$commit"

# 5. Fast-forward push (без --force). Если remote ушёл вперёд между fetch и push — откатываем
#    локальную ветку к remote tip (не оставляем расходящееся состояние) и просим перезапуск.
if ! git push "$REMOTE" "${BRANCH}"; then
  if [ -n "$parent" ]; then
    git update-ref "refs/heads/${BRANCH}" "$parent"
  else
    git update-ref -d "refs/heads/${BRANCH}"
  fi
  echo "ОШИБКА: push отклонён — ${REMOTE}/${BRANCH} ушёл вперёд. Перезапусти scripts/bd-sync-export.sh (заберёт свежий tip)." >&2
  exit 1
fi

echo "OK: снапшот опубликован в ${REMOTE}/${BRANCH} (.beads/issues.jsonl)"
