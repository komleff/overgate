#!/usr/bin/env bash
# Публикация снапшота задач Beads в служебную ветку beads-backup.
# Замена несуществующей в bd 1.0.2 команды `bd backup export-git --force`.
#
# Канон: source of truth — снапшот .beads/issues.jsonl в ветке beads-backup.
# Скрипт НИКОГДА не пишет .beads/issues.jsonl в рабочее дерево (только $TMPDIR),
# коммитит снапшот в beads-backup через temp-index плюминг и делает
# fast-forward push (force-push/branch-delete запрещены политикой репозитория).
#
# Запускать ТОЛЬКО из основного checkout (не из git-worktree) — см. .claude/rules/beads.md.
set -euo pipefail

BRANCH="beads-backup"
TMP="${TMPDIR:-/tmp}"
SNAP="${TMP}/bd-snap-$$.jsonl"
IDX="${TMP}/bd-bb-index-$$"
cleanup() { rm -f "$SNAP" "$IDX"; }
trap cleanup EXIT

# 1. Экспорт всех задач во временный файл (в рабочее дерево ничего не пишем).
bd export --all -o "$SNAP"
touch "$SNAP"   # гарантируем существование файла даже при нуле задач
blob=$(git hash-object -w "$SNAP")

# 2. Родитель коммита — ВСЕГДА актуальный remote tip (origin/beads-backup). Это важно для
#    переносимости между машинами: если строить snapshot поверх устаревшей локальной ветки,
#    push отклонится как non-fast-forward, а локальная beads-backup останется в расходящемся
#    состоянии. Поэтому сначала fetch, parent = origin tip; локальную ветку используем только
#    когда remote-ветки ещё нет (первая публикация).
parent=""
if git ls-remote --exit-code --heads origin "${BRANCH}" >/dev/null 2>&1; then
  # Явный destination-refspec: на single-branch/CI-клонах (remote.origin.fetch сужен до
  # default-ветки) обычный `git fetch origin <branch>` НЕ обновляет refs/remotes/origin/<branch>,
  # и rev-parse ниже упал бы. Принудительно пишем remote-tracking ref.
  git fetch -q origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}"
  parent=$(git rev-parse "refs/remotes/origin/${BRANCH}")
elif git rev-parse --verify -q "refs/heads/${BRANCH}" >/dev/null; then
  parent=$(git rev-parse "refs/heads/${BRANCH}")
fi

# 2a. Защита от перезаписи: если локальный export пуст, а на beads-backup уже есть НЕПУСТОЙ
#     снапшот — отказ (иначе деградированная/пустая база затрёт реальные задачи пустым файлом,
#     known failure mode из правил). Пустой трекер — легитимен (свежий проект): override
#     через BD_SYNC_ALLOW_EMPTY=1. Пустой→пустой и первая публикация проходят без override.
if [ ! -s "$SNAP" ] && [ -n "$parent" ] && git cat-file -e "${parent}:.beads/issues.jsonl" 2>/dev/null; then
  remote_size=$(git cat-file -s "${parent}:.beads/issues.jsonl" 2>/dev/null || echo 0)
  if [ "$remote_size" -gt 0 ] && [ "${BD_SYNC_ALLOW_EMPTY:-}" != "1" ]; then
    echo "ОШИБКА: bd export вернул пустой снапшот, а на ${BRANCH} есть непустой (${remote_size} б)." >&2
    echo "Публикация отменена (защита от перезаписи). Если трекер действительно пуст — BD_SYNC_ALLOW_EMPTY=1." >&2
    exit 1
  fi
fi

# 3. Дерево из единственного файла .beads/issues.jsonl (стандартный путь снапшота).
#    Сборка во временном индексе — рабочий индекс/дерево не трогаем.
rm -f "$IDX"
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

# 5. Fast-forward push (без --force). Если origin ушёл вперёд между fetch и push — откатываем
#    локальную ветку к remote tip (не оставляем её в расходящемся состоянии) и просим перезапуск.
if ! git push origin "${BRANCH}"; then
  if [ -n "$parent" ]; then
    git update-ref "refs/heads/${BRANCH}" "$parent"
  else
    git update-ref -d "refs/heads/${BRANCH}"
  fi
  echo "ОШИБКА: push отклонён — origin/${BRANCH} ушёл вперёд. Перезапусти scripts/bd-sync-export.sh (заберёт свежий tip)." >&2
  exit 1
fi

echo "OK: снапшот опубликован в origin/${BRANCH} (.beads/issues.jsonl)"
