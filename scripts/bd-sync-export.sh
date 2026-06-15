#!/usr/bin/env bash
# Публикация снапшота задач Beads в служебную ветку beads-backup.
# Замена несуществующей в bd 1.0.2 команды `bd backup export-git --force`.
#
# КОНТРАКТ СИНХРОНИЗАЦИИ (важно — см. также .claude/rules/beads.md):
# Модель — снапшот .beads/issues.jsonl в ветке beads-backup. Это НЕ распределённый
# merge-движок (Dolt-merge намеренно запрещён каноном). Поэтому:
#  - export строит снапшот из ЛОКАЛЬНОЙ БД и публикует его как новый tip beads-backup;
#  - чтобы это не приводило к last-writer-wins потере чужих правок, export FAIL-CLOSED,
#    если origin/beads-backup продвинулся с момента последней синхронизации этого клона
#    (last-seen guard) ИЛИ если на remote есть задачи, отсутствующие локально (drop-guard).
#    В обоих случаях нужно сперва scripts/bd-sync-restore.sh, затем повторить export;
#  - контракт по сути «restore-before-export». Удаления задач не зеркалируются автоматически
#    (restore = upsert без prune; `bd delete` запрещён deny-правилом) — осознанное ограничение
#    snapshot-модели.
#
# Скрипт НИКОГДА не пишет .beads/issues.jsonl в рабочее дерево (только приватный mktemp-каталог),
# коммитит снапшот через temp-index плюминг и делает fast-forward push (force/delete запрещены).
#
# env: BD_SYNC_REMOTE (default origin), BD_SYNC_BRANCH (default beads-backup),
#      BD_SYNC_FORCE=1 (override last-seen/drop guard — напр. намеренное удаление задач).
set -euo pipefail

REMOTE="${BD_SYNC_REMOTE:-origin}"
BRANCH="${BD_SYNC_BRANCH:-beads-backup}"

# Guard: только из основного checkout. В git-worktree bd привязан к чужой dolt-базе и export
# опубликовал бы некорректный снапшот (known failure mode, .claude/rules/beads.md).
if [ "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ]; then
  echo "ОШИБКА: запуск из git-worktree запрещён — bd привязан к основному checkout." >&2
  exit 1
fi

# Приватная временная директория (umask 077, mktemp) — снапшот не читаем другим юзерам,
# нет symlink/race на предсказуемых путях.
umask 077
WORK=$(mktemp -d "${TMPDIR:-/tmp}/bd-sync.XXXXXX")
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
SNAP="$WORK/snap.jsonl"
IDX="$WORK/index"

# 1. Экспорт всех задач во временный файл.
bd export --all -o "$SNAP"
touch "$SNAP"
blob=$(git hash-object -w "$SNAP")

# 2. Родитель = актуальный remote tip. Явный destination-refspec для single-branch/CI-клонов.
parent=""
if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git fetch -q "$REMOTE" "+refs/heads/${BRANCH}:refs/remotes/${REMOTE}/${BRANCH}"
  parent=$(git rev-parse "refs/remotes/${REMOTE}/${BRANCH}")
elif git rev-parse --verify -q "refs/heads/${BRANCH}" >/dev/null; then
  parent=$(git rev-parse "refs/heads/${BRANCH}")
fi

# 2a. Last-seen guard (защита от stale-overwrite, в т.ч. правок той же задачи на другой машине).
#     Если remote tip изменился с момента последней синхронизации этого клона — fast-forward
#     push молча затёр бы чужие изменения. Отказываемся, требуем restore. Хранится в git config
#     (--local, per-clone, не коммитится — gitignore не нужен).
last_seen=$(git config --local --get beads-sync.lastSeen 2>/dev/null || true)
if [ -n "$parent" ] && [ -n "$last_seen" ] && [ "$last_seen" != "$parent" ] && [ "${BD_SYNC_FORCE:-}" != "1" ]; then
  echo "ОШИБКА: ${REMOTE}/${BRANCH} продвинулся с момента последней синхронизации этого клона." >&2
  echo "  last-seen: $last_seen" >&2
  echo "  remote:    $parent" >&2
  echo "Сначала: scripts/bd-sync-restore.sh (подтянуть чужие изменения), затем повтори export." >&2
  echo "Override (намеренная перезапись): BD_SYNC_FORCE=1." >&2
  exit 1
fi

# 2b. Снапшот, лежащий сейчас на remote (канонический путь либо legacy .beads/backup/).
remote_snap=""
if [ -n "$parent" ]; then
  remote_snap="$WORK/remote.jsonl"
  if ! git show "${parent}:.beads/issues.jsonl" > "$remote_snap" 2>/dev/null; then
    git show "${parent}:.beads/backup/issues.jsonl" > "$remote_snap" 2>/dev/null || : > "$remote_snap"
  fi
fi

# 2c. Drop-guard: не теряем задачи, существующие на remote, но отсутствующие в локальном снапшоте
#     (вторая линия защиты к last-seen). id извлекаются надёжным JSON-парсером (python3), с
#     fallback на grep если python3 нет. Override — BD_SYNC_FORCE=1.
if [ -n "$remote_snap" ] && [ -s "$remote_snap" ] && [ "${BD_SYNC_FORCE:-}" != "1" ]; then
  if command -v python3 >/dev/null 2>&1; then
    dropped=$(python3 - "$remote_snap" "$SNAP" <<'PY'
import json, sys
def ids(path):
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            i = obj.get("id")
            if i:
                out.add(i)
    return out
remote = ids(sys.argv[1]); new = ids(sys.argv[2])
print("\n".join(sorted(remote - new)))
PY
)
  else
    remote_ids=$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]+"' "$remote_snap" 2>/dev/null | sort -u || true)
    new_ids=$(grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]+"' "$SNAP" 2>/dev/null | sort -u || true)
    dropped=$(comm -23 <(printf '%s\n' "$remote_ids") <(printf '%s\n' "$new_ids") | grep -v '^$' || true)
  fi
  if [ -n "$dropped" ]; then
    echo "ОШИБКА: на ${BRANCH} есть задачи, отсутствующие в локальном снапшоте — публикация затёрла бы их:" >&2
    printf '%s\n' "$dropped" | sed 's/^/  - /' >&2
    echo "Сначала: scripts/bd-sync-restore.sh, затем повтори export. Override: BD_SYNC_FORCE=1." >&2
    exit 1
  fi
fi

# 2d. No-op skip: снапшот идентичен remote — не плодим пустой коммит, но фиксируем sync-состояние.
if [ -n "$parent" ]; then
  prev_blob=$(git rev-parse -q --verify "${parent}:.beads/issues.jsonl" 2>/dev/null || true)
  if [ "$prev_blob" = "$blob" ]; then
    git config --local beads-sync.lastSeen "$parent"
    echo "OK: снапшот не изменился относительно ${REMOTE}/${BRANCH} — публикация не требуется."
    exit 0
  fi
fi

# 3. Дерево из единственного файла .beads/issues.jsonl (во временном индексе).
GIT_INDEX_FILE="$IDX" git read-tree --empty
GIT_INDEX_FILE="$IDX" git update-index --add --cacheinfo "100644,${blob},.beads/issues.jsonl"
tree=$(GIT_INDEX_FILE="$IDX" git write-tree)

# 4. Fast-forward-коммит поверх remote tip.
msg="beads-backup: snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$parent" ]; then
  commit=$(git commit-tree "$tree" -p "$parent" -m "$msg")
else
  commit=$(git commit-tree "$tree" -m "$msg")
fi
git update-ref "refs/heads/${BRANCH}" "$commit"

# 5. Fast-forward push (без --force). При reject — откат локальной ветки + просьба перезапуска.
if ! git push "$REMOTE" "${BRANCH}"; then
  if [ -n "$parent" ]; then
    git update-ref "refs/heads/${BRANCH}" "$parent"
  else
    git update-ref -d "refs/heads/${BRANCH}"
  fi
  echo "ОШИБКА: push отклонён — ${REMOTE}/${BRANCH} ушёл вперёд. Перезапусти scripts/bd-sync-export.sh." >&2
  exit 1
fi

# 6. Зафиксировать sync-состояние этого клона (для last-seen guard следующего export).
git config --local beads-sync.lastSeen "$commit"

echo "OK: снапшот опубликован в ${REMOTE}/${BRANCH} (.beads/issues.jsonl)"
