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

# Legacy dispatch must classify the real repository-local origin before any bd
# mutation/import. Remove caller Git config, URL rewrite, index and namespace
# overrides before the first Git command; keep local credential/identity config.
bd_env_sanitize_git() {
  local git_name
  for git_name in "${!GIT_@}"; do
    case "$git_name" in GIT_AUTHOR_NAME|GIT_AUTHOR_EMAIL|GIT_AUTHOR_DATE|GIT_COMMITTER_NAME|GIT_COMMITTER_EMAIL|GIT_COMMITTER_DATE) ;;
      *) unset "$git_name" ;;
    esac
  done
  case "${OSTYPE:-}" in msys*|cygwin*|mingw*) GIT_CONFIG_GLOBAL=NUL ;; *) GIT_CONFIG_GLOBAL=/dev/null ;; esac
  export GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
}

# Git Bash видит путь /d/..., но нативный Node ожидает D:/... даже при
# пробелах, кириллице и апострофе. Преобразуем только operand модуля.
bd_env_native_path() {
  local original="${1:-}" converted
  [ -n "$original" ] || return 1
  if command -v cygpath >/dev/null 2>&1; then
    converted="$(cygpath -m "$original")" || return 1
    [ -n "$converted" ] || return 1
    printf '%s\n' "$converted"
    return 0
  fi
  case "${OSTYPE:-}" in msys*|cygwin*|mingw*) return 1 ;; esac
  printf '%s\n' "$original"
}

# Local legacy cutover fence is checked by every old OverGate writer entry
# before native bd or a task-branch publication. Either control artifact keeps
# the fence closed if one half of an interrupted install is present.
bd_env_legacy_fenced() {
  local config_rc=0 common marker
  git config --local --get overgate.beadsLegacyFence >/dev/null 2>&1 || config_rc=$?
  [ "$config_rc" = 0 ] && return 0
  [ "$config_rc" = 1 ] || return 0
  # --git-path resolves inside .git/worktrees/<linked> for linked worktrees,
  # while the reviewed marker lives in the shared main Git directory.
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 0
  [ -n "$common" ] || return 0
  marker="${common%/}/overgate-bd-legacy-fence.json"
  [ -e "$marker" ] || [ -L "$marker" ]
}

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

# ---------------------------------------------------------------------------
# og-4py, ADR §3.39: сетевые вызовы Git (ls-remote/fetch/push) и commit-tree снимка получают
# перенос allowlist пользовательского config (credential.*, user.name, user.email) через
# приватный временный GIT_CONFIG_GLOBAL. bd_env_sanitize_git остаётся чистой изоляцией.
# Спецификация общая с scripts/lib/bd-git-environment.mjs и scripts/install-overgate.py.
BD_ENV_USER_CONFIG_PATTERN='^(credential\..+|user\.name|user\.email)$'
BD_ENV_RESIDUAL_CONFIG_PATTERN='^(http\..+|url\..+\.(insteadof|pushinsteadof)|core\.sshcommand|author\..+|committer\..+|commit\.gpgsign|gpg\..+)$'
BD_ENV_NETWORK_DIR=""
BD_ENV_NETWORK_CONFIG=""
BD_ENV_NETWORK_ROOT=""

# Удаляет временный файл переноса; идемпотентна, вызывается ловушками и перед exec.
bd_env_network_cleanup() {
  if [ -n "${BD_ENV_NETWORK_DIR:-}" ]; then rm -rf "$BD_ENV_NETWORK_DIR"; fi
  BD_ENV_NETWORK_DIR=""
  BD_ENV_NETWORK_CONFIG=""
  BD_ENV_NETWORK_ROOT=""
}

# Ключ печатается без userinfo URL: в subsection может оказаться токен.
bd_env_redact_key() {
  printf '%s' "$1" | sed -E 's#(://)[^/@]*@#\1<userinfo>@#g'
}

# Цепочка к существующим ловушкам EXIT/INT/TERM (не замена). В subshell `trap -p`
# показывает ловушки родителя, которые там не действуют, — ставим собственные.
bd_env_network_traps() {
  local sig existing previous
  for sig in EXIT INT TERM; do
    previous=""
    if [ "${BASH_SUBSHELL:-0}" = 0 ]; then
      existing="$(trap -p "$sig")"
      if [ -n "$existing" ]; then
        eval "set -- $existing"
        previous="${3:-}"
      fi
    fi
    case "$previous" in *bd_env_network_cleanup*) continue ;; esac
    case "$sig" in
      EXIT) trap "bd_env_network_cleanup${previous:+; $previous}" EXIT ;;
      INT) trap "bd_env_network_cleanup; ${previous:-exit 130}" INT ;;
      TERM) trap "bd_env_network_cleanup; ${previous:-exit 143}" TERM ;;
    esac
  done
}

# Экранирование для синтаксиса git config посимвольно: подстановка ${v//…} в bash 3.2 и
# 5.2 по-разному обрабатывает обратную косую в замене. subsection: \ и "; value: ещё \n \t \b.
bd_env_config_escape() { # <subsection|value> <text>
  local mode="$1" text="$2" out="" index character
  for (( index=0; index<${#text}; index++ )); do
    character="${text:index:1}"
    case "$character" in
      \\) out="$out\\\\" ;;
      \") out="$out\\\"" ;;
      $'\n') if [ "$mode" = value ]; then out="$out\\n"; else out="$out$character"; fi ;;
      $'\t') if [ "$mode" = value ]; then out="$out\\t"; else out="$out$character"; fi ;;
      $'\b') if [ "$mode" = value ]; then out="$out\\b"; else out="$out$character"; fi ;;
      *) out="$out$character" ;;
    esac
  done
  printf '%s' "$out"
}

bd_env_network_fail() {
  echo "ERROR: $1 (fail-closed)." >&2
  bd_env_network_cleanup
  return 1
}

# Вывод reader: файл OVERGATE_GIT_USER_CONFIG_FILE (seam) либо git config без caller GIT_*
# (иначе GIT_CONFIG_NOSYSTEM родительского маршрута теряет scope system/unknown).
bd_env_user_config_raw() { # <root> <pattern> <output> [--name-only]
  local root="$1" pattern="$2" output="$3" rc=0
  shift 3
  if [ -n "${OVERGATE_GIT_USER_CONFIG_FILE+x}" ]; then
    [ -f "$OVERGATE_GIT_USER_CONFIG_FILE" ] && [ -r "$OVERGATE_GIT_USER_CONFIG_FILE" ] \
      && cat "$OVERGATE_GIT_USER_CONFIG_FILE" > "$output" && return 0
    echo "ERROR: OVERGATE_GIT_USER_CONFIG_FILE is set but unreadable (fail-closed)." >&2
    return 2
  fi
  (
    for git_name in "${!GIT_@}"; do unset "$git_name"; done
    export GIT_TERMINAL_PROMPT=0
    cd "$root" && git config "$@" --show-scope --includes -z --get-regexp "$pattern"
  ) > "$output" 2>/dev/null || rc=$?
  case "$rc" in
    0) return 0 ;;
    1) : > "$output"; return 0 ;;
    *) echo "ERROR: user Git config reader failed (exit ${rc}); Git >= 2.26 with --show-scope is required (fail-closed)." >&2
       return 2 ;;
  esac
}

# Готовит перенос для <root> лениво, один раз на процесс; путь — в BD_ENV_NETWORK_CONFIG
# (не экспортируется: exec-окружение и дочерние процессы его не получают).
bd_env_network_prepare() { # <root>
  local root="${1:-}" dir cfg raw scope record key value last
  local key_shape='^[A-Za-z0-9-]+(\..*)?\.[A-Za-z][A-Za-z0-9-]*$'
  [ -n "$root" ] || root="$(git rev-parse --show-toplevel 2>/dev/null)" || root=""
  [ -n "$root" ] || { echo "ERROR: network Git root unavailable (fail-closed)." >&2; return 1; }
  if [ -n "$BD_ENV_NETWORK_CONFIG" ] && [ "$BD_ENV_NETWORK_ROOT" = "$root" ] && [ -f "$BD_ENV_NETWORK_DIR/config" ]; then
    return 0
  fi
  bd_env_network_cleanup
  bd_env_network_traps
  dir="$(umask 077 && mktemp -d "${TMPDIR:-/tmp}/overgate-git-net.XXXXXX")" \
    || { echo "ERROR: private network Git config directory unavailable (fail-closed)." >&2; return 1; }
  BD_ENV_NETWORK_DIR="$dir"
  chmod 700 "$dir" || { bd_env_network_fail 'private network Git config directory mode'; return 1; }
  cfg="$dir/config"
  raw="$dir/user-config.raw"
  (umask 077 && : > "$cfg" && : > "$raw") || { bd_env_network_fail 'private network Git config file unavailable'; return 1; }
  bd_env_user_config_raw "$root" "$BD_ENV_USER_CONFIG_PATTERN" "$raw" || { bd_env_network_cleanup; return 1; }
  if [ -s "$raw" ]; then
    last="$(tail -c 1 "$raw" | od -An -tx1 | tr -d ' \n')"
    [ "$last" = 00 ] || { bd_env_network_fail 'user Git config framing invalid'; return 1; }
  fi
  # Каждая запись — собственная секция в порядке вывода reader: `git config --add` дописал бы
  # ключ в существующую одноимённую секцию и поменял порядок списка helper. Ключ без значения
  # пишется без `=`. Затем read-back тем же git сверяет перенос с записями reader.
  local expected="$dir/expected" readback="$dir/readback" section variable subsection residue canonical escaped valued
  (umask 077 && : > "$expected") || { bd_env_network_fail 'private network Git config file unavailable'; return 1; }
  while IFS= read -r -d '' scope; do
    IFS= read -r -d '' record || { bd_env_network_fail 'user Git config framing invalid'; return 1; }
    case "$record" in
      *$'\n'*) key="${record%%$'\n'*}"; value="${record#*$'\n'}"; valued=1 ;;
      *) key="$record"; value=""; valued=0 ;;
    esac
    [[ "$key" =~ $key_shape ]] || { bd_env_network_fail 'user Git config key framing invalid'; return 1; }
    case "$scope" in
      system|global|unknown) ;;
      local|worktree|command) continue ;;
      *) bd_env_network_fail 'user Git config scope invalid'; return 1 ;;
    esac
    [[ "$key" =~ $BD_ENV_USER_CONFIG_PATTERN ]] || continue
    section="${key%%.*}"
    variable="${key##*.}"
    subsection=""
    [ "$section.$variable" = "$key" ] || { subsection="${key#*.}"; subsection="${subsection%.*}"; }
    residue="${value//[$'\n\t\b']/}"
    if [[ "$residue" == *[[:cntrl:]]* ]]; then
      bd_env_network_fail "user Git config value/key unsupported for transfer: $(bd_env_redact_key "$key")"
      return 1
    fi
    canonical="$(printf '%s' "$section" | tr '[:upper:]' '[:lower:]')"
    if [ "$section.$variable" = "$key" ]; then
      printf '[%s]\n' "$section" >> "$cfg"
    else
      escaped="$(bd_env_config_escape subsection "$subsection")"
      printf '[%s "%s"]\n' "$section" "$escaped" >> "$cfg"
      canonical="$canonical.$subsection"
    fi
    canonical="$canonical.$(printf '%s' "$variable" | tr '[:upper:]' '[:lower:]')"
    if [ "$valued" = 1 ]; then
      escaped="$(bd_env_config_escape value "$value")"
      printf '\t%s = "%s"\n' "$variable" "$escaped" >> "$cfg"
      printf '%s\n%s\0' "$canonical" "$value" >> "$expected"
    else
      printf '\t%s\n' "$variable" >> "$cfg"
      printf '%s\0' "$canonical" >> "$expected"
    fi
  done < "$raw"
  rm -f "$raw"
  local readback_rc=0
  git config --file "$cfg" -z --list > "$readback" 2>/dev/null || readback_rc=$?
  # Побайтное сравнение через od: cmp не гарантирован в каждой поставке Git Bash.
  if { [ "$readback_rc" != 0 ] && { [ "$readback_rc" != 1 ] || [ -s "$cfg" ]; }; } \
    || [ "$(od -An -v -tx1 "$expected")" != "$(od -An -v -tx1 "$readback")" ]; then
    bd_env_network_fail 'user Git config transfer read-back mismatch'
    return 1
  fi
  rm -f "$expected" "$readback"
  chmod 600 "$cfg" || { bd_env_network_fail 'private network Git config file mode'; return 1; }
  BD_ENV_NETWORK_CONFIG="$(bd_env_native_path "$cfg")" \
    || { bd_env_network_fail 'native network Git config path unavailable'; return 1; }
  BD_ENV_NETWORK_ROOT="$root"
}

# Только имена и scope residual-ключей (значения не читаются, --name-only).
bd_env_network_residual() { # <root>
  local root="$1" tmp scope key
  [ -z "${OVERGATE_GIT_USER_CONFIG_FILE+x}" ] || return 0
  tmp="$(umask 077 && mktemp "${TMPDIR:-/tmp}/overgate-git-residual.XXXXXX")" || return 0
  if bd_env_user_config_raw "$root" "$BD_ENV_RESIDUAL_CONFIG_PATTERN" "$tmp" --name-only 2>/dev/null; then
    while IFS= read -r -d '' scope && IFS= read -r -d '' key; do
      case "$scope" in system|global|unknown) printf '%s %s\n' "$scope" "$(bd_env_redact_key "$key")" ;; esac
    done < "$tmp"
  fi
  rm -f "$tmp"
}

# Сетевой Git-вызов маршрута: bd_env_network_git <root> <git args...>. Перенос действует
# только на эту команду; при сбое (кроме кода 2 ls-remote --exit-code) печатается подсказка
# с именами residual-ключей без значений. В subshell (command substitution, pipeline)
# собственный файл живёт не дольше вызова: состояние subshell не вернётся к родителю,
# а EXIT-ловушка элемента pipeline в bash 3.2 не срабатывает.
bd_env_network_git() {
  local root="$1" rc=0 residual owned=0
  shift
  if [ "${BASH_SUBSHELL:-0}" != 0 ] && [ -z "$BD_ENV_NETWORK_CONFIG" ]; then owned=1; fi
  bd_env_network_prepare "$root" || return 125
  GIT_CONFIG_GLOBAL="$BD_ENV_NETWORK_CONFIG" GIT_CONFIG_NOSYSTEM=1 git "$@" || rc=$?
  root="$BD_ENV_NETWORK_ROOT"
  if [ "$owned" = 1 ]; then bd_env_network_cleanup; fi
  if [ "$rc" != 0 ] && [ "$rc" != 2 ]; then
    residual="$(bd_env_network_residual "$root" | sed -E 's/^([^ ]+) (.*)$/\2 (\1)/' | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
    if [ -n "$residual" ]; then
      echo "HINT: user Git config keys not carried into the Beads network route: ${residual} — og-4py residual (ADR §3.39); diagnose: bash scripts/lib/bd-env.sh --diagnose ls-remote" >&2
    fi
  fi
  return "$rc"
}

# Диагностика для живых проверок: ключи и scope без значений + проба в окружении маршрута.
bd_env_network_diagnose() { # [ls-remote|push-dry-run]
  local probe="${1:-}" root raw scope record key rc=0 err result
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "ERROR: run inside the project checkout." >&2; return 1; }
  echo "OverGate Beads network Git diagnostic (shell; values hidden)"
  raw="$(umask 077 && mktemp "${TMPDIR:-/tmp}/overgate-git-diag.XXXXXX")" || return 1
  if ! bd_env_user_config_raw "$root" "$BD_ENV_USER_CONFIG_PATTERN" "$raw"; then rm -f "$raw"; return 1; fi
  local count=0
  while IFS= read -r -d '' scope && IFS= read -r -d '' record; do
    key="${record%%$'\n'*}"
    case "$scope" in system|global|unknown) ;; *) continue ;; esac
    [[ "$key" =~ $BD_ENV_USER_CONFIG_PATTERN ]] || continue
    echo "carried: ${scope} $(bd_env_redact_key "$key")"
    count=$((count+1))
  done < "$raw"
  rm -f "$raw"
  [ "$count" -gt 0 ] || echo "carried: <none>"
  bd_env_network_residual "$root" | sed 's/^/residual: /; s/$/ (not carried; og-4py residual, ADR §3.39)/'
  [ -n "$probe" ] || return 0
  err="$(umask 077 && mktemp "${TMPDIR:-/tmp}/overgate-git-probe.XXXXXX")" || return 1
  case "$probe" in
    ls-remote) bd_env_network_git "$root" ls-remote --heads origin >/dev/null 2>"$err" || rc=$? ;;
    push-dry-run) bd_env_network_git "$root" push --dry-run origin HEAD:refs/heads/og-auth-probe >/dev/null 2>"$err" || rc=$? ;;
    *) rm -f "$err"; echo "ERROR: probe must be ls-remote or push-dry-run." >&2; return 2 ;;
  esac
  if [ "$rc" = 0 ]; then result=ok
  elif grep -Eqi 'terminal prompts disabled|could not read (Username|Password)|Authentication failed|HTTP (401|403)|returned error: 40[13]' "$err"; then result=auth-unavailable
  else result=failed; fi
  rm -f "$err"
  echo "probe: ${probe} exit=${rc} result=${result}"
}

# Свежий снимок задач из origin/beads-backup явным refspec.
bd_env_fetch_backup() {
  bd_env_network_git "$(git rev-parse --show-toplevel)" fetch -q origin "$BD_BACKUP_REFSPEC"
}

# Детерминированный slug имени (для имени receipt-файла и т.п.): '/' и пробелы → '-',
# прочее не-[alnum._-] вырезается, длина ≤100. Имена git-веток не содержат пробелов/
# control-символов, поэтому коллизии практически исключены; при сомнении — явный путь.
bd_env_slugify() {
  printf '%s' "$1" | tr '/[:space:]' '--' | tr -cd '[:alnum:]._-' | cut -c1-100
}

# Прямой запуск только для диагностики og-4py (в production-окружении маршрута):
#   bash scripts/lib/bd-env.sh --diagnose [ls-remote|push-dry-run]
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    --diagnose)
      bd_env_sanitize_git
      bd_env_network_diagnose "${2:-}"
      exit $? ;;
    *) echo "usage: bash scripts/lib/bd-env.sh --diagnose [ls-remote|push-dry-run]" >&2; exit 2 ;;
  esac
fi
