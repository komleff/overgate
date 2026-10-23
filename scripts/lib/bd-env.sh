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
    echo "       Для чтения/записи из worktree используйте bash scripts/bd-wt.sh (явный --db)." >&2
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

# Основная база по режиму из <root>/.beads/metadata.json: embedded Dolt (.beads/embeddeddolt,
# без сервера) или dolt-сервер (.beads/dolt). Решает только dolt_mode: наличие обоих каталогов
# на выбор не влияет. Аргумент $1 — корень основного checkout. При успехе выставляет
# BD_ENV_DB_MODE (embedded|server) и BD_ENV_DB_PATH и возвращает 0. Коды отказа:
#   1 — fail-closed: нет/нечитаем/невалиден metadata.json, dolt_mode пуст или неизвестен,
#       нет каталога базы, не запустился Python (ошибка с путём — в stderr);
#   3 — режим server, путь определён, но живого dolt-сервера нет; сообщение печатает
#       вызывающий.
# Вызывать как `bd_env_resolve_main_db "$root" || rc=$?`, не в $(…): переменные нужны вызывающему.
# Прежние bd_env_main_db / bd_env_dolt_alive не меняются: на них опираются другие потребители.
bd_env_resolve_main_db() {
  local root="${1:-}" meta mode db launcher operator_hint rc=0
  BD_ENV_DB_MODE=""
  BD_ENV_DB_PATH=""
  if [ -z "$root" ]; then
    echo "ERROR: не удалось определить корень основного checkout (git worktree list)." >&2
    return 1
  fi
  meta="${root}/.beads/metadata.json"
  # Штатной команды bd, восстанавливающей dolt_mode, нет, а ручная правка .beads запрещена
  # каноном — поэтому шаг восстановления один: остановиться и передать решение оператору.
  operator_hint="       Остановитесь и обратитесь к оператору; .beads/** руками не правьте (.claude/rules/beads.md)."
  if [ ! -f "$meta" ]; then
    echo "ERROR: не найден файл режима базы Beads: ${meta} (fail-closed)." >&2
    echo "$operator_hint" >&2
    return 1
  fi
  # Python — только через переносимый launcher проекта: прямой python3 на Windows может
  # оказаться заглушкой Store. Launcher лежит в том же дереве, что и эта библиотека.
  launcher="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.claude/tools/run-python.sh"
  if [ ! -x "$launcher" ]; then
    echo "ERROR: нужен Python 3, чтобы прочитать ${meta}: launcher ${launcher} отсутствует или не исполним (fail-closed)." >&2
    return 1
  fi
  # Файл подаётся на stdin: путь не проходит преобразование путей Git Bash для нативного
  # Python, а отказ чтения файла остаётся кодом 1. -I — без модулей из cwd.
  # Коды Python: 1 — не читается / не JSON-объект, 2 — dolt_mode нет или не непустая строка,
  # 3 — неизвестное значение; 126/127 — launcher не нашёл исправный Python.
  mode="$("$launcher" -I -c '
import json, sys
try:
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
except (OSError, ValueError):
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
mode = data.get("dolt_mode")
if not isinstance(mode, str) or not mode:
    sys.exit(2)
if mode not in ("embedded", "server"):
    sys.exit(3)
sys.stdout.write(mode)
' 2>/dev/null <"$meta")" || rc=$?
  case "$rc" in
    0) ;;
    2) echo "ERROR: dolt_mode отсутствует или пуст в ${meta} — режим базы не определён (fail-closed)." >&2
       echo "$operator_hint" >&2
       return 1 ;;
    3) echo "ERROR: неизвестный dolt_mode в ${meta} — ожидается embedded или server (fail-closed)." >&2
       echo "$operator_hint" >&2
       return 1 ;;
    126|127) echo "ERROR: нужен Python 3, чтобы прочитать ${meta}: launcher ${launcher} не нашёл исправный Python (fail-closed)." >&2
       return 1 ;;
    *) echo "ERROR: ${meta} не читается или не является JSON-объектом (fail-closed)." >&2
       echo "$operator_hint" >&2
       return 1 ;;
  esac
  case "$mode" in
    embedded) db="${root}/.beads/embeddeddolt" ;;
    *) db="${root}/.beads/dolt" ;;
  esac
  if [ ! -d "$db" ]; then
    echo "ERROR: основная база Beads не найдена: ${db}" >&2
    echo "       dolt_mode ${mode} в ${meta} требует этот каталог (fail-closed)." >&2
    return 1
  fi
  BD_ENV_DB_MODE="$mode"
  BD_ENV_DB_PATH="$db"
  if [ "$mode" = "server" ] && ! bd_env_dolt_alive "$root"; then
    return 3
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
