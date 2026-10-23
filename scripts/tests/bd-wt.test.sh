#!/usr/bin/env bash
# Тесты scripts/bd-wt.sh и bd_env_resolve_main_db (scripts/lib/bd-env.sh) на заглушке bd:
# pass-through из основного checkout, --db из worktree по dolt_mode (embedded/server),
# fail-closed выбор базы, allowlist подкоманд, запрещённые флаги и BEADS_DIR/BEADS_DB,
# чтение metadata.json через launcher проекта. Живая база не трогается: только временные
# git-репозитории и заглушка bd, которая пишет argv в журнал.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"
WT_SH="$ROOT/scripts/bd-wt.sh"
ENV_LIB="$ROOT/scripts/lib/bd-env.sh"
LAUNCHER="$ROOT/.claude/tools/run-python.sh"
STUB="$ROOT/scripts/tests/lib/bd-stub.mjs"
chmod +x "$STUB" 2>/dev/null
export BD_BIN="$STUB"
# Окружение вызывающего (git hook, сессия агента) не должно менять выбор репозитория и базы.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY GIT_PREFIX
unset BEADS_DIR BEADS_DB BD_ENV_ASSUME_DOLT_ALIVE BD_STUB_STATE

T="$(mktemp -d)"
trap 'chmod -R u+rwX "$T" 2>/dev/null; rm -rf "$T"' EXIT
LOG="$T/calls.log"
TAB="$(printf '\t')"

git_q() { git -c user.name=t -c user.email=t@t.t -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }

# new_fixture <имя>: основной checkout и linked worktree, созданная из его подкаталога; в путях
# пробелы. Выставляет FX_MAIN, FX_WT и FX_ROOT — корень основного checkout в той форме, в
# которой его печатает git (её же берёт обёртка; на Windows это C:/…, на macOS — realpath).
new_fixture() {
  local base="$T/$1 base"
  FX_MAIN="$base/main checkout"
  FX_WT="$base/linked wt"
  mkdir -p "$FX_MAIN/sub"
  git_q init -q "$FX_MAIN"
  : > "$FX_MAIN/sub/.keep"
  git_q -C "$FX_MAIN" add .
  git_q -C "$FX_MAIN" commit -q -m init
  git_q -C "$FX_MAIN/sub" worktree add -q -b "wt-$1" "$FX_WT"
  mkdir -p "$FX_MAIN/.beads"
  FX_ROOT="$(git -C "$FX_WT" worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
}

set_meta() { printf '%s\n' "$2" > "$1/.beads/metadata.json"; }
set_mode() { set_meta "$1" "{\"database\":\"dolt\",\"dolt_mode\":\"$2\",\"backend\":\"dolt\"}"; }

# argv <аргументы>: ожидаемая строка журнала заглушки (аргументы через табуляцию).
argv() { local IFS="$TAB"; printf '%s' "$*"; }

# wrap <cwd> <direct|bash> [VAR=значение ...] -- <аргументы>: запуск обёртки в двух формах
# вызова (`scripts/bd-wt.sh` и `bash scripts/bd-wt.sh`). Выставляет RC, ERR, CALLS.
WRAP_SH="$WT_SH"
wrap() {
  local cwd="$1" form="$2"
  shift 2
  local envs=("BD_STUB_LOG=$LOG")
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done
  shift
  : > "$LOG"
  if [ "$form" = "bash" ]; then
    ERR="$(cd "$cwd" && env "${envs[@]}" bash "$WRAP_SH" "$@" 2>&1 >/dev/null </dev/null)"; RC=$?
  else
    ERR="$(cd "$cwd" && env "${envs[@]}" "$WRAP_SH" "$@" 2>&1 >/dev/null </dev/null)"; RC=$?
  fi
  CALLS="$(cat "$LOG")"
}

# resolve <библиотека> <корень> [VAR=значение ...]: прямой вызов bd_env_resolve_main_db.
# Выставляет RESOLVED="код|режим|путь" и RESOLVE_ERR.
resolve() {
  local lib="$1" root="$2"
  shift 2
  RESOLVED="$(cd "$T" && env "$@" bash -c '. "$1"; rc=0; bd_env_resolve_main_db "$2" || rc=$?; printf "%s|%s|%s" "$rc" "${BD_ENV_DB_MODE:-}" "${BD_ENV_DB_PATH:-}"' resolve "$lib" "$root" 2>"$T/resolve.err")"
  RESOLVE_ERR="$(cat "$T/resolve.err")"
}

new_fixture embedded
E_MAIN="$FX_MAIN"; E_WT="$FX_WT"; E_ROOT="$FX_ROOT"
set_mode "$E_MAIN" embedded
mkdir -p "$E_MAIN/.beads/embeddeddolt"

new_fixture server
S_MAIN="$FX_MAIN"; S_WT="$FX_WT"; S_ROOT="$FX_ROOT"
set_mode "$S_MAIN" server
mkdir -p "$S_MAIN/.beads/dolt"
echo 99999999 > "$S_MAIN/.beads/dolt-server.pid"   # заведомо мёртвый pid
echo 50999 > "$S_MAIN/.beads/dolt-server.port"

# --- прежние кейсы rc.1 (смысл сохранён; worktree-фикстура — dolt_mode server) ---
wrap "$S_MAIN" direct -- export
assert_eq "$RC" "2" "refuse: export → exit 2"
assert_contains "$ERR" "bash scripts/bd-sync-export.sh" "refuse: export подсказывает запуск через bash"
wrap "$S_MAIN" direct -- --db /tmp/x dolt push
assert_eq "$RC" "2" "refuse: dolt после глобального флага --db X → exit 2"
wrap "$S_MAIN" direct -- import foo
assert_eq "$RC" "2" "refuse: import → exit 2"

wrap "$S_MAIN" direct -- ready
assert_contains "$CALLS" "ready" "main: команда ready проброшена"
assert_not_contains "$CALLS" "--db" "main: --db НЕ подставлен"

wrap "$T" direct -- ready
assert_eq "$RC" "1" "не git-репо → exit 1"

wrap "$S_WT" direct BD_ENV_ASSUME_DOLT_ALIVE=1 -- ready
assert_eq "$RC" "0" "worktree+живой сервер: exit 0"
assert_contains "$CALLS" "--db" "worktree: --db подставлен"
assert_eq "$CALLS" "$(argv --db "$S_ROOT/.beads/dolt" ready)" "worktree: --db указывает на базу основного checkout"

wrap "$S_WT" direct -- ready
assert_eq "$RC" "3" "worktree+мёртвый сервер: exit 3"
assert_eq "$CALLS" "" "worktree+мёртвый сервер: bd не вызван"
assert_contains "$ERR" "dolt-сервер основного checkout не запущен" "worktree+мёртвый сервер: причина в stderr"

wrap "$S_MAIN" direct -- --db /tmp/x show proj-1
assert_eq "$RC" "2" "refuse: пользовательский --db value → exit 2"
wrap "$S_MAIN" direct -- --db=/tmp/x show proj-1
assert_eq "$RC" "2" "refuse: --db=… → exit 2"

# --- rc.2: изменённое поведение — --global больше не разрешённый глобальный флаг ---
for form in direct bash; do
  wrap "$E_MAIN" "$form" -- --global list
  assert_eq "$RC" "2" "rc.2 changed ($form): --global до подкоманды → exit 2"
  assert_eq "$CALLS" "" "rc.2 changed ($form): --global — bd не вызван"
done

# --- embedded / server: выбор базы в worktree ---
before="$(ls -A "$E_MAIN/.beads" | sort)"
wrap "$E_WT" direct -- create --title "Заголовок с пробелами" --priority 2
assert_eq "$RC" "0" "worktree embedded: exit 0 без pid/port"
assert_eq "$CALLS" "$(argv --db "$E_ROOT/.beads/embeddeddolt" create --title "Заголовок с пробелами" --priority 2)" \
  "worktree embedded: --db embeddeddolt, аргументы без изменений"
assert_eq "$(ls -A "$E_MAIN/.beads" | sort)" "$before" "worktree embedded: .beads основного checkout не изменён"
if [ -e "$E_WT/.beads" ]; then fail "worktree embedded: в worktree появился .beads"; else pass "worktree embedded: в worktree .beads не создан"; fi

wrap "$E_WT/sub" bash -- show proj-1
assert_eq "$CALLS" "$(argv --db "$E_ROOT/.beads/embeddeddolt" show proj-1)" "worktree embedded: запуск из подкаталога worktree"

wrap "$S_WT" bash BD_ENV_ASSUME_DOLT_ALIVE=1 -- ready --json
assert_eq "$CALLS" "$(argv --db "$S_ROOT/.beads/dolt" ready --json)" "worktree server: --db dolt при живом сервере"

wrap "$E_MAIN" direct -- comment proj-1 "текст с пробелами"
assert_eq "$CALLS" "$(argv comment proj-1 "текст с пробелами")" "main embedded: точный argv без --db"

# --- resolver: прямой вызов bd_env_resolve_main_db ---
new_fixture resolver
F_MAIN="$FX_MAIN"; F_WT="$FX_WT"; F_ROOT="$FX_ROOT"
reset_beads() { chmod -R u+rwX "$F_MAIN/.beads" 2>/dev/null; rm -rf "$F_MAIN/.beads"; mkdir -p "$F_MAIN/.beads"; }

reset_beads
mkdir -p "$F_MAIN/.beads/dolt" "$F_MAIN/.beads/embeddeddolt"
set_meta "$F_MAIN" '{
  "backend" : "dolt",

  "extra": {"dolt_mode": "server"},
  "dolt_mode"   :   "embedded"
}'
resolve "$ENV_LIB" "$F_ROOT"
assert_eq "$RESOLVED" "0|embedded|$F_ROOT/.beads/embeddeddolt" "resolver: решает dolt_mode, порядок ключей и пробелы не важны"
set_meta "$F_MAIN" '{"dolt_mode":"server","database":"dolt"}'
resolve "$ENV_LIB" "$F_ROOT"
assert_eq "$RESOLVED" "3|server|$F_ROOT/.beads/dolt" "resolver: server без живого сервера → код 3, режим и путь определены"
resolve "$ENV_LIB" "$F_ROOT" BD_ENV_ASSUME_DOLT_ALIVE=1
assert_eq "$RESOLVED" "0|server|$F_ROOT/.beads/dolt" "resolver: server с живым сервером → 0"
wrap "$F_WT" direct BD_ENV_ASSUME_DOLT_ALIVE=1 -- list
assert_eq "$CALLS" "$(argv --db "$F_ROOT/.beads/dolt" list)" "worktree: при обоих каталогах базу выбирает dolt_mode"
resolve "$ENV_LIB" ""
assert_eq "$RESOLVED" "1||" "resolver: пустой корень → fail-closed"

# check_fail_closed <имя> <часть пути в stderr> <нужна ли подсказка оператора: 1|0>
check_fail_closed() {
  local name="$1" part="$2" operator="$3"
  wrap "$F_WT" direct BD_ENV_ASSUME_DOLT_ALIVE=1 -- ready
  assert_eq "$RC" "1" "fail-closed $name: exit 1"
  assert_eq "$CALLS" "" "fail-closed $name: bd не вызван"
  assert_contains "$ERR" "$F_ROOT/.beads" "fail-closed $name: stderr называет .beads основного checkout"
  assert_contains "$ERR" "$part" "fail-closed $name: stderr называет $part"
  if [ "$operator" = "1" ]; then
    assert_contains "$ERR" "обратитесь к оператору" "fail-closed $name: шаг восстановления — оператор, без ручной правки"
  fi
  resolve "$ENV_LIB" "$F_ROOT" BD_ENV_ASSUME_DOLT_ALIVE=1
  assert_eq "$RESOLVED" "1||" "fail-closed $name: resolver → 1 без режима и пути"
}

reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"
check_fail_closed "нет metadata.json" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_meta "$F_MAIN" '{"dolt_mode": "embedded"'
check_fail_closed "невалидный JSON" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_meta "$F_MAIN" '["embedded"]'
check_fail_closed "JSON не объект" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_meta "$F_MAIN" '{"database":"dolt"}'
check_fail_closed "нет dolt_mode" "metadata.json" 1
assert_contains "$ERR" "dolt_mode" "fail-closed нет dolt_mode: причина названа"
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_mode "$F_MAIN" ""
check_fail_closed "пустой dolt_mode" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_meta "$F_MAIN" '{"dolt_mode": 1}'
check_fail_closed "dolt_mode не строка" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt" "$F_MAIN/.beads/dolt"; set_mode "$F_MAIN" sqlite
check_fail_closed "неизвестный dolt_mode" "metadata.json" 1
reset_beads; mkdir -p "$F_MAIN/.beads/dolt"; set_mode "$F_MAIN" embedded
check_fail_closed "embedded без каталога базы" ".beads/embeddeddolt" 0
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_mode "$F_MAIN" server
check_fail_closed "server без каталога базы" ".beads/dolt" 0
reset_beads; mkdir -p "$F_MAIN/.beads/embeddeddolt"; set_mode "$F_MAIN" embedded
chmod 000 "$F_MAIN/.beads/metadata.json"
if [ -r "$F_MAIN/.beads/metadata.json" ]; then
  # root или файловая система без POSIX-прав (Windows): нечитаемый файл не воспроизводится.
  echo "  SKIP: нечитаемый metadata.json не воспроизводится в этом окружении"
else
  check_fail_closed "нечитаемый metadata.json" "metadata.json" 1
fi
chmod 644 "$F_MAIN/.beads/metadata.json"

# --- launcher проекта: resolver читает metadata.json только через .claude/tools/run-python.sh ---
FAKE="$T/fake project"
mkdir -p "$FAKE/scripts/lib" "$FAKE/.claude/tools"
cp "$WT_SH" "$FAKE/scripts/bd-wt.sh"
cp "$ENV_LIB" "$FAKE/scripts/lib/bd-env.sh"
LAUNCH_LOG="$T/launcher.log"
printf '#!/bin/sh\nprintf "called\\n" >> "%s"\nexec "%s" "$@"\n' "$LAUNCH_LOG" "$LAUNCHER" > "$FAKE/.claude/tools/run-python.sh"
chmod +x "$FAKE/.claude/tools/run-python.sh" "$FAKE/scripts/bd-wt.sh"
: > "$LAUNCH_LOG"
WRAP_SH="$FAKE/scripts/bd-wt.sh"
wrap "$E_WT" bash -- ready
assert_eq "$RC" "0" "launcher: обёртка проекта проходит через его launcher"
assert_eq "$CALLS" "$(argv --db "$E_ROOT/.beads/embeddeddolt" ready)" "launcher: база выбрана по ответу launcher"
assert_contains "$(cat "$LAUNCH_LOG")" "called" "launcher: resolver вызвал .claude/tools/run-python.sh проекта"

printf '#!/bin/sh\necho "ОШИБКА: не найден исправный Python 3" >&2\nexit 127\n' > "$FAKE/.claude/tools/run-python.sh"
wrap "$E_WT" bash -- ready
assert_eq "$RC" "1" "launcher без Python: exit 1"
assert_eq "$CALLS" "" "launcher без Python: bd не вызван"
assert_contains "$ERR" "нужен Python" "launcher без Python: адресное сообщение «нужен Python»"
assert_not_contains "$ERR" "JSON" "launcher без Python: нет ложного диагноза про JSON"

rm -f "$FAKE/.claude/tools/run-python.sh"
wrap "$E_WT" bash -- ready
assert_eq "$RC" "1" "launcher отсутствует: exit 1"
assert_eq "$CALLS" "" "launcher отсутствует: bd не вызван"
assert_contains "$ERR" "нужен Python" "launcher отсутствует: адресное сообщение «нужен Python»"
assert_contains "$ERR" "run-python.sh" "launcher отсутствует: stderr называет launcher"
WRAP_SH="$WT_SH"

# --- allowlist, запрещённые флаги и BEADS_* в четырёх контекстах ---
CTX_NAME=("main embedded" "main server" "worktree embedded" "worktree server")
CTX_CWD=("$E_MAIN" "$S_MAIN" "$E_WT" "$S_WT")
CTX_ENV=("" "" "" "BD_ENV_ASSUME_DOLT_ALIVE=1")
CTX_DB=("" "" "$E_ROOT/.beads/embeddeddolt" "$S_ROOT/.beads/dolt")
CTX_FORM=(direct bash bash direct)

ALLOWED="ready show list search blocked children create q update close reopen dep comment comments note label"
FORBIDDEN_SUBCOMMANDS="delete config init sql batch prune purge flatten gc compact admin rename-prefix migrate bootstrap export import dolt"
# Случаи отказа: аргументы через «|»; пустая строка — вызов без аргументов.
FORBIDDEN_ARGS=(
  ""
  "--json"
  "--unknown|list"
  "--frobnicate|list"
  "--ignore-schema-skew|list"
  "list|--ignore-schema-skew"
  "--db|/other|list"
  "--db=/other|list"
  "list|--db|/other"
  "list|--db=/other"
  "-C|/other|list"
  "list|-C|/other"
  "list|-C/other"
  "list|-qC|/other"
  "--directory|/other|list"
  "list|--directory|/other"
  "list|--directory=/other"
  "--global|list"
  "list|--global"
  "list|--global=true"
  "--|export"
  "create|--title|-C"
  "comment|proj-1|--global"
  "note|proj-1|--db"
  "create|--repo|/other|x"
  "create|--repo=/other|x"
  "create|x|--repo|/other"
  "create|x|--body-file|/etc/hosts"
  "create|x|--body-file=/etc/hosts"
  "update|proj-1|--design-file|/etc/hosts"
  "update|proj-1|--design-file=/etc/hosts"
  "close|proj-1|--reason-file|/etc/hosts"
  "close|proj-1|--reason-file=/etc/hosts"
  "create|--file|/etc/hosts"
  "create|--file=/etc/hosts"
  "create|--graph|/etc/hosts"
  "create|--graph=/etc/hosts"
  "create|-f|/etc/hosts"
  "create|-f/etc/hosts"
  "create|-qf|/etc/hosts"
  "--json|comment|proj-1|-f|/etc/hosts"
  "create|x|--metadata|@/etc/hosts"
  "create|x|--metadata=@/etc/hosts"
  "update|proj-1|--metadata|@x"
)
for sub in $FORBIDDEN_SUBCOMMANDS; do
  FORBIDDEN_ARGS+=("$sub" "--json|$sub|x")
done
PASSING_ARGS=(
  "create|x|--metadata|{\"k\":\"v\"}"
  "create|x|--metadata={\"k\":\"v\"}"
  "create|x|--stdin"
  "create|x|--description|длинный текст"
  "--json|comment|proj-1|--stdin"
  "--|show|proj-1"
)

i=0
while [ "$i" -lt 4 ]; do
  name="${CTX_NAME[$i]}"; cwd="${CTX_CWD[$i]}"; extra="${CTX_ENV[$i]}"; db="${CTX_DB[$i]}"; form="${CTX_FORM[$i]}"
  envs=(); [ -n "$extra" ] && envs=("$extra")
  prefix=(); [ -n "$db" ] && prefix=(--db "$db")

  bad=0
  for sub in $ALLOWED; do
    wrap "$cwd" "$form" ${envs[@]+"${envs[@]}"} -- --json "$sub" arg
    if [ "$RC" != "0" ] || [ "$CALLS" != "$(argv ${prefix[@]+"${prefix[@]}"} --json "$sub" arg)" ]; then
      bad=1; fail "$name: allowlist $sub — rc=$RC calls=[$CALLS] err=[$ERR]"
    fi
  done
  [ "$bad" = "0" ] && pass "$name: все подкоманды allowlist проходят с точным argv"

  bad=0
  for case_args in "${FORBIDDEN_ARGS[@]}"; do
    args=()
    if [ -n "$case_args" ]; then
      IFS='|' read -r -a args <<EOF
$case_args
EOF
    fi
    for f in direct bash; do
      wrap "$cwd" "$f" ${envs[@]+"${envs[@]}"} -- ${args[@]+"${args[@]}"}
      if [ "$RC" != "2" ] || [ -n "$CALLS" ]; then
        bad=1; fail "$name ($f): [$case_args] — ожидался отказ 2 без bd, rc=$RC calls=[$CALLS]"
      fi
    done
  done
  [ "$bad" = "0" ] && pass "$name: запрещённые подкоманды/флаги/пустая подкоманда → 2 до bd (обе формы вызова)"

  for sub in export import dolt; do
    wrap "$cwd" "$form" ${envs[@]+"${envs[@]}"} -- "$sub"
    assert_contains "$ERR" "bash scripts/bd-sync-export.sh" "$name: $sub — подсказка синхронизации через bash"
  done
  wrap "$cwd" "$form" ${envs[@]+"${envs[@]}"} -- delete proj-1
  assert_contains "$ERR" "allowlist" "$name: delete — отказ называет allowlist"

  bad=0
  for case_args in "${PASSING_ARGS[@]}"; do
    IFS='|' read -r -a args <<EOF
$case_args
EOF
    wrap "$cwd" "$form" ${envs[@]+"${envs[@]}"} -- "${args[@]}"
    if [ "$RC" != "0" ] || [ "$CALLS" != "$(argv ${prefix[@]+"${prefix[@]}"} "${args[@]}")" ]; then
      bad=1; fail "$name: [$case_args] должен пройти — rc=$RC calls=[$CALLS] err=[$ERR]"
    fi
  done
  [ "$bad" = "0" ] && pass "$name: --stdin/--description/--metadata JSON/-- проходят с точным argv"

  for var in BEADS_DIR BEADS_DB; do
    for f in direct bash; do
      wrap "$cwd" "$f" ${envs[@]+"${envs[@]}"} "$var=$T/other/.beads" -- ready
      assert_eq "$RC" "2" "$name ($f): непустой $var → 2"
      assert_eq "$CALLS" "" "$name ($f): непустой $var — bd не вызван"
      assert_contains "$ERR" "$var" "$name ($f): отказ называет $var"
    done
  done
  wrap "$cwd" "$form" ${envs[@]+"${envs[@]}"} BEADS_DIR= BEADS_DB= -- ready
  assert_eq "$CALLS" "$(argv ${prefix[@]+"${prefix[@]}"} ready)" "$name: пустые BEADS_DIR/BEADS_DB не мешают"
  i=$((i + 1))
done

finish
