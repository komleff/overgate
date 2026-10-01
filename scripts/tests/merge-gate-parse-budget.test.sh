#!/usr/bin/env bash
# Гейт публикации обязан быть fail-closed ПО ВРЕМЕНИ РАЗБОРА.
#
# Причина существования: разбор команды шёл без собственного предела, а стоимость
# разбора растёт экспоненциально по глубине вложенных подстановок. Замер на
# исходной голове (2026-08-12, macOS): 16 уровней — 0,61 с, 18 — 2,43 с,
# 19 — 4,87 с, 21 — 19,4 с при длине команды 111 символов. Объявленный
# диспетчеру предел — 5 с: команда чуть больше сотни символов выводила разбор за
# предел, диспетчер снимал обработчик, а снятый обработчик кода выхода не
# возвращает — блокирует же только код 2. Публикация уходила БЕЗ проверки тела.
#
# Здесь проверяются обе половины починки:
#   1) соответствие чисел — СУММА пределов всех фаз строго меньше объявленного
#      диспетчеру, с запасом на запуск интерпретатора и печать причины;
#   2) поведение — тяжёлый вход БЛОКИРУЕТСЯ (а не проходит и не висит), причём
#      проверка идёт сквозным вызовом настоящего hook'а.
#
# Фаз ДВЕ, и это второй дефект того же класса: предел стоял только на разборе, а
# проверка формулировки шла после него без предела и росла квадратично. Инвариант
# сформулирован не про фазу, а про все: ограничена КАЖДАЯ, истечение любой — код
# блокировки.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
HOOK="$ROOT/.claude/hooks/check-merge-ready.py"
SETTINGS="$ROOT/.claude/settings.json"

# Запас между пределом разбора и объявленным диспетчеру, секунды: обработчику
# нужно успеть запустить интерпретатор, напечатать причину и вернуть код 2.
REQUIRED_DISPATCHER_SLACK_SECONDS=2

# Вызывается ОПЕРАТОРОМ, а не в подстановке: результаты кладутся в HOOK_RC /
# HOOK_STDERR / HOOK_SECONDS, потому что подстановка выполняется в подоболочке и
# переменные из неё не возвращаются.
run_hook() { # run_hook <команда> [ПЕРЕМЕННАЯ=значение ...]
  local command="$1"
  shift
  local payload started finished
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$command")"
  started="$("$PYTHON_RUNNER" -c 'import time; print(time.monotonic())')"
  HOOK_STDERR="$(printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$@" \
    "$PYTHON_RUNNER" "$HOOK" 2>&1 >/dev/null)"
  HOOK_RC=$?
  finished="$("$PYTHON_RUNNER" -c 'import time; print(time.monotonic())')"
  HOOK_SECONDS="$("$PYTHON_RUNNER" -c 'import sys; print(f"{float(sys.argv[2])-float(sys.argv[1]):.2f}")' "$started" "$finished")"
}

# --- 1. Числа из настоящих источников -----------------------------------------

NUMBERS="$("$PYTHON_RUNNER" - "$ROOT" <<'PYX'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / ".claude" / "hooks"))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "check_merge_ready", root / ".claude" / "hooks" / "check-merge-ready.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with open(root / ".claude" / "settings.json", encoding="utf-8") as stream:
    settings = json.load(stream)

handlers = [
    handler
    for entry in settings.get("hooks", {}).get("PreToolUse", [])
    for handler in entry.get("hooks", [])
    if "check-merge-ready" in handler.get("command", "")
]
if len(handlers) != 1:
    raise SystemExit("ожидалась ровно одна запись гейта публикации в PreToolUse")
print(handlers[0]["timeout"])
print(module.PARSE_TIME_LIMIT_SECONDS)
print(module.PARSE_MAX_DEPTH)
print(module.READINESS_TIME_LIMIT_SECONDS)
PYX
)"
NUMBERS_RC=$?
assert_eq "$NUMBERS_RC" "0" "числа читаются из настоящих источников"

DECLARED="$(printf '%s\n' "$NUMBERS" | sed -n '1p')"
PARSE_LIMIT="$(printf '%s\n' "$NUMBERS" | sed -n '2p')"
PARSE_DEPTH="$(printf '%s\n' "$NUMBERS" | sed -n '3p')"
READINESS_LIMIT="$(printf '%s\n' "$NUMBERS" | sed -n '4p')"

COMPARE="$("$PYTHON_RUNNER" -c 'import sys; d,p,r,s=float(sys.argv[1]),float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4]); print("OK" if (p + r) < d and (d - p - r) >= s else "BAD")' \
  "$DECLARED" "$PARSE_LIMIT" "$READINESS_LIMIT" "$REQUIRED_DISPATCHER_SLACK_SECONDS")"
assert_eq "$COMPARE" "OK" \
  "сумма пределов фаз (разбор $PARSE_LIMIT с + формулировка $READINESS_LIMIT с) строго меньше объявленного диспетчеру ($DECLARED с) с запасом ≥ $REQUIRED_DISPATCHER_SLACK_SECONDS с"

POSITIVE="$("$PYTHON_RUNNER" -c 'import sys; print("OK" if float(sys.argv[1]) > 0 else "BAD")' "$READINESS_LIMIT")"
assert_eq "$POSITIVE" "OK" "фаза проверки формулировки имеет собственный положительный предел"

case "$PARSE_DEPTH" in
  ''|*[!0-9]*) fail "предел вложенности — целое число (получено '$PARSE_DEPTH')" ;;
  *) [ "$PARSE_DEPTH" -gt 0 ] && pass "предел вложенности — положительное целое ($PARSE_DEPTH)" \
       || fail "предел вложенности должен быть больше нуля" ;;
esac

# --- 2. Поведение: тяжёлый по разбору вход блокируется -------------------------

nested_command() { # nested_command <глубина>
  "$PYTHON_RUNNER" -c 'import sys; d=int(sys.argv[1]); print("echo " + "$("*d + "gh pr comment 1 --body \x27Готов к merge\x27" + ")"*d)' "$1"
}

DEEP="$(nested_command "$((PARSE_DEPTH + 13))")"
run_hook "$DEEP"
assert_eq "$HOOK_RC" "2" "вход с вложенностью выше предела блокируется"
assert_contains "$HOOK_STDERR" "разбор команды не завершён" \
  "блокировка по разбору объясняет, что доказательства нет"
WITHIN_LIMIT="$("$PYTHON_RUNNER" -c 'import sys; print("OK" if float(sys.argv[1]) < float(sys.argv[2]) else "SLOW")' "$HOOK_SECONDS" "$DECLARED")"
assert_eq "$WITHIN_LIMIT" "OK" \
  "вердикт получен за $HOOK_SECONDS с — внутри объявленного диспетчеру предела $DECLARED с"

# Ровно на пределе вложенности разбор ещё обязан доходить до вердикта по телу.
AT_LIMIT="$(nested_command "$PARSE_DEPTH")"
run_hook "$AT_LIMIT"
assert_eq "$HOOK_RC" "2" "вход ровно на пределе вложенности разбирается и блокируется по существу"
assert_not_contains "$HOOK_STDERR" "разбор команды не завершён" \
  "на пределе вложенности причина блокировки — содержимое, а не незавершённый разбор"

# --- 3. Тестовый крючок предела: только сужает ---------------------------------

run_hook "gh pr comment 1 --body 'обычный отчёт'" OVERGATE_MERGE_GATE_TEST_MAX_PARSE_SECONDS=0.000001
assert_eq "$HOOK_RC" "2" "сужённый крючком предел разбора блокирует"
assert_contains "$HOOK_STDERR" "не уложился в предел времени" \
  "блокировка по времени разбора названа своей причиной"

run_hook "gh pr comment 1 --body 'обычный отчёт'" OVERGATE_MERGE_GATE_TEST_MAX_PARSE_SECONDS=99999
assert_eq "$HOOK_RC" "0" "крючком нельзя расширить окно разбора: рабочий предел сохраняется"

for bad_override in 0 -5 abc; do
  run_hook "gh pr comment 1 --body 'обычный отчёт'" "OVERGATE_MERGE_GATE_TEST_MAX_PARSE_SECONDS=$bad_override"
  assert_eq "$HOOK_RC" "0" "неверное значение крючка '$bad_override' не меняет рабочий предел"
done

# --- 3b. Предел фазы проверки формулировки: тот же контракт --------------------
# Дефект: собственный предел стоял только у разбора. Проверка формулировки идёт
# после него и на длинном входе выходила за бюджет обработчика — тот снимался
# раньше вердикта.

run_hook "gh pr comment 1 --body 'обычный отчёт'" OVERGATE_MERGE_GATE_TEST_MAX_READINESS_SECONDS=0.000001
assert_eq "$HOOK_RC" "2" "сужённый крючком предел проверки формулировки блокирует"
assert_contains "$HOOK_STDERR" "проверка формулировки не завершена" \
  "блокировка по времени проверки формулировки названа своей причиной"

run_hook "gh pr comment 1 --body 'обычный отчёт'" OVERGATE_MERGE_GATE_TEST_MAX_READINESS_SECONDS=99999
assert_eq "$HOOK_RC" "0" "крючком нельзя расширить окно проверки формулировки"

for bad_override in 0 -5 abc; do
  run_hook "gh pr comment 1 --body 'обычный отчёт'" "OVERGATE_MERGE_GATE_TEST_MAX_READINESS_SECONDS=$bad_override"
  assert_eq "$HOOK_RC" "0" "неверное значение крючка формулировки '$bad_override' не меняет рабочий предел"
done

# Длинное тело проходит фазу проверки формулировки в рабочем пределе: инвариант
# «ограничено» не должен превращаться в «длинный отчёт не опубликовать».
#
# Payload собирается в ФАЙЛ, а не передаётся аргументом: у Linux предел длины
# ОДНОГО аргумента (128 КБ) строже общего предела macOS, и тело такого размера
# роняло сам стенд «списком аргументов», выдавая это за вердикт гейта.
LONG_TMP="$(mktemp -d)"
LONG_PAYLOAD="$LONG_TMP/long-body.json"
"$PYTHON_RUNNER" - "$LONG_PAYLOAD" <<'PYX'
import json
import sys

body = "строка обычного отчёта ревью без формулировки. " * 4000
command = "gh pr comment 1 --body '" + body + "'"
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({"tool_input": {"command": command}}, stream, ensure_ascii=False)
PYX

LONG_STARTED="$("$PYTHON_RUNNER" -c 'import time; print(time.monotonic())')"
env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$HOOK" < "$LONG_PAYLOAD" >/dev/null 2>&1
LONG_RC=$?
LONG_FINISHED="$("$PYTHON_RUNNER" -c 'import time; print(time.monotonic())')"
LONG_SECONDS="$("$PYTHON_RUNNER" -c 'import sys; print(f"{float(sys.argv[2])-float(sys.argv[1]):.2f}")' "$LONG_STARTED" "$LONG_FINISHED")"
rm -rf "$LONG_TMP"

assert_eq "$LONG_RC" "0" "длинное легитимное тело проходит обе фазы"
WITHIN_DECLARED="$("$PYTHON_RUNNER" -c 'import sys; print("OK" if float(sys.argv[1]) < float(sys.argv[2]) else "SLOW")' "$LONG_SECONDS" "$DECLARED")"
assert_eq "$WITHIN_DECLARED" "OK" \
  "вердикт по длинному телу получен за $LONG_SECONDS с — внутри объявленного предела $DECLARED с"

# --- 4. Штатная работа не задета ----------------------------------------------

run_hook "gh pr comment 1 --body 'обычный отчёт ревью'"
assert_eq "$HOOK_RC" "0" "легитимная инлайн-публикация проходит"
run_hook "git status"
assert_eq "$HOOK_RC" "0" "обычная команда разработчика проходит"
run_hook "gh pr comment 1 --body 'Готов к merge'"
assert_eq "$HOOK_RC" "2" "запрещённая формулировка по-прежнему блокируется"

# --- 5. Комментарии описывают существующие маршруты ---------------------------
# Дефект: docstring объявлял inline-токен рабочим маршрутом обхода, тогда как
# .agents/PIPELINE_ADR.md §3.23 фиксирует обратное, а комментарий над проверкой
# формулировки описывал блокировку подстановок (она веткой выше).

DOC_OUT="$("$PYTHON_RUNNER" - "$ROOT" <<'PYX'
import sys
from pathlib import Path

text = (Path(sys.argv[1]) / ".claude" / "hooks" / "check-merge-ready.py").read_text(encoding="utf-8")
docstring = text.split('"""')[1]
print("ADR_CITED" if "3.23" in docstring else "NO_ADR")
print("ROUTE_DENIED" if "рабочим маршрутом НЕ является" in docstring else "ROUTE_CLAIMED")

# Комментарий непосредственно перед проверкой запрещённой формулировки обязан
# описывать именно её, а не блокировку подстановок.
head = text.split("is_forbidden(publication.body")[0]
comment = "\n".join(
    line for line in head.splitlines()[-8:] if line.strip().startswith("#")
)
print("COMMENT_ON_TOPIC" if "формулировк" in comment else f"COMMENT_DRIFT {comment!r}")
PYX
)"
assert_contains "$DOC_OUT" "ADR_CITED" "docstring ссылается на решение §3.23"
assert_contains "$DOC_OUT" "ROUTE_DENIED" \
  "docstring не выдаёт inline-токен за рабочий маршрут обхода"
assert_contains "$DOC_OUT" "COMMENT_ON_TOPIC" \
  "комментарий перед проверкой формулировки описывает эту проверку"

finish
