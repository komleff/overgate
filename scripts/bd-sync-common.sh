#!/usr/bin/env bash
# Общие проверки для bd-sync-export.sh / bd-sync-restore.sh.
# Это библиотека — её НЕ запускают напрямую, а source'ят. Использует переменные REMOTE и BRANCH
# из вызывающего скрипта.

# This sourced guard executes before any Git read in legacy export/restore.
# Child Git and bd inherit the same isolated repository/config context.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/bd-env.sh"
bd_env_sanitize_git

# Валидация env-параметров + guard окружения. Возврат 0 — ок, 1 — ошибка (вызывающий делает exit).
bd_sync_validate() {
  BD_SYNC_VALIDATED_PRESENT=0
  BD_SYNC_VALIDATED_TIP=""
  # Whitelist ветки (а не blacklist — последний неполон: BD_SYNC_BRANCH=feature/x схлопнул бы
  # рабочую ветку до snapshot-файла). Разрешены только канон-ветка и её именованные варианты.
  case "$BRANCH" in
    beads-backup|beads-backup-*) ;;
    *)
      echo "ОШИБКА: BD_SYNC_BRANCH='$BRANCH' — разрешены только 'beads-backup' или 'beads-backup-*'." >&2
      return 1 ;;
  esac
  if ! git check-ref-format "refs/heads/${BRANCH}"; then
    echo "ОШИБКА: BD_SYNC_BRANCH='$BRANCH' — некорректное имя git-ветки." >&2
    return 1
  fi
  # REMOTE — только настроенный named remote (исключает refspec/path abuse).
  if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "ОШИБКА: BD_SYNC_REMOTE='$REMOTE' — не настроенный named remote." >&2
    return 1
  fi
  # Только из основного checkout: в git-worktree bd привязан к чужой dolt-базе (known failure
  # mode, .claude/rules/beads.md). В linked-worktree git-dir != git-common-dir.
  if [ "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ]; then
    echo "ОШИБКА: запуск из git-worktree запрещён — bd привязан к основному checkout." >&2
    return 1
  fi
  # Старый export/restore не может писать поверх managed protocol, даже если этот
  # clone ещё не зарегистрирован: marker проверяется на свежем remote tip.
  if git config --local --get overgate.beadsPublisher >/dev/null 2>&1; then
    echo "ОШИБКА: managed publisher зарегистрирован; legacy sync запрещён. Используй trusted typed queue publisher." >&2
    return 1
  fi
  local remote_rc=0
  git ls-remote --exit-code --heads "$REMOTE" "refs/heads/${BRANCH}" >/dev/null 2>&1 || remote_rc=$?
  case "$remote_rc" in
    0)
      if [ "$(git rev-parse --is-shallow-repository)" = "true" ]; then
        echo "ОШИБКА: partial history не подтверждает отсутствие managed protocol; legacy sync остановлен." >&2
        return 1
      fi
      if ! git fetch -q "$REMOTE" "+refs/heads/${BRANCH}:refs/remotes/${REMOTE}/${BRANCH}"; then
        echo "ОШИБКА: не удалось подтвердить remote task state перед legacy sync (fail-closed)." >&2
        return 1
      fi
      local frozen_tip
      if ! frozen_tip="$(git rev-parse --verify "refs/remotes/${REMOTE}/${BRANCH}^{commit}" 2>/dev/null)"; then
        echo "ОШИБКА: fetched task ref не разрешён в commit SHA; legacy sync остановлен." >&2
        return 1
      fi
      if git cat-file -e "${frozen_tip}:.beads/overgate-managed-v1.json" 2>/dev/null \
        || git cat-file -e "${frozen_tip}:.beads/overgate-outcomes-v1.json" 2>/dev/null; then
        echo "ОШИБКА: remote managed protocol активен; legacy sync запрещён. Используй managed publisher." >&2
        return 1
      fi
      local protocol_history
      if ! protocol_history="$(git log -1 --format=%H "$frozen_tip" -- .beads/overgate-managed-v1.json .beads/overgate-outcomes-v1.json)"; then
        echo "ОШИБКА: remote protocol history недоступна; legacy sync остановлен." >&2
        return 1
      fi
      if [ -n "$protocol_history" ]; then
        echo "ОШИБКА: remote managed protocol был удалён (downgrade); legacy sync запрещён." >&2
        return 1
      fi
      BD_SYNC_VALIDATED_PRESENT=1
      BD_SYNC_VALIDATED_TIP="$frozen_tip" ;;
    2)
      # Отсутствие ветки на remote не доказывает fresh state, если этот clone
      # уже видел её историю. Иначе старый writer может восстановить удалённый
      # managed marker как legacy snapshot.
      if git show-ref --verify --quiet "refs/remotes/${REMOTE}/${BRANCH}" \
        || git show-ref --verify --quiet "refs/heads/${BRANCH}" \
        || { [ "$BRANCH" = beads-backup ] \
          && [ -n "$(git config --local --get beads-sync.lastSeen 2>/dev/null || true)" ]; }; then
        echo "ОШИБКА: remote task branch отсутствует, но локальная история/lastSeen существует; legacy sync остановлен (fail-closed)." >&2
        return 1
      fi ;;
    *) echo "ОШИБКА: remote task state недоступен; legacy sync остановлен (fail-closed)." >&2; return 1 ;;
  esac
}
