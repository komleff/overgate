#!/usr/bin/env bash
# Общие проверки для bd-sync-export.sh / bd-sync-restore.sh.
# Это библиотека — её НЕ запускают напрямую, а source'ят. Использует переменные REMOTE и BRANCH
# из вызывающего скрипта.

# Валидация env-параметров + guard окружения. Возврат 0 — ок, 1 — ошибка (вызывающий делает exit).
bd_sync_validate() {
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
}
