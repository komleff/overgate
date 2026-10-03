#!/usr/bin/env bash
# Поведенческий контракт единого переносимого запуска Python 3.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

LAUNCHER="$ROOT/.claude/tools/run-python.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ -x "$LAUNCHER" ]; then
  pass "run-python.sh существует и исполним"
else
  fail "run-python.sh существует и исполним"
fi

REAL_PYTHON="$(command -v python3 || command -v python)"

make_runtime() {
  local path="$1"
  local name="$2"
  local marker="$3"
  local expects_py_flag="${4:-0}"
  mkdir -p "$path"
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' "printf '%s\\n' '$name' > '$marker'"
    if [ "$expects_py_flag" = "1" ]; then
      printf '%s\n' '[ "${1-}" = "-3" ] || exit 64' 'shift'
    fi
    printf 'exec %s "$@"\n' "'$REAL_PYTHON'"
  } >"$path/$name"
  chmod +x "$path/$name"
}

PY_FIRST_BIN="$TMP_DIR/py-first-bin"
PY_FIRST_MARKER="$TMP_DIR/py-first.marker"
make_runtime "$PY_FIRST_BIN" py "$PY_FIRST_MARKER" 1
make_runtime "$PY_FIRST_BIN" python3 "$TMP_DIR/python3-unexpected.marker"
PY_FIRST_OUT="$(PATH="$PY_FIRST_BIN" "$LAUNCHER" -c \
  'import sys; print(sys.argv[1])' 'argument with spaces')"
assert_eq "$PY_FIRST_OUT" "argument with spaces" \
  "launcher сохраняет аргументы вызываемого Python"
assert_eq "$(cat "$PY_FIRST_MARKER" 2>/dev/null)" "py" \
  "launcher предпочитает исправный py -3"
if [ -e "$TMP_DIR/python3-unexpected.marker" ]; then
  fail "launcher не продолжает поиск после исправного py -3"
else
  pass "launcher не продолжает поиск после исправного py -3"
fi

BROKEN_PY_BIN="$TMP_DIR/broken-py-bin"
BROKEN_PY_MARKER="$TMP_DIR/broken-py.marker"
PYTHON3_MARKER="$TMP_DIR/python3.marker"
mkdir -p "$BROKEN_PY_BIN"
printf '%s\n' '#!/bin/sh' 'exit 23' >"$BROKEN_PY_BIN/py"
chmod +x "$BROKEN_PY_BIN/py"
make_runtime "$BROKEN_PY_BIN" python3 "$PYTHON3_MARKER"
PATH="$BROKEN_PY_BIN" "$LAUNCHER" -c 'print("python3-ok")' \
  >"$TMP_DIR/python3.out" 2>"$TMP_DIR/python3.err"
BROKEN_PY_RC=$?
assert_eq "$BROKEN_PY_RC" "0" "сломанный py не блокирует следующий runtime"
assert_eq "$(cat "$TMP_DIR/python3.out")" "python3-ok" \
  "после сломанного py запускается python3"
assert_eq "$(cat "$PYTHON3_MARKER" 2>/dev/null)" "python3" \
  "python3 действительно выбран после неуспешной probe py"

STORE_ALIAS_BIN="$TMP_DIR/store-alias-bin"
PYTHON_MARKER="$TMP_DIR/python.marker"
mkdir -p "$STORE_ALIAS_BIN"
printf '%s\n' '#!/bin/sh' 'exit 9009' >"$STORE_ALIAS_BIN/python3"
chmod +x "$STORE_ALIAS_BIN/python3"
make_runtime "$STORE_ALIAS_BIN" python "$PYTHON_MARKER"
PATH="$STORE_ALIAS_BIN" "$LAUNCHER" -c 'print("python-ok")' \
  >"$TMP_DIR/python.out" 2>"$TMP_DIR/python.err"
STORE_ALIAS_RC=$?
assert_eq "$STORE_ALIAS_RC" "0" \
  "сломанный Windows Store alias не считается пригодным python3"
assert_eq "$(cat "$TMP_DIR/python.out")" "python-ok" \
  "launcher доходит до исправного python"
assert_eq "$(cat "$PYTHON_MARKER" 2>/dev/null)" "python" \
  "python действительно выбран после неуспешной probe python3"

NO_RUNTIME_BIN="$TMP_DIR/no-runtime-bin"
mkdir -p "$NO_RUNTIME_BIN"
PATH="$NO_RUNTIME_BIN" "$LAUNCHER" -c 'print("unreachable")' \
  >"$TMP_DIR/no-runtime.out" 2>"$TMP_DIR/no-runtime.err"
NO_RUNTIME_RC=$?
assert_eq "$NO_RUNTIME_RC" "127" "launcher fail-closed без исправного Python 3"
assert_contains "$(cat "$TMP_DIR/no-runtime.err")" "Python 3" \
  "launcher объясняет отсутствие исправного Python 3"

# Запрет по КЛАССУ, а не по одной записи: любой прямой запуск publisher'а
# интерпретатором (`python`, `python3`, `python3.11`, `py -3`, абсолютный путь к
# любому из них) непереносим. Прежняя форма ловила ровно строку
# `python3 .claude/tools/...` — соседние непереносимые записи проходили молча.
NONPORTABLE_PUBLISHER_CALL='(^|[^[:alnum:]_-])(py|python|python[0-9]+(\.[0-9]+)?)([[:space:]]+-[^[:space:]]+)*[[:space:]]+[^[:space:]]*publish-pr-comment\.py'

# Само правило проверяется на образцах: иначе испорченный шаблон «не находит
# ничего» и молча объявляет любой файл чистым.
PATTERN_PROBE_DIR="$TMP_DIR/publisher-callsite-probe"
mkdir -p "$PATTERN_PROBE_DIR"
{
  printf '%s\n' 'python3 .claude/tools/publish-pr-comment.py 645 -'
  printf '%s\n' 'python .claude/tools/publish-pr-comment.py 645 -'
  printf '%s\n' 'py -3 .claude/tools/publish-pr-comment.py 645 -'
  printf '%s\n' '/usr/bin/python3 .claude/tools/publish-pr-comment.py 645 -'
  printf '%s\n' 'python3.11 /repo/.claude/tools/publish-pr-comment.py 645 -'
} >"$PATTERN_PROBE_DIR/nonportable.txt"
{
  printf '%s\n' '.claude/tools/run-python.sh .claude/tools/publish-pr-comment.py 645 -'
  printf '%s\n' 'printf "%s" "$BODY" | "$PYTHON_LAUNCHER" "$PUBLISHER" 645 -'
  printf '%s\n' 'FINALIZE_PR_TOKEN=1 .claude/tools/run-python.sh .claude/tools/publish-pr-comment.py 645 -'
} >"$PATTERN_PROBE_DIR/portable.txt"
PROBE_HITS="$(grep -cE "$NONPORTABLE_PUBLISHER_CALL" "$PATTERN_PROBE_DIR/nonportable.txt" || true)"
assert_eq "$PROBE_HITS" "5" "правило ловит все непереносимые формы запуска publisher"
PROBE_FALSE="$(grep -cE "$NONPORTABLE_PUBLISHER_CALL" "$PATTERN_PROBE_DIR/portable.txt" || true)"
assert_eq "$PROBE_FALSE" "0" "правило не ложится на переносимый launcher"

PUBLISHER_CALLSITE_FILES="
$ROOT/AGENTS.md
$ROOT/.agents/PIPELINE_ADR.md
$ROOT/.agents/RV_ROLE.md
"
while IFS= read -r callsite_file; do
  [ -n "$callsite_file" ] || continue
  if grep -E "$NONPORTABLE_PUBLISHER_CALL" "$callsite_file" >/dev/null; then
    fail "publisher callsite использует переносимый Python launcher: ${callsite_file#$ROOT/}"
  else
    pass "publisher callsite использует переносимый Python launcher: ${callsite_file#$ROOT/}"
  fi
done <<EOF
$PUBLISHER_CALLSITE_FILES
EOF

COMMIT_HOOK="$ROOT/.claude/hooks/check-tests-before-commit.sh"
if grep -F 'run-python.sh' "$COMMIT_HOOK" >/dev/null && \
    ! grep -E 'for[[:space:]]+PY[[:space:]]+in[[:space:]]+python3' "$COMMIT_HOOK" >/dev/null; then
  pass "production commit-hook делегирует выбор runtime переносимому launcher"
else
  fail "production commit-hook делегирует выбор runtime переносимому launcher"
fi

finish
