#!/usr/bin/env bash
# Общие функции для beads-инструментов проекта: определение класса окружения,
# путь к основной базе, детект живого dolt-сервера, fetch снимка beads-backup.
#
# Источник истины — правила проекта .claude/rules/beads.md (доступ к Beads по классу окружения).
# Единый refspec и guard живут здесь, чтобы не было drift между потребителями
# (bd-apply-intents.sh, bd-sync-export.sh, bd-sync-restore.sh, bd-read.sh, bd-wt.sh).
#
# Файл предназначен для source, не для прямого запуска.

# Явный refspec публикации/чтения снимка задач. В shallow/single-branch clone
# простой `git fetch origin beads-backup` обновляет лишь FETCH_HEAD и оставляет
# refs/remotes/origin/beads-backup устаревшим — поэтому всегда явный refspec.
BD_BACKUP_BRANCH="beads-backup"
BD_BACKUP_REFSPEC="+refs/heads/${BD_BACKUP_BRANCH}:refs/remotes/origin/${BD_BACKUP_BRANCH}"

# Возвращает 0, если текущее дерево — основной checkout (не git-worktree).
# Критерий: в worktree --git-common-dir указывает на общий .git основного дерева,
# а --git-dir — на отдельный .git/worktrees/<name>; в основном дереве они равны.
bd_env_is_main_checkout() {
  local common git_dir
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 2
  git_dir="$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" || return 2
  [ "$common" = "$git_dir" ]
}

# Останавливает выполнение, если команда запущена из git-worktree (отличает linked worktree
# от обычного checkout). NB: standalone clone «вторым writer'ом» эту проверку проходит как main —
# идентичность КАНОНИЧЕСКОГО checkout технически не определима. Защита от реальной потери задач
# (content-clobber вторым writer'ом) — в bd-sync-export.sh: divergence/shrink-guard + non-force push.
# Аргумент $1 — человекочитаемое имя команды для сообщения.
bd_env_assert_main_checkout() {
  local who="${1:-эта команда}"
  if ! bd_env_is_main_checkout; then
    echo "ERROR: ${who} должна запускаться из основного checkout, не из git-worktree." >&2
    echo "       В worktree прямой bd с auto-discovery создаёт пустую базу и рвёт синхронизацию." >&2
    echo "       Для чтения/записи из worktree используйте scripts/bd-wt.sh (явный --db)." >&2
    echo "       Канон — .claude/rules/beads.md и правила проекта .claude/rules/beads.md." >&2
    return 1
  fi
}

# Корень основного worktree. git worktree list всегда выводит главное дерево
# первым — берём его (устойчиво к вынесенному git-dir / .git-файлу / layout).
bd_env_main_root() {
  git worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | head -1
}

# Путь к основной базе Dolt с валидацией существования. Печатает путь в stdout
# либо возвращает ненулевой код и пишет ошибку в stderr (не угадываем).
bd_env_main_db() {
  local root db
  root="$(bd_env_main_root)"
  if [ -z "$root" ]; then
    echo "ERROR: не удалось определить корень основного checkout (git worktree list)." >&2
    return 2
  fi
  db="${root}/.beads/dolt"
  if [ ! -d "$db" ]; then
    echo "ERROR: основная база Beads не найдена: ${db}" >&2
    echo "       Ожидался каталог .beads/dolt в основном checkout: ${root}" >&2
    return 1
  fi
  printf '%s\n' "$db"
}

# Детект живого dolt-сервера основного checkout ЧИСТО OS-средствами, без вызова
# bd (любая bd-команда автостартует `bd dolt start` — пробой через bd сам поднял
# бы сервер). Аргумент $1 — корень основного checkout. Возвращает 0, если жив.
bd_env_dolt_alive() {
  # Тест-сем: позволяет харнессам считать сервер живым без реального dolt.
  [ "${BD_ENV_ASSUME_DOLT_ALIVE:-0}" = "1" ] && return 0
  local root="$1" pidf portf pid port
  pidf="${root}/.beads/dolt-server.pid"
  portf="${root}/.beads/dolt-server.port"
  [ -f "$pidf" ] && [ -s "$portf" ] || return 1
  pid="$(cat "$pidf" 2>/dev/null)"
  port="$(cat "$portf" 2>/dev/null)"
  [ -n "$pid" ] && [ -n "$port" ] || return 1
  # Процесс с этим pid жив И это dolt (защита от PID-reuse).
  ps -p "$pid" -o command= 2>/dev/null | grep -qi 'dolt' || return 1
  # Порт реально слушается (если lsof доступен — иначе довольствуемся pid-проверкой).
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 1
  fi
  return 0
}

# Свежий снимок задач из origin/beads-backup явным refspec.
bd_env_fetch_backup() {
  git fetch -q origin "$BD_BACKUP_REFSPEC"
}

# Детерминированный slug имени (для имени receipt-файла и т.п.): '/' и пробелы → '-',
# прочее не-[alnum._-] вырезается, длина ≤100. Имена git-веток не содержат пробелов/
# control-символов, поэтому коллизии практически исключены; при сомнении — явный путь.
bd_env_slugify() {
  printf '%s' "$1" | tr '/[:space:]' '--' | tr -cd '[:alnum:]._-' | cut -c1-100
}
