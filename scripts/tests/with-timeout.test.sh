#!/usr/bin/env bash
# Поведенческий контракт переносимой обёртки ограничения времени и её потребителей.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

HELPER="$ROOT/.claude/tools/with-timeout.sh"
PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Единый АВАРИЙНЫЙ сторож ожидания событий (запуск процесса, запись pid-файла
# и окончательное исчезновение записи процесса), секунды.
#
# Прежняя редакция задавала границу списком итераций в каждом цикле и давала
# суммарно 1 секунду. Внутри ожидается старт интерпретатора Python и запись
# pid-файла: на машине под нагрузкой один только старт съедает эту границу, и
# тест краснел на НЕИЗМЕНИВШЕМСЯ коде — наблюдено при loadavg 10–13 (FAIL
# «native cancellation-тест дождался потомка до deadline»), зелено при loadavg 4.
# Нормальной средой набора его собственный гейт называет loadavg 6–24, то есть
# граница была рассчитана на незагруженную машину.
#
# Сторож щедрый: на зелёном пути ожидание завершается по событию. Из его
# величины НЕ выводится своевременность или правильность. Обязательный порядок
# cleanup проверяется отдельно по исходнику и мутациями этого оракула; сторож
# лишь не даёт зависнуть безопасному подтверждению исчезновения процессов.
EVENT_GUARD_SECONDS=120
export EVENT_GUARD_SECONDS

# Пин аварийного предела защищает только от возврата к ложной красноте под
# нагрузкой. Семантический оракул правильности от этой величины не зависит.
if [ "$EVENT_GUARD_SECONDS" -ge 60 ]; then
  pass "аварийный сторож события щедрый (${EVENT_GUARD_SECONDS} с)"
else
  fail "аварийный сторож события ${EVENT_GUARD_SECONDS} с снова рассчитан на незагруженную машину"
fi

# Структурный пин: аварийные сторожа считаются от единой переменной, а не
# задаются списком итераций по месту.
if grep -qE '^[[:space:]]*for _ in 1 2 3' "$0"; then
  fail "аварийный сторож снова задан списком итераций — нужен EVENT_GUARD_SECONDS"
else
  pass "аварийные сторожа считаются от единой переменной EVENT_GUARD_SECONDS"
fi

run_and_capture() {
  local output_file="$1"
  shift
  "$@" >"$output_file" 2>&1
  return $?
}

if [ -x "$HELPER" ]; then
  pass "with-timeout.sh существует и исполним"
else
  fail "with-timeout.sh существует и исполним"
fi

# Детерминированные файловые события принадлежат только тестовому harness.
# Production-helper не должен распознавать ни ready/release, ни маркеры стадий
# cleanup: специальный путь или FIFO из окружения способен задержать боевой
# hard-timeout даже без явного цикла ожидания.
if grep -qE 'U2_WITH_TIMEOUT_TEST_[A-Z0-9_]*_FILE' "$HELPER"; then
  fail "production with-timeout.sh не содержит файловые тестовые протоколы"
else
  pass "production with-timeout.sh не содержит файловые тестовые протоколы"
fi

STARTUP_SIGNAL_ORDER="$("$PYTHON_RUNNER" - "$HELPER" <<'PY_STARTUP_ORDER'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")

def appears_before(left: str, right: str) -> bool:
    return left in source and right in source and source.index(left) < source.index(right)

native = appears_before(
    "trap 'cancel_native_timeout TERM 143' TERM",
    '"$native_timeout" -s TERM -k 1 "$seconds"',
)
fallback = appears_before(
    "signal.signal(handled_signal",
    "process = subprocess.Popen(command, **popen_options)",
)
print(f"{native} {fallback}")
PY_STARTUP_ORDER
)"
assert_eq "$STARTUP_SIGNAL_ORDER" "True True" \
  "обработчики внешней отмены устанавливаются до запуска изолированного потомка"

# Наблюдение исчезновения PID нельзя использовать как единственное доказательство
# протокола cleanup: после killpg(SIGKILL) запись внука может исчезнуть чуть позже,
# а при ошибочной реализации конечный потомок способен умереть сам. Поэтому
# обязательный порядок TERM/KILL/wait пинится отдельно по реальному исходнику.
# Узкие мутационные прогоны этого оракула отдельно проверяют удаление каждого
# критического шага.
CLEANUP_PROTOCOL_CHECK="$("$PYTHON_RUNNER" - "$HELPER" <<'PY_CLEANUP_PROTOCOL'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")


def block(text, start, end):
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def ordered(text, *steps):
    cursor = 0
    for step in steps:
        position = text.find(step, cursor)
        if position < 0:
            return False
        cursor = position + len(step)
    return True


native_cancel = block(
    source,
    "  cancel_native_timeout() {",
    "\n  trap 'cancel_native_timeout TERM 143' TERM",
)
native_deadline = block(
    source,
    '  "$native_timeout" -s TERM -k 1 "$seconds"',
    '\n  if [ "$native_rc" -eq 137 ]; then',
)
fallback = block(
    source,
    "def terminate_tree(initial_signal):",
    "\n\ncleanup_required = True",
)
fallback_windows = block(
    fallback,
    '    if os.name == "nt":',
    "\n        return",
)
fallback_posix = fallback[fallback.index("    try:\n        os.killpg"):]
checks = (
    ordered(
        native_cancel,
        'kill -"$cancel_signal" "-$native_pid"',
        "/bin/sleep 1",
        'kill -KILL "-$native_pid"',
        'kill -KILL "$native_pid"',
        'wait "$native_pid"',
        'exit "$cancel_rc"',
    ),
    ordered(
        native_deadline,
        'native_pid=$!',
        'wait "$native_pid"',
        'native_rc=$?',
        'if [ "$native_rc" -eq 124 ]; then',
        "/bin/sleep 1",
        'kill -KILL "-$native_pid"',
        "return 124",
    ),
    ordered(
        fallback_posix,
        "os.killpg(process.pid, initial_signal)",
        "process.wait(timeout=1)",
        "os.killpg(process.pid, signal.SIGKILL)",
        "process.wait(timeout=1)",
        "except subprocess.TimeoutExpired:",
        "process.kill()",
        "process.wait()",
    ),
    ordered(
        fallback_windows,
        '["taskkill", "/PID", str(process.pid), "/T", "/F"]',
        "except OSError:",
        "process.kill()",
        "process.wait(timeout=1)",
        "except subprocess.TimeoutExpired:",
        "process.kill()",
        "process.wait()",
    ),
)
print(" ".join(str(result) for result in checks))
PY_CLEANUP_PROTOCOL
)"
assert_eq "$CLEANUP_PROTOCOL_CHECK" "True True True True" \
  "cleanup-протокол включает SIGKILL и обязательный wait во всех применимых ветвях"

NO_ARGS_OUTPUT="$TMP_DIR/no-args.out"
run_and_capture "$NO_ARGS_OUTPUT" "$HELPER"
NO_ARGS_RC=$?
assert_eq "$NO_ARGS_RC" "2" "вызов без аргументов отклоняется как ошибка интерфейса"
assert_contains "$(cat "$NO_ARGS_OUTPUT")" "Использование:" \
  "вызов без аргументов печатает способ использования"

NO_COMMAND_OUTPUT="$TMP_DIR/no-command.out"
run_and_capture "$NO_COMMAND_OUTPUT" "$HELPER" 1
NO_COMMAND_RC=$?
assert_eq "$NO_COMMAND_RC" "2" "вызов без команды отклоняется как ошибка интерфейса"

for invalid_seconds in 0 -1 1.5; do
  INVALID_SECONDS_OUTPUT="$TMP_DIR/invalid-seconds-${invalid_seconds//[^a-zA-Z0-9]/_}.out"
  run_and_capture "$INVALID_SECONDS_OUTPUT" "$HELPER" "$invalid_seconds" /bin/true
  INVALID_SECONDS_RC=$?
  assert_eq "$INVALID_SECONDS_RC" "2" \
    "невалидное значение секунд '$invalid_seconds' отклоняется"
done

ERROR_OUTPUT="$TMP_DIR/error.out"
run_and_capture "$ERROR_OUTPUT" "$HELPER" 2 /bin/sh -c 'exit 23'
ERROR_RC=$?
assert_eq "$ERROR_RC" "23" "обычная ошибка сохраняет исходный код"
assert_ne "$ERROR_RC" "124" "обычная ошибка отличается от истечения времени"

# Оставляем в PATH только Python: так тест обязательно проходит через переносимый fallback,
# даже если на машине разработчика установлены timeout или gtimeout.
FALLBACK_BIN="$TMP_DIR/fallback-bin"
mkdir -p "$FALLBACK_BIN"
PYTHON_BIN="$(command -v python3)"
ln -s "$PYTHON_BIN" "$FALLBACK_BIN/python3"

if PATH="$FALLBACK_BIN" command -v timeout >/dev/null 2>&1 || \
    PATH="$FALLBACK_BIN" command -v gtimeout >/dev/null 2>&1; then
  fail "fallback-тест скрывает timeout и gtimeout"
else
  pass "fallback-тест скрывает timeout и gtimeout"
fi

ARGS_OUTPUT="$TMP_DIR/args.out"
PATH="$FALLBACK_BIN" run_and_capture "$ARGS_OUTPUT" "$HELPER" 2 /bin/sh -c \
  'printf "<%s>\n" "$1" "$2" "$3"' _ "argument with spaces" "" "--flag"
ARGS_RC=$?
assert_eq "$ARGS_RC" "0" "fallback успешно передаёт аргументы команды"
assert_eq "$(cat "$ARGS_OUTPUT")" $'<argument with spaces>\n<>\n<--flag>' \
  "fallback сохраняет пробелы, пустой аргумент и ведущий дефис"

SIGNAL_OUTPUT="$TMP_DIR/signal.out"
PATH="$FALLBACK_BIN" run_and_capture "$SIGNAL_OUTPUT" "$HELPER" 2 /bin/sh -c \
  'kill -TERM "$$"'
SIGNAL_RC=$?
assert_eq "$SIGNAL_RC" "143" "fallback переводит SIGTERM команды в shell-код 143"

FALLBACK_RESERVED_OUTPUT="$TMP_DIR/fallback-reserved.out"
PATH="$FALLBACK_BIN" run_and_capture "$FALLBACK_RESERVED_OUTPUT" "$HELPER" 2 \
  /bin/sh -c 'exit 124'
FALLBACK_RESERVED_RC=$?
assert_eq "$FALLBACK_RESERVED_RC" "125" \
  "fallback оставляет код 124 только для реального истечения времени"

MISSING_COMMAND_OUTPUT="$TMP_DIR/missing-command.out"
PATH="$FALLBACK_BIN" run_and_capture "$MISSING_COMMAND_OUTPUT" "$HELPER" 2 \
  command-that-does-not-exist-u2-timeout-test
MISSING_COMMAND_RC=$?
assert_eq "$MISSING_COMMAND_RC" "127" "fallback возвращает shell-код отсутствующей команды"
assert_contains "$(cat "$MISSING_COMMAND_OUTPUT")" "команда не найдена" \
  "fallback явно диагностирует отсутствующую команду"

NO_RUNTIME_BIN="$TMP_DIR/no-runtime-bin"
mkdir -p "$NO_RUNTIME_BIN"
NO_RUNTIME_OUTPUT="$TMP_DIR/no-runtime.out"
PATH="$NO_RUNTIME_BIN" run_and_capture "$NO_RUNTIME_OUTPUT" "$HELPER" 1 /bin/true
NO_RUNTIME_RC=$?
assert_eq "$NO_RUNTIME_RC" "127" \
  "fallback fail-closed без timeout, gtimeout и исправного Python 3"
assert_contains "$(cat "$NO_RUNTIME_OUTPUT")" "запуск без ограничения времени запрещён" \
  "fallback объясняет отказ при отсутствии исправного Python 3"

PROCESS_SCRIPT="$TMP_DIR/process-tree.sh"
cat >"$PROCESS_SCRIPT" <<'PROCESS_SCRIPT_BODY'
#!/bin/sh
echo "$$" >"$1"
# Потомок игнорирует сигналы отмены и живёт дольше аварийного сторожа: helper
# обязан после grace-периода добить всю группу. Ожидание его исчезновения не
# может ложно позеленеть из-за самостоятельного завершения потомка.
/bin/sh -c 'trap "" TERM INT HUP; exec /bin/sleep 86400' &
echo "$!" >"$2"
wait
PROCESS_SCRIPT_BODY
chmod +x "$PROCESS_SCRIPT"

# Гонка-фри смок production-пути: код 124 не зависит от скорости старта команды
# (Popen уже вернулся, wait(timeout) истекает и добивает группу), поэтому здесь
# нет PID-файлов и барьер готовности не нужен. Поведенческие утверждения об
# исчезновении дерева процессов — ниже, в deadline-сценарии под барьером
# готовности (после сборки SIGNAL_HARNESS): прежняя форма запускала этот же
# сценарий здесь с бюджетом 1 с БЕЗ барьера, и под параллельной фазой набора
# (J=9) exec /bin/sh съедал бюджет до записи root.pid/child.pid — «PID пуст»
# краснел на неизменившемся коде.
TIMEOUT_OUTPUT="$TMP_DIR/timeout.out"
PATH="$FALLBACK_BIN" run_and_capture "$TIMEOUT_OUTPUT" "$HELPER" 1 /bin/sleep 30
TIMEOUT_RC=$?
assert_eq "$TIMEOUT_RC" "124" "истечение времени возвращает отдельный код 124"

process_is_live() {
  local pid="$1"
  local state
  if ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  state="$(/bin/ps -o stat= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ -n "$state" ] && [ "${state#Z}" = "$state" ]
}

# Коды возврата РАЗВЕДЕНЫ по причине отказа, и это не косметика: причины лечатся
# по-разному. Код 2 — владелец умер, не создав pid-файла: расширение границы
# ожидания тут бесполезно, чинить надо запускаемый сценарий. Код 1 — граница
# исчерпана при живом владельце. Прежде обе причины возвращали 1, и сообщение об
# отказе всегда говорило про предел, уводя диагностику в заведомо ложную сторону.
wait_for_pid_file() {
  local pid_file="$1"
  local owner_pid="$2"
  local left=$((EVENT_GUARD_SECONDS * 20))   # аварийный шаг 0,05 с
  while [ "$left" -gt 0 ]; do
    if [ -s "$pid_file" ]; then
      return 0
    fi
    if ! kill -0 "$owner_pid" 2>/dev/null; then
      return 2
    fi
    /bin/sleep 0.05
    left=$((left - 1))
  done
  return 1
}

# Единая формулировка отказа ожидания pid-файла: причина называется та, что
# случилась на самом деле.
pid_file_wait_reason() {
  case "$1" in
    2) printf '%s' "владелец завершился, не создав pid-файла (границей ожидания не лечится)" ;;
    *) printf '%s' "исчерпан аварийный сторож ${EVENT_GUARD_SECONDS} с при живом владельце" ;;
  esac
}

wait_until_process_gone() {
  local pid="$1"
  local left=$((EVENT_GUARD_SECONDS * 20))   # аварийный шаг 0,05 с
  while [ "$left" -gt 0 ]; do
    if ! process_is_live "$pid"; then
      return 0
    fi
    /bin/sleep 0.05
    left=$((left - 1))
  done
  return 1
}

assert_process_gone() {
  local pid="$1"
  local label="$2"
  if [ -z "$pid" ]; then
    fail "$label — PID пуст, исчезновение не доказано"
    return
  fi
  if wait_until_process_gone "$pid"; then
    pass "$label"
  else
    fail "$label — процесс не исчез до аварийного сторожа"
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

assert_external_signal_cleanup() {
  local route="$1"
  local route_path="$2"
  local signal_name="$3"
  local expected_rc="$4"
  local root_pid_file="$TMP_DIR/$route-$signal_name-root.pid"
  local child_pid_file="$TMP_DIR/$route-$signal_name-child.pid"
  local wrapper_output="$TMP_DIR/$route-$signal_name.out"
  local harness_output

  harness_output="$(PATH="$route_path" "$PYTHON_BIN" - \
    "$HELPER" "$PROCESS_SCRIPT" "$root_pid_file" "$child_pid_file" \
    "$signal_name" "$wrapper_output" <<'PY_CANCEL_HARNESS'
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

helper, process_script, root_file, child_file, signal_name, output_file = sys.argv[1:]
with open(output_file, "wb") as output:
    wrapper = subprocess.Popen(
        [helper, "30", process_script, root_file, child_file],
        stdout=output,
        stderr=subprocess.STDOUT,
    )
# Аварийный сторож синхронизации приходит из одного места на файл.
event_guard = float(os.environ["EVENT_GUARD_SECONDS"])
deadline = time.monotonic() + event_guard
while time.monotonic() < deadline and not Path(child_file).exists():
    if wrapper.poll() is not None:
        break
    time.sleep(0.05)
if not Path(child_file).exists():
    wrapper.kill()
    wrapper.wait()
    print("missing-child")
    raise SystemExit(0)
os.kill(wrapper.pid, getattr(signal, "SIG" + signal_name))
try:
    return_code = wrapper.wait(timeout=event_guard)
except subprocess.TimeoutExpired:
    wrapper.kill()
    wrapper.wait()
    print("wrapper-timeout")
    raise SystemExit(0)
if return_code < 0:
    return_code = 128 + abs(return_code)
print(return_code)
PY_CANCEL_HARNESS
)"

  assert_eq "$harness_output" "$expected_rc" \
    "$route возвращает shell-код внешнего SIG$signal_name"
  local root_pid="$(cat "$root_pid_file" 2>/dev/null)"
  local child_pid="$(cat "$child_pid_file" 2>/dev/null)"
  assert_process_gone "$root_pid" "$route SIG$signal_name завершает корневой процесс"
  assert_process_gone "$child_pid" "$route SIG$signal_name завершает устойчивого потомка"
}

assert_double_signal_cleanup() {
  local route="$1"
  local route_path="$2"
  local root_pid_file="$TMP_DIR/$route-double-root.pid"
  local child_pid_file="$TMP_DIR/$route-double-child.pid"
  local wrapper_output="$TMP_DIR/$route-double.out"
  local cancel_ready_file="$TMP_DIR/$route-double-cancel-ready"
  local harness_output

  harness_output="$(PATH="$route_path" "$PYTHON_BIN" - \
    "$SIGNAL_HARNESS" "$PROCESS_SCRIPT" "$root_pid_file" "$child_pid_file" \
    "$wrapper_output" "$cancel_ready_file" <<'PY_DOUBLE_HARNESS'
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

helper, process_script, root_file, child_file, output_file, cancel_file = sys.argv[1:]
wrapper_env = dict(os.environ)
wrapper_env["U2_WITH_TIMEOUT_HARNESS_CANCEL_READY_FILE"] = cancel_file
with open(output_file, "wb") as output:
    wrapper = subprocess.Popen(
        [helper, "30", process_script, root_file, child_file],
        stdout=output,
        stderr=subprocess.STDOUT,
        env=wrapper_env,
    )
# Аварийный сторож синхронизации приходит из одного места на файл.
event_guard = float(os.environ["EVENT_GUARD_SECONDS"])
deadline = time.monotonic() + event_guard
while time.monotonic() < deadline and not Path(child_file).exists():
    if wrapper.poll() is not None:
        break
    time.sleep(0.05)
if not Path(child_file).exists():
    wrapper.kill()
    wrapper.wait()
    print("missing-child")
    raise SystemExit(0)
os.kill(wrapper.pid, signal.SIGTERM)
# Второй сигнал ДРУГОГО типа отправляется по событию «cleanup уже начат и
# повторные сигналы игнорируются», а не по догадке о длительности grace-периода.
deadline = time.monotonic() + event_guard
while time.monotonic() < deadline and not Path(cancel_file).exists():
    if wrapper.poll() is not None:
        break
    time.sleep(0.05)
if not Path(cancel_file).exists():
    wrapper.kill()
    wrapper.wait()
    print("missing-cancel-ready")
    raise SystemExit(0)
try:
    os.kill(wrapper.pid, signal.SIGINT)
except (ProcessLookupError, PermissionError):
    pass
try:
    return_code = wrapper.wait(timeout=event_guard)
except subprocess.TimeoutExpired:
    wrapper.kill()
    wrapper.wait()
    print("wrapper-timeout")
    raise SystemExit(0)
if return_code < 0:
    return_code = 128 + abs(return_code)
print(return_code)
PY_DOUBLE_HARNESS
)"

  assert_eq "$harness_output" "143" \
    "$route: двойной сигнал (TERM→INT) возвращает код первого сигнала (143)"
  local root_pid="$(cat "$root_pid_file" 2>/dev/null)"
  local child_pid="$(cat "$child_pid_file" 2>/dev/null)"
  assert_process_gone "$root_pid" \
    "$route: двойной сигнал (TERM→INT) завершает корневой процесс"
  assert_process_gone "$child_pid" \
    "$route: двойной сигнал (TERM→INT) завершает устойчивого потомка"
}

# Отмена обёртки до deadline обязана очищать отдельную сессию fallback, а не
# оставлять корень или TERM-устойчивого потомка жить после завершения агента.
FALLBACK_CANCEL_ROOT_PID_FILE="$TMP_DIR/fallback-cancel-root.pid"
FALLBACK_CANCEL_CHILD_PID_FILE="$TMP_DIR/fallback-cancel-child.pid"
PATH="$FALLBACK_BIN" "$HELPER" 30 "$PROCESS_SCRIPT" \
  "$FALLBACK_CANCEL_ROOT_PID_FILE" "$FALLBACK_CANCEL_CHILD_PID_FILE" \
  >"$TMP_DIR/fallback-cancel.out" 2>&1 &
FALLBACK_WRAPPER_PID=$!
wait_for_pid_file "$FALLBACK_CANCEL_CHILD_PID_FILE" "$FALLBACK_WRAPPER_PID"
FALLBACK_WAIT_RC=$?
if [ "$FALLBACK_WAIT_RC" = "0" ]; then
  pass "fallback cancellation-тест дождался потомка"
else
  fail "fallback cancellation-тест дождался потомка — $(pid_file_wait_reason "$FALLBACK_WAIT_RC")"
fi
kill -TERM "$FALLBACK_WRAPPER_PID" 2>/dev/null
wait "$FALLBACK_WRAPPER_PID" 2>/dev/null
FALLBACK_CANCEL_RC=$?
assert_eq "$FALLBACK_CANCEL_RC" "143" \
  "fallback возвращает shell-код внешнего SIGTERM"
FALLBACK_CANCEL_ROOT_PID="$(cat "$FALLBACK_CANCEL_ROOT_PID_FILE" 2>/dev/null)"
FALLBACK_CANCEL_CHILD_PID="$(cat "$FALLBACK_CANCEL_CHILD_PID_FILE" 2>/dev/null)"
assert_process_gone "$FALLBACK_CANCEL_ROOT_PID" \
  "fallback внешняя отмена завершает корневой процесс"
assert_process_gone "$FALLBACK_CANCEL_CHILD_PID" \
  "fallback внешняя отмена завершает TERM-устойчивого потомка"
for external_signal_case in INT:130 HUP:129; do
  assert_external_signal_cleanup fallback "$FALLBACK_BIN" \
    "${external_signal_case%%:*}" "${external_signal_case##*:}"
done

# Временная копия реального helper получает только тестовые точки наблюдения.
# Все пять anchor обязаны быть единственными: иначе тест останавливается, а не
# инструментирует неоднозначный фрагмент. Production-файл при этом не меняется.
SIGNAL_HARNESS_TOOLS="$TMP_DIR/signal-harness-tools"
SIGNAL_HARNESS="$SIGNAL_HARNESS_TOOLS/with-timeout.sh"
mkdir -p "$SIGNAL_HARNESS_TOOLS"
ln -s "$PYTHON_RUNNER" "$SIGNAL_HARNESS_TOOLS/run-python.sh"
"$PYTHON_RUNNER" - "$HELPER" "$SIGNAL_HARNESS" <<'PY_BUILD_SIGNAL_HARNESS'
from pathlib import Path
import sys

source_path = Path(sys.argv[1])
harness_path = Path(sys.argv[2])
source = source_path.read_text(encoding="utf-8")

instrumentation = (
    (
        "native cleanup",
        "    trap '' TERM INT HUP\n",
        r'''
    if [ -n "${U2_WITH_TIMEOUT_HARNESS_CANCEL_READY_FILE-}" ]; then
      : > "$U2_WITH_TIMEOUT_HARNESS_CANCEL_READY_FILE"
    fi
''',
    ),
    (
        "first fallback signal",
        "    if pending_cancellation is None:\n        pending_cancellation = signum\n",
        r'''        first_signal_file = os.environ.get(
            "U2_WITH_TIMEOUT_HARNESS_FIRST_SIGNAL_FILE"
        )
        if first_signal_file:
            with open(first_signal_file, "w", encoding="utf-8") as marker:
                marker.write(str(signum))
''',
    ),
    (
        "fallback cleanup",
        "def terminate_tree(initial_signal):\n",
        r'''    cancel_ready_file = os.environ.get(
        "U2_WITH_TIMEOUT_HARNESS_CANCEL_READY_FILE"
    )
    if cancel_ready_file:
        with open(cancel_ready_file, "w", encoding="utf-8"):
            pass
''',
    ),
    (
        "startup window",
        "for handled_signal in handled_signals:\n    signal.signal(handled_signal, record_cancellation)\n",
        r'''
# Инструментирование временной тестовой копии: production-helper этого
# ready/release-протокола не содержит и потому не может расширить свой deadline.
harness_ready_file = os.environ.get("U2_WITH_TIMEOUT_HARNESS_READY_FILE")
harness_release_file = os.environ.get("U2_WITH_TIMEOUT_HARNESS_RELEASE_FILE")
if harness_ready_file and harness_release_file:
    with open(harness_ready_file, "w", encoding="utf-8"):
        pass
    harness_guard_deadline = time.monotonic() + 120
    while not os.path.exists(harness_release_file):
        if time.monotonic() >= harness_guard_deadline:
            print("ОШИБКА: тестовый harness не получил release.", file=sys.stderr)
            sys.exit(126)
        time.sleep(0.01)
''',
    ),
    (
        "deadline release",
        "        if pending_cancellation is not None:\n            raise ExternalCancellation(pending_cancellation)\n",
        r'''
        # Инструментирование временной тестовой копии: production-helper этого
        # release-протокола не содержит и не может отложить боевой hard-timeout.
        # Барьер удерживает СТАРТ отсчёта дедлайна до события теста «PID-файлы
        # записаны»; истечение и cleanup дальше идут тем же production-кодом.
        harness_deadline_release_file = os.environ.get(
            "U2_WITH_TIMEOUT_HARNESS_DEADLINE_RELEASE_FILE"
        )
        if harness_deadline_release_file:
            harness_deadline_guard = time.monotonic() + float(
                os.environ["EVENT_GUARD_SECONDS"]
            )
            while not os.path.exists(harness_deadline_release_file):
                if time.monotonic() >= harness_deadline_guard:
                    print(
                        "ОШИБКА: тестовый harness не получил release дедлайна.",
                        file=sys.stderr,
                    )
                    sys.exit(126)
                time.sleep(0.01)
''',
    ),
)

for label, anchor, addition in instrumentation:
    if source.count(anchor) != 1:
        raise SystemExit(f"не найден единственный anchor: {label}")
    source = source.replace(anchor, anchor + addition)

harness_path.write_text(source, encoding="utf-8")
PY_BUILD_SIGNAL_HARNESS
chmod +x "$SIGNAL_HARNESS"

# Deadline-сценарий fallback-маршрута под барьером готовности. Production-пин
# выше запрещает helper'у файловые тестовые протоколы, поэтому барьер живёт в
# инструментированной копии: точка «deadline release» удерживает старт отсчёта,
# пока тест не подтвердит непустые PID-файлы через wait_for_pid_file (аварийный
# сторож — EVENT_GUARD_SECONDS). После release истечение и cleanup идут тем же
# production-кодом process.wait(timeout)/terminate_tree; семантика утверждений
# (124, исчезновение корня и потомка) не менялась.
ROOT_PID_FILE="$TMP_DIR/root.pid"
CHILD_PID_FILE="$TMP_DIR/child.pid"
DEADLINE_BARRIER_OUTPUT="$TMP_DIR/deadline-barrier.out"
DEADLINE_RELEASE_FILE="$TMP_DIR/deadline-release"
PATH="$FALLBACK_BIN" \
  U2_WITH_TIMEOUT_HARNESS_DEADLINE_RELEASE_FILE="$DEADLINE_RELEASE_FILE" \
  "$SIGNAL_HARNESS" 1 "$PROCESS_SCRIPT" "$ROOT_PID_FILE" "$CHILD_PID_FILE" \
  >"$DEADLINE_BARRIER_OUTPUT" 2>&1 &
DEADLINE_WRAPPER_PID=$!
wait_for_pid_file "$ROOT_PID_FILE" "$DEADLINE_WRAPPER_PID"
DEADLINE_ROOT_WAIT_RC=$?
if [ "$DEADLINE_ROOT_WAIT_RC" = "0" ]; then
  pass "fallback deadline-сценарий дождался записи корневого PID до старта дедлайна"
else
  fail "fallback deadline-сценарий дождался записи корневого PID до старта дедлайна — $(pid_file_wait_reason "$DEADLINE_ROOT_WAIT_RC")"
fi
wait_for_pid_file "$CHILD_PID_FILE" "$DEADLINE_WRAPPER_PID"
DEADLINE_CHILD_WAIT_RC=$?
if [ "$DEADLINE_CHILD_WAIT_RC" = "0" ]; then
  pass "fallback deadline-сценарий дождался записи дочернего PID до старта дедлайна"
else
  fail "fallback deadline-сценарий дождался записи дочернего PID до старта дедлайна — $(pid_file_wait_reason "$DEADLINE_CHILD_WAIT_RC")"
fi
# Release выдаётся и при красном барьере: удержанный дедлайн обязан истечь и
# добить группу, иначе сироты пережили бы тест.
: >"$DEADLINE_RELEASE_FILE"
wait "$DEADLINE_WRAPPER_PID" 2>/dev/null
DEADLINE_BARRIER_RC=$?
assert_eq "$DEADLINE_BARRIER_RC" "124" \
  "fallback под барьером готовности: истечение времени возвращает 124"
ROOT_PID="$(cat "$ROOT_PID_FILE" 2>/dev/null)"
CHILD_PID="$(cat "$CHILD_PID_FILE" 2>/dev/null)"
assert_process_gone "$ROOT_PID" "fallback завершает корневой процесс"
assert_process_gone "$CHILD_PID" "fallback завершает дочерний процесс"

assert_double_signal_cleanup fallback "$FALLBACK_BIN"

# Инвариант первого сигнала в ОКНЕ ЗАПУСКА: если TERM затем INT приходят до
# готовности супервизора (обработчики уже установлены, потомок ещё не запущен),
# код выхода обязан отражать ПЕРВЫЙ сигнал (143), а не последний (130). Окно
# открывается и закрывается явным тестовым барьером, поэтому порядок не зависит
# от скорости запуска интерпретатора.
STARTUP_READY_FILE="$TMP_DIR/startup-ready"
STARTUP_RELEASE_FILE="$TMP_DIR/startup-release"
STARTUP_FIRST_SIGNAL_FILE="$TMP_DIR/startup-first-signal"
STARTUP_ORDER_RC="$(
  PATH="$FALLBACK_BIN" "$PYTHON_RUNNER" - "$SIGNAL_HARNESS" \
    "$STARTUP_READY_FILE" "$STARTUP_RELEASE_FILE" \
    "$STARTUP_FIRST_SIGNAL_FILE" <<'PY_STARTUP_FIRST_SIGNAL'
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

helper, ready_file, release_file, first_signal_file = sys.argv[1:]
wrapper_env = dict(os.environ)
wrapper_env["U2_WITH_TIMEOUT_HARNESS_READY_FILE"] = ready_file
wrapper_env["U2_WITH_TIMEOUT_HARNESS_RELEASE_FILE"] = release_file
wrapper_env["U2_WITH_TIMEOUT_HARNESS_FIRST_SIGNAL_FILE"] = first_signal_file
wrapper = subprocess.Popen(
    [helper, "30", "/bin/sleep", "30"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=wrapper_env,
)
# Явное событие доказывает, что обработчики уже установлены, а супервизор ещё не
# готов. Предел ниже — только аварийный сторож зависшего теста.
event_guard = float(os.environ["EVENT_GUARD_SECONDS"])
deadline = time.monotonic() + event_guard
while time.monotonic() < deadline and not Path(ready_file).exists():
    if wrapper.poll() is not None:
        break
    time.sleep(0.05)
if not Path(ready_file).exists():
    wrapper.kill()
    wrapper.wait()
    print("missing-startup-ready")
    raise SystemExit(0)
os.kill(wrapper.pid, signal.SIGTERM)
# Дожидаемся события обработки ПЕРВОГО сигнала; без этого ядро вправе доставить
# два посланных подряд сигнала в другом порядке.
deadline = time.monotonic() + event_guard
while time.monotonic() < deadline and not Path(first_signal_file).exists():
    if wrapper.poll() is not None:
        break
    time.sleep(0.05)
if not Path(first_signal_file).exists():
    wrapper.kill()
    wrapper.wait()
    print("missing-first-signal")
    raise SystemExit(0)
try:
    os.kill(wrapper.pid, signal.SIGINT)
except (ProcessLookupError, PermissionError):
    pass
Path(release_file).touch()
try:
    return_code = wrapper.wait(timeout=event_guard)
except subprocess.TimeoutExpired:
    wrapper.kill()
    wrapper.wait()
    print("wrapper-timeout")
    raise SystemExit(0)
if return_code < 0:
    return_code = 128 + abs(return_code)
print(return_code)
PY_STARTUP_FIRST_SIGNAL
)"
assert_eq "$STARTUP_ORDER_RC" "143" \
  "fallback: TERM затем INT в окне запуска дают код первого сигнала (143)"

# Совместимый двойник GNU timeout воспроизводит две важные семантики native-пути:
# ранний выход 124 после TERM корня и 137 после принудительного KILL всей группы.
NATIVE_TIMEOUT_BIN="$TMP_DIR/native-timeout-bin"
mkdir -p "$NATIVE_TIMEOUT_BIN"
ln -s "$PYTHON_BIN" "$NATIVE_TIMEOUT_BIN/python3"
for native_tool in mktemp sed rm; do
  ln -s "$(command -v "$native_tool")" "$NATIVE_TIMEOUT_BIN/$native_tool"
done
cat >"$NATIVE_TIMEOUT_BIN/timeout" <<'NATIVE_TIMEOUT_BODY'
#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time

backend = os.path.basename(sys.argv[0])
with open(os.environ["NATIVE_INVOKED"], "w", encoding="utf-8") as marker:
    marker.write(backend)
seconds = int(sys.argv[5])
command = sys.argv[6:]
os.setpgid(0, 0)
signal.signal(signal.SIGTERM, lambda _signum, _frame: None)
process = subprocess.Popen(command)

# Все ошибки ready-протокола идут через один аварийный выход. Fake timeout сам
# является лидером исходной process group, поэтому он не может надёжно выполнить
# SIGKILL своей группы и затем вернуть код. Отдельный reaper запускается в новой
# session, ждёт однобайтовое событие ПОСЛЕ печати причины и убивает исходный PGID.
# Протокольный child PID здесь принципиально не используется: он и есть
# недоверенный вход, который проверяют ветки 99/100.
READY_REAPER = r"""
import os
import signal
import sys
import time

pgid = int(sys.argv[1])
if not sys.stdin.buffer.read(1):
    raise SystemExit(125)
try:
    os.killpg(pgid, signal.SIGTERM)
except ProcessLookupError:
    raise SystemExit(0)
time.sleep(0.2)
try:
    os.killpg(pgid, signal.SIGKILL)
except ProcessLookupError:
    pass
"""


def abort_ready(code, reason):
    print(f"native-ready[{code}]: {reason}", file=sys.stderr, flush=True)
    original_pgid = os.getpgrp()
    try:
        reaper = subprocess.Popen(
            [sys.executable, "-c", READY_REAPER, str(original_pgid)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        reaper.stdin.write(b"!")
        reaper.stdin.flush()
        reaper.stdin.close()
    except (OSError, ValueError):
        # Даже отказ запуска reaper остаётся fail-closed: синхронный KILL группы
        # завершит и fake, зато ни один descendant не переживёт ready-failure.
        os.killpg(original_pgid, signal.SIGKILL)
        os._exit(code)
    # Штатно сюда не возвращаемся: reaper сначала посылает TERM, затем KILL.
    # Эта ветка — лишь аварийный дубль на случай испорченного reaper-кода.
    time.sleep(5)
    os.killpg(original_pgid, signal.SIGKILL)
    os._exit(code)


# В deadline-сценариях отсчёт начинается только после события ИЗ САМОГО
# TERM-устойчивого потомка. Он создаёт marker строго после установки trap и
# завершённой записи собственного PID. EVENT_GUARD_SECONDS ограничивает лишь
# аварийное ожидание события; семантический deadline запускается ниже.
ready_file = os.environ.get("FAKE_TIMEOUT_READY_FILE")
ready_pid_file = os.environ.get("FAKE_TIMEOUT_READY_PID_FILE")
if ready_file or ready_pid_file:
    if not ready_file or not ready_pid_file:
        abort_ready(96, "не заданы marker и PID вместе")
    ready_deadline = time.monotonic() + float(os.environ["EVENT_GUARD_SECONDS"])
    while time.monotonic() < ready_deadline and not os.path.exists(ready_file):
        if process.poll() is not None:
            abort_ready(97, "команда завершилась до ready-marker потомка")
        time.sleep(0.05)
    if not os.path.exists(ready_file):
        abort_ready(98, "аварийный сторож не дождался ready-marker потомка")
    try:
        with open(ready_pid_file, encoding="utf-8") as pid_source:
            ready_pid = pid_source.read().strip()
    except FileNotFoundError:
        ready_pid = ""
    if not ready_pid.isdecimal():
        abort_ready(99, "после marker нет корректного child PID")
    try:
        os.kill(int(ready_pid), 0)
    except (ProcessLookupError, PermissionError):
        abort_ready(100, "child PID из marker-протокола не жив")
    observed_file = os.environ.get("FAKE_TIMEOUT_READY_OBSERVED_FILE")
    if observed_file:
        with open(observed_file, "w", encoding="utf-8") as marker:
            marker.write(ready_pid)
try:
    sys.exit(process.wait(timeout=seconds))
except subprocess.TimeoutExpired:
    os.killpg(os.getpgrp(), signal.SIGTERM)
    if os.environ.get("FAKE_TIMEOUT_MODE") == "early":
        process.wait(timeout=1)
        sys.exit(124)
    time.sleep(1)
    os.killpg(os.getpgrp(), signal.SIGKILL)
NATIVE_TIMEOUT_BODY
chmod +x "$NATIVE_TIMEOUT_BIN/timeout"

# Native route также не должен переживать внешнюю отмену shell-обёртки.
NATIVE_CANCEL_ROOT_PID_FILE="$TMP_DIR/native-cancel-root.pid"
NATIVE_CANCEL_CHILD_PID_FILE="$TMP_DIR/native-cancel-child.pid"
NATIVE_CANCEL_INVOKED_FILE="$TMP_DIR/native-cancel-invoked"
PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$NATIVE_CANCEL_INVOKED_FILE" \
  FAKE_TIMEOUT_MODE=early "$HELPER" 30 "$PROCESS_SCRIPT" \
  "$NATIVE_CANCEL_ROOT_PID_FILE" "$NATIVE_CANCEL_CHILD_PID_FILE" \
  >"$TMP_DIR/native-cancel.out" 2>&1 &
NATIVE_WRAPPER_PID=$!
wait_for_pid_file "$NATIVE_CANCEL_CHILD_PID_FILE" "$NATIVE_WRAPPER_PID"
NATIVE_WAIT_RC=$?
if [ "$NATIVE_WAIT_RC" = "0" ]; then
  pass "native cancellation-тест дождался потомка"
else
  fail "native cancellation-тест дождался потомка — $(pid_file_wait_reason "$NATIVE_WAIT_RC")"
fi
kill -TERM "$NATIVE_WRAPPER_PID" 2>/dev/null
wait "$NATIVE_WRAPPER_PID" 2>/dev/null
NATIVE_CANCEL_RC=$?
assert_eq "$NATIVE_CANCEL_RC" "143" \
  "native route возвращает shell-код внешнего SIGTERM"
NATIVE_CANCEL_ROOT_PID="$(cat "$NATIVE_CANCEL_ROOT_PID_FILE" 2>/dev/null)"
NATIVE_CANCEL_CHILD_PID="$(cat "$NATIVE_CANCEL_CHILD_PID_FILE" 2>/dev/null)"
assert_process_gone "$NATIVE_CANCEL_ROOT_PID" \
  "native внешняя отмена завершает корневой процесс"
assert_process_gone "$NATIVE_CANCEL_CHILD_PID" \
  "native внешняя отмена завершает TERM-устойчивого потомка"
for external_signal_case in INT:130 HUP:129; do
  NATIVE_INVOKED="$NATIVE_CANCEL_INVOKED_FILE" FAKE_TIMEOUT_MODE=early \
    assert_external_signal_cleanup native "$NATIVE_TIMEOUT_BIN" \
    "${external_signal_case%%:*}" "${external_signal_case##*:}"
done
NATIVE_INVOKED="$NATIVE_CANCEL_INVOKED_FILE" FAKE_TIMEOUT_MODE=early \
  assert_double_signal_cleanup native "$NATIVE_TIMEOUT_BIN"

NATIVE_ROOT_PID_FILE="$TMP_DIR/native-root.pid"
NATIVE_CHILD_PID_FILE="$TMP_DIR/native-child.pid"
NATIVE_READY_FILE="$TMP_DIR/native-child.ready"
NATIVE_INVOKED_FILE="$TMP_DIR/native-invoked"
NATIVE_READY_OBSERVED_FILE="$TMP_DIR/native-ready-observed"
NATIVE_TIMEOUT_OUTPUT="$TMP_DIR/native-timeout.out"
# Двухсекундная задержка — только мутационное разделение: без native-ready
# барьера секундный fake deadline гарантированно срабатывает ДО записи PID даже
# на быстрой машине. В зелёном сценарии fake ждёт событие и лишь затем включает
# deadline; своевременность из этой задержки не выводится.
NATIVE_DELAYED_PROCESS_SCRIPT="$TMP_DIR/native-delayed-process-tree.sh"
cat >"$NATIVE_DELAYED_PROCESS_SCRIPT" <<'NATIVE_DELAYED_PROCESS_BODY'
#!/bin/sh
echo "$$" >"$1"
/bin/sleep 2
/bin/sh -c '
  trap "" TERM INT HUP
  printf "%s\n" "$$" >"$1"
  : >"$2"
  exec /bin/sleep 86400
' _ "$2" "$3" &
wait
NATIVE_DELAYED_PROCESS_BODY
chmod +x "$NATIVE_DELAYED_PROCESS_SCRIPT"

PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$NATIVE_INVOKED_FILE" \
  FAKE_TIMEOUT_MODE=early \
  FAKE_TIMEOUT_READY_FILE="$NATIVE_READY_FILE" \
  FAKE_TIMEOUT_READY_PID_FILE="$NATIVE_CHILD_PID_FILE" \
  FAKE_TIMEOUT_READY_OBSERVED_FILE="$NATIVE_READY_OBSERVED_FILE" \
  run_and_capture "$NATIVE_TIMEOUT_OUTPUT" "$HELPER" 1 \
  "$NATIVE_DELAYED_PROCESS_SCRIPT" "$NATIVE_ROOT_PID_FILE" \
  "$NATIVE_CHILD_PID_FILE" "$NATIVE_READY_FILE"
NATIVE_TIMEOUT_RC=$?
assert_eq "$NATIVE_TIMEOUT_RC" "124" "native timeout возвращает нормализованный код 124"
assert_eq "$(cat "$NATIVE_INVOKED_FILE" 2>/dev/null)" "timeout" \
  "helper действительно выбирает native timeout"
assert_ne "$(cat "$NATIVE_READY_OBSERVED_FILE" 2>/dev/null)" "" \
  "native-ready барьер оставляет невакуумное доказательство события"
assert_eq "$(cat "$NATIVE_READY_OBSERVED_FILE" 2>/dev/null)" \
  "$(cat "$NATIVE_CHILD_PID_FILE" 2>/dev/null)" \
  "native deadline включается после наблюдения живого TERM-устойчивого потомка"

# Ready-failure обязан чистить всю группу по доверенному PGID, даже когда именно
# протокольный PID испорчен. Потомок ставит trap ДО записи отдельного фактического
# PID, затем пишет мусор в protocol PID, создаёт marker и живёт 86400 секунд.
BROKEN_READY_SCRIPT="$TMP_DIR/native-broken-ready-process-tree.sh"
BROKEN_READY_ACTUAL_PID_FILE="$TMP_DIR/native-broken-ready-actual.pid"
BROKEN_READY_PROTOCOL_PID_FILE="$TMP_DIR/native-broken-ready-protocol.pid"
BROKEN_READY_FILE="$TMP_DIR/native-broken-ready.marker"
BROKEN_READY_INVOKED_FILE="$TMP_DIR/native-broken-ready-invoked"
BROKEN_READY_OUTPUT="$TMP_DIR/native-broken-ready.out"
cat >"$BROKEN_READY_SCRIPT" <<'BROKEN_READY_PROCESS_BODY'
#!/bin/sh
/bin/sh -c '
  trap "" TERM INT HUP
  printf "%s\n" "$$" >"$1"
  printf "%s\n" "protocol-pid-is-corrupt" >"$2"
  : >"$3"
  exec /bin/sleep 86400
' _ "$1" "$2" "$3" &
wait
BROKEN_READY_PROCESS_BODY
chmod +x "$BROKEN_READY_SCRIPT"

PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$BROKEN_READY_INVOKED_FILE" \
  FAKE_TIMEOUT_MODE=early \
  FAKE_TIMEOUT_READY_FILE="$BROKEN_READY_FILE" \
  FAKE_TIMEOUT_READY_PID_FILE="$BROKEN_READY_PROTOCOL_PID_FILE" \
  run_and_capture "$BROKEN_READY_OUTPUT" "$HELPER" 30 \
  "$BROKEN_READY_SCRIPT" "$BROKEN_READY_ACTUAL_PID_FILE" \
  "$BROKEN_READY_PROTOCOL_PID_FILE" "$BROKEN_READY_FILE"
BROKEN_READY_RC=$?
assert_ne "$BROKEN_READY_RC" "0" \
  "native-ready[99]: wrapper fail-closed при испорченном протокольном PID"
assert_contains "$(cat "$BROKEN_READY_OUTPUT")" \
  "native-ready[99]: после marker нет корректного child PID" \
  "native-ready[99]: именованная причина напечатана до group-abort"
BROKEN_READY_ACTUAL_PID="$(cat "$BROKEN_READY_ACTUAL_PID_FILE" 2>/dev/null)"
assert_ne "$BROKEN_READY_ACTUAL_PID" "" \
  "native-ready[99]: отдельный фактический PID доказывает запуск потомка"
assert_process_gone "$BROKEN_READY_ACTUAL_PID" \
  "native-ready[99]: reaper добивает TERM-устойчивого потомка при сломанном PID"

for native_rc in 23 124; do
  NATIVE_STATUS_OUTPUT="$TMP_DIR/native-status-$native_rc.out"
  PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$NATIVE_INVOKED_FILE" FAKE_TIMEOUT_MODE=early \
    run_and_capture "$NATIVE_STATUS_OUTPUT" "$HELPER" 2 /bin/sh -c "exit $native_rc"
  NATIVE_STATUS_RC=$?
  if [ "$native_rc" -eq 124 ]; then
    assert_eq "$NATIVE_STATUS_RC" "125" \
      "native timeout оставляет код 124 только для реального истечения времени"
  else
    assert_eq "$NATIVE_STATUS_RC" "$native_rc" \
      "native timeout сохраняет обычный код команды $native_rc"
  fi
done
NATIVE_SIGNAL_OUTPUT="$TMP_DIR/native-signal.out"
PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$NATIVE_INVOKED_FILE" FAKE_TIMEOUT_MODE=early \
  run_and_capture "$NATIVE_SIGNAL_OUTPUT" "$HELPER" 2 /bin/sh -c 'kill -KILL "$$"'
NATIVE_SIGNAL_RC=$?
assert_eq "$NATIVE_SIGNAL_RC" "137" \
  "native timeout не принимает обычный SIGKILL команды за истечение времени"

NATIVE_ROOT_PID="$(cat "$NATIVE_ROOT_PID_FILE" 2>/dev/null)"
NATIVE_CHILD_PID="$(cat "$NATIVE_CHILD_PID_FILE" 2>/dev/null)"
assert_ne "$NATIVE_ROOT_PID" "" \
  "native deadline-сценарий записывает PID корневого процесса"
assert_ne "$NATIVE_CHILD_PID" "" \
  "native deadline-сценарий записывает PID TERM-устойчивого потомка"
assert_process_gone "$NATIVE_ROOT_PID" \
  "native timeout завершает корень после раннего выхода"
assert_process_gone "$NATIVE_CHILD_PID" \
  "native timeout добивает TERM-устойчивого потомка после раннего выхода корня"

DASH_BIN="$(command -v dash 2>/dev/null || true)"
if [ -n "$DASH_BIN" ]; then
  DASH_ROOT_PID_FILE="$TMP_DIR/dash-root.pid"
  DASH_CHILD_PID_FILE="$TMP_DIR/dash-child.pid"
  DASH_READY_FILE="$TMP_DIR/dash-child.ready"
  DASH_INVOKED_FILE="$TMP_DIR/dash-invoked"
  DASH_READY_OBSERVED_FILE="$TMP_DIR/dash-ready-observed"
  DASH_TIMEOUT_OUTPUT="$TMP_DIR/dash-timeout.out"
  PATH="$NATIVE_TIMEOUT_BIN" NATIVE_INVOKED="$DASH_INVOKED_FILE" \
    FAKE_TIMEOUT_MODE=early \
    FAKE_TIMEOUT_READY_FILE="$DASH_READY_FILE" \
    FAKE_TIMEOUT_READY_PID_FILE="$DASH_CHILD_PID_FILE" \
    FAKE_TIMEOUT_READY_OBSERVED_FILE="$DASH_READY_OBSERVED_FILE" \
    run_and_capture "$DASH_TIMEOUT_OUTPUT" "$DASH_BIN" "$HELPER" 1 \
    "$NATIVE_DELAYED_PROCESS_SCRIPT" "$DASH_ROOT_PID_FILE" \
    "$DASH_CHILD_PID_FILE" "$DASH_READY_FILE"
  DASH_TIMEOUT_RC=$?
  assert_eq "$DASH_TIMEOUT_RC" "124" "dash native timeout возвращает код 124"
  assert_eq "$(cat "$DASH_INVOKED_FILE" 2>/dev/null)" "timeout" \
    "dash запускает helper через native timeout"

  DASH_ROOT_PID="$(cat "$DASH_ROOT_PID_FILE" 2>/dev/null)"
  DASH_CHILD_PID="$(cat "$DASH_CHILD_PID_FILE" 2>/dev/null)"
  assert_ne "$(cat "$DASH_READY_OBSERVED_FILE" 2>/dev/null)" "" \
    "dash native-ready барьер оставляет невакуумное доказательство события"
  assert_eq "$(cat "$DASH_READY_OBSERVED_FILE" 2>/dev/null)" "$DASH_CHILD_PID" \
    "dash deadline включается после наблюдения живого TERM-устойчивого потомка"
  assert_ne "$DASH_ROOT_PID" "" \
    "dash native timeout записывает PID корневого процесса"
  assert_ne "$DASH_CHILD_PID" "" \
    "dash native timeout запускает TERM-устойчивого потомка"
  assert_process_gone "$DASH_ROOT_PID" \
    "dash native timeout завершает корневой процесс"
  assert_process_gone "$DASH_CHILD_PID" \
    "dash native timeout добивает TERM-устойчивого потомка"
else
  echo "  SKIP: dash недоступен; поведенческий native-path тест пропущен"
fi

GTIMEOUT_BIN="$TMP_DIR/gtimeout-bin"
mkdir -p "$GTIMEOUT_BIN"
ln -s "$PYTHON_BIN" "$GTIMEOUT_BIN/python3"
for native_tool in mktemp sed rm; do
  ln -s "$(command -v "$native_tool")" "$GTIMEOUT_BIN/$native_tool"
done
ln -s "$NATIVE_TIMEOUT_BIN/timeout" "$GTIMEOUT_BIN/gtimeout"
GTIMEOUT_INVOKED_FILE="$TMP_DIR/gtimeout-invoked"
GTIMEOUT_OUTPUT="$TMP_DIR/gtimeout.out"
PATH="$GTIMEOUT_BIN" NATIVE_INVOKED="$GTIMEOUT_INVOKED_FILE" FAKE_TIMEOUT_MODE=kill \
  run_and_capture "$GTIMEOUT_OUTPUT" "$HELPER" 1 /bin/sh -c 'trap "" TERM; /bin/sleep 30'
GTIMEOUT_RC=$?
assert_eq "$GTIMEOUT_RC" "124" "native gtimeout нормализует принудительный KILL в код 124"
assert_eq "$(cat "$GTIMEOUT_INVOKED_FILE" 2>/dev/null)" "gtimeout" \
  "helper действительно выбирает native gtimeout"

GTIMEOUT_RESERVED_OUTPUT="$TMP_DIR/gtimeout-reserved.out"
PATH="$GTIMEOUT_BIN" NATIVE_INVOKED="$GTIMEOUT_INVOKED_FILE" FAKE_TIMEOUT_MODE=early \
  run_and_capture "$GTIMEOUT_RESERVED_OUTPUT" "$HELPER" 2 /bin/sh -c 'exit 124'
GTIMEOUT_RESERVED_RC=$?
assert_eq "$GTIMEOUT_RESERVED_RC" "125" \
  "native gtimeout оставляет код 124 только для реального истечения времени"

extract_marked_shell() {
  local source_file="$1"
  local output_file="$2"
  local marker="$3"
  awk -v start="<!-- ${marker}:start -->" -v finish="<!-- ${marker}:end -->" '
    $0 == start { inside=1; next }
    $0 == finish { inside=0; found=1; next }
    inside && $0 !~ /^```/ { print }
    END { if (!found) exit 1 }
  ' "$source_file" >"$output_file"
}

extract_shell_block_containing() {
  local source_file="$1"
  local output_file="$2"
  local needle="$3"
  awk -v needle="$needle" '
    $0 == "```bash" { inside=1; buffer=""; matched=0; next }
    inside && $0 == "```" {
      if (matched) { printf "%s", buffer; emitted=1; exit }
      inside=0
      next
    }
    inside {
      buffer=buffer $0 ORS
      if (index($0, needle)) matched=1
    }
    END { if (!emitted) exit 1 }
  ' "$source_file" >"$output_file"
}

CALLSITE_STUB="$TMP_DIR/callsite-stub.sh"
cat >"$CALLSITE_STUB" <<'CALLSITE_STUB_BODY'
run_with_timeout() {
  local seconds="$1"
  shift
  local call_kind
  case " $* " in
    *" --json comments "*) call_kind="triage" ;;
    *" --json reviews "*) call_kind="reviews" ;;
    *" api "*) call_kind="comments" ;;
    *) call_kind="unknown" ;;
  esac
  if [[ "$SCENARIO" == "$call_kind-error" ]]; then
    echo "ОШИБКА: команда завершилась с кодом 23." >&2
    return 23
  fi
  if [[ "$SCENARIO" == "$call_kind-timeout" ]]; then
    echo "ОШИБКА: истечение времени (${seconds} с)." >&2
    return 124
  fi
  if [[ "$SCENARIO" == "$call_kind-empty" ]]; then
    return 0
  fi
  if [[ "$SCENARIO" == "$call_kind-invalid" ]]; then
    printf '{'
    return 0
  fi
  case "$call_kind" in
    triage) printf '{"comments":[]}' ;;
    reviews) printf '{"reviews":[]}' ;;
    comments) printf '[]' ;;
  esac
}
HEAD_COMMIT=0123456789abcdef0123456789abcdef01234567
CALLSITE_STUB_BODY

assert_callsite_fails_closed() {
  local block_file="$1"
  local scenario="$2"
  local expected_text="$3"
  local label="$4"
  local output_file="$TMP_DIR/$scenario.out"
  SCENARIO="$scenario" bash -c '. "$1"; . "$2"' _ "$CALLSITE_STUB" "$block_file" \
    >"$output_file" 2>&1
  local callsite_rc=$?
  assert_ne "$callsite_rc" "0" "$label останавливается для $scenario"
  assert_contains "$(cat "$output_file")" "$expected_text" \
    "$label явно диагностирует $scenario"
}

assert_callsite_succeeds() {
  local block_file="$1"
  local label="$2"
  local output_file="$TMP_DIR/callsite-valid-${label//[^a-zA-Z0-9]/_}.out"
  SCENARIO=valid bash -c '. "$1"; . "$2"' _ "$CALLSITE_STUB" "$block_file" \
    >"$output_file" 2>&1
  local callsite_rc=$?
  assert_eq "$callsite_rc" "0" "$label принимает валидный JSON без findings"
}

FINALIZE_CALLSITE="$TMP_DIR/finalize-triage-callsite.sh"
if extract_shell_block_containing "$ROOT/.claude/skills/finalize-pr/SKILL.md" \
    "$FINALIZE_CALLSITE" 'TRIAGE_JSON=$(run_with_timeout'; then
  sed -i.bak 's/<PR_NUMBER>/645/g' "$FINALIZE_CALLSITE"
  rm -f "$FINALIZE_CALLSITE.bak"
  pass "finalize-pr triage проверяется через реальный call site"
  for scenario in triage-error triage-timeout; do
    assert_callsite_fails_closed "$FINALIZE_CALLSITE" "$scenario" "СТОП" "finalize-pr triage"
  done
  assert_callsite_fails_closed "$FINALIZE_CALLSITE" triage-empty "пуст" "finalize-pr triage"
  assert_callsite_fails_closed "$FINALIZE_CALLSITE" triage-invalid "невалид" "finalize-pr triage"
  assert_callsite_succeeds "$FINALIZE_CALLSITE" "finalize-pr triage"
else
  fail "finalize-pr triage проверяется через реальный call site"
fi

# Generic wrappers no longer execute Copilot/network loops; only finalize owns timed calls.
for skill in finalize-pr; do
  SKILL_FILE="$ROOT/.claude/skills/$skill/SKILL.md"
  PREFLIGHT="$TMP_DIR/$skill-preflight.sh"
  if extract_marked_shell "$SKILL_FILE" "$PREFLIGHT" timeout-helper-preflight; then
    pass "$skill содержит исполняемый preflight помощника"
  else
    fail "$skill содержит исполняемый preflight помощника"
    continue
  fi

  SKILL_SANDBOX="$TMP_DIR/$skill-repo"
  mkdir -p "$SKILL_SANDBOX/.claude/tools"
  git -C "$SKILL_SANDBOX" init -q

  MISSING_OUTPUT="$TMP_DIR/$skill-missing.out"
  (cd "$SKILL_SANDBOX" && bash "$PREFLIGHT") >"$MISSING_OUTPUT" 2>&1
  MISSING_RC=$?
  MISSING_TEXT="$(cat "$MISSING_OUTPUT")"
  assert_ne "$MISSING_RC" "0" "$skill останавливается без помощника"
  assert_contains "$MISSING_TEXT" "with-timeout.sh" "$skill называет отсутствующий помощник"
  assert_contains "$MISSING_TEXT" "отсутствует" "$skill называет причину отсутствия"

  cp "$HELPER" "$SKILL_SANDBOX/.claude/tools/with-timeout.sh"
  cp "$ROOT/.claude/tools/run-python.sh" \
    "$SKILL_SANDBOX/.claude/tools/run-python.sh"
  chmod +x "$SKILL_SANDBOX/.claude/tools/run-python.sh"
  chmod -x "$SKILL_SANDBOX/.claude/tools/with-timeout.sh"
  NONEXEC_OUTPUT="$TMP_DIR/$skill-nonexec.out"
  (cd "$SKILL_SANDBOX" && bash "$PREFLIGHT") >"$NONEXEC_OUTPUT" 2>&1
  NONEXEC_RC=$?
  NONEXEC_TEXT="$(cat "$NONEXEC_OUTPUT")"
  assert_ne "$NONEXEC_RC" "0" "$skill останавливается с неисполнимым помощником"
  assert_contains "$NONEXEC_TEXT" "не исполним" "$skill называет причину неисполнимости"

  chmod +x "$SKILL_SANDBOX/.claude/tools/with-timeout.sh"
  COMMAND_ERROR_OUTPUT="$TMP_DIR/$skill-command-error.out"
  (cd "$SKILL_SANDBOX" && bash -c \
    '. "$1"; run_with_timeout 1 /bin/sh -c "exit 23"' _ "$PREFLIGHT") \
    >"$COMMAND_ERROR_OUTPUT" 2>&1
  COMMAND_ERROR_RC=$?
  COMMAND_ERROR_TEXT="$(cat "$COMMAND_ERROR_OUTPUT")"
  assert_eq "$COMMAND_ERROR_RC" "23" "$skill сохраняет код ошибки команды"
  assert_contains "$COMMAND_ERROR_TEXT" "завершилась с кодом 23" \
    "$skill явно диагностирует ошибку команды"

  RESERVED_ERROR_OUTPUT="$TMP_DIR/$skill-reserved-error.out"
  (cd "$SKILL_SANDBOX" && bash -c \
    '. "$1"; run_with_timeout 1 /bin/sh -c "exit 124"' _ "$PREFLIGHT") \
    >"$RESERVED_ERROR_OUTPUT" 2>&1
  RESERVED_ERROR_RC=$?
  RESERVED_ERROR_TEXT="$(cat "$RESERVED_ERROR_OUTPUT")"
  assert_eq "$RESERVED_ERROR_RC" "125" \
    "$skill не принимает обычный код команды 124 за истечение времени"
  assert_contains "$RESERVED_ERROR_TEXT" "завершилась с кодом 125" \
    "$skill диагностирует преобразованный обычный код команды"
  assert_not_contains "$RESERVED_ERROR_TEXT" "истечение времени" \
    "$skill не печатает ложную диагностику истечения времени"

  SKILL_TIMEOUT_OUTPUT="$TMP_DIR/$skill-timeout.out"
  (cd "$SKILL_SANDBOX" && bash -c \
    '. "$1"; run_with_timeout 1 /bin/sleep 5' _ "$PREFLIGHT") \
    >"$SKILL_TIMEOUT_OUTPUT" 2>&1
  SKILL_TIMEOUT_RC=$?
  SKILL_TIMEOUT_TEXT="$(cat "$SKILL_TIMEOUT_OUTPUT")"
  assert_eq "$SKILL_TIMEOUT_RC" "124" "$skill сохраняет отдельный код истечения времени"
  assert_contains "$SKILL_TIMEOUT_TEXT" "истечение времени" \
    "$skill явно диагностирует истечение времени"
done

for skill in finalize-pr; do
  if grep -nE '(^|[=(;&|[:space:]])timeout[[:space:]]+[0-9]' \
      "$ROOT/.claude/skills/$skill/SKILL.md" >"$TMP_DIR/$skill-direct-timeout.out"; then
    fail "$skill не вызывает системный timeout напрямую"
  else
    pass "$skill не вызывает системный timeout напрямую"
  fi
done

# Installer executable-bit/closure cases: install-distribution.test.py.

# --- Native-путь без статус-файла = fail-closed (успех не засчитывается) -------
# Инвариант: успех дочерней команды засчитывается ТОЛЬКО при доказательстве её
# фактического запуска и завершения (записанный статус-файл). Несовместимый
# timeout-shim, возвращающий свой код (в т.ч. 0), НЕ запустив команду, не должен
# читаться как успех — иначе commit-гейт принял бы «зелёные тесты», которых не было.

NATIVE_FAKE_BIN="$TMP_DIR/native-fake-bin"
mkdir -p "$NATIVE_FAKE_BIN"
fail_closed_marker="$TMP_DIR/fail-closed-marker"

for shim_code in 0 1 23; do
  printf '%s\n' '#!/bin/sh' "exit ${shim_code}" > "$NATIVE_FAKE_BIN/timeout"
  chmod +x "$NATIVE_FAKE_BIN/timeout"
  : > "$fail_closed_marker"
  PATH="$NATIVE_FAKE_BIN:$PATH" run_and_capture "$TMP_DIR/native-fake.out" \
    "$HELPER" 5 /bin/sh -c "printf X > '$fail_closed_marker'; exit 0"
  FAKE_RC=$?
  assert_ne "$FAKE_RC" "0" \
    "несовместимый timeout (код $shim_code) без статус-файла не даёт ложный успех"
  if [ -s "$fail_closed_marker" ]; then
    fail "команда не должна была запуститься под несовместимым shim (код $shim_code)"
  else
    pass "команда не запускалась под несовместимым shim (код $shim_code) — доказательства нет"
  fi
  assert_contains "$(cat "$TMP_DIR/native-fake.out")" "не доказан" \
    "fail-closed объяснён: запуск команды не доказан (код $shim_code)"
done

# Совместимый native timeout (реально запускает) — статус-файл авторитетен.
printf '%s\n' \
  '#!/bin/sh' \
  'while [ "$#" -gt 0 ]; do case "$1" in -s|-k) shift 2 ;; *) break ;; esac; done' \
  'shift' \
  'exec "$@"' > "$NATIVE_FAKE_BIN/timeout"
chmod +x "$NATIVE_FAKE_BIN/timeout"
PATH="$NATIVE_FAKE_BIN:$PATH" "$HELPER" 5 /bin/sh -c 'exit 0' >/dev/null 2>&1
assert_eq "$?" "0" "совместимый native timeout: успех команды сохраняется"
PATH="$NATIVE_FAKE_BIN:$PATH" "$HELPER" 5 /bin/sh -c 'exit 7' >/dev/null 2>&1
assert_eq "$?" "7" "совместимый native timeout: код падения команды сохраняется"

finish
