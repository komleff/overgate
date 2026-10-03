#!/usr/bin/env bash
# Помощник ограничения времени: тестовый крючок не РАСШИРЯЕТ окно, а сам
# помощник прозрачен для входного потока.
#
# Причина существования, часть 1 (крючок). Переменная
# U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS добавляла паузу перед запуском и
# принимала любое значение без верхней границы. Зеркальный крючок гейта коммита
# сведён минимумом и умеет только сужать окно — здесь было наоборот. На машине
# без нативного timeout это боевой маршрут: переменная в окружении растягивала
# обработчик сверх объявленного диспетчеру предела, тот снимал обработчик, и
# защита превращалась в пропуск.
#
# Причина существования, часть 2 (входной поток). На маршруте нативного timeout
# помощник запускал команду асинхронным списком, а такой список по POSIX
# получает stdin из /dev/null. Гейт коммита передаёт payload разбора по
# конвейеру: без прозрачности разбор видел бы пустой вход на каждой машине с GNU
# timeout — то есть ровно там, где защиту никто не проверял вручную.
#
# Причина существования, часть 3 (переносимость проверки). Проверка «получится
# ли продублировать вход» стояла группой, а по POSIX ошибка перенаправления у
# специальной встроенной команды завершает саму оболочку. В dash — то есть в
# `/bin/sh` типичного Linux — помощник на закрытом входе умирал раньше ветки
# запасного варианта, а bash и zsh на macOS вели себя мягче, поэтому расхождение
# видел только Linux. Поэтому закрытый вход проверяется ещё и явным запуском под
# строгой POSIX-оболочкой, если она на машине есть.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

HELPER="$ROOT/.claude/tools/with-timeout.sh"
PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Маршрут Python-fallback: PATH без timeout/gtimeout.
FALLBACK_BIN="$TMP_DIR/fallback-bin"
mkdir -p "$FALLBACK_BIN"
for tool in sh cat sleep env; do
  [ -x "/bin/$tool" ] && ln -s "/bin/$tool" "$FALLBACK_BIN/$tool"
done
PYTHON_BIN="$(command -v python3 || command -v python)"
ln -s "$PYTHON_BIN" "$FALLBACK_BIN/python3"
if PATH="$FALLBACK_BIN" command -v timeout >/dev/null 2>&1 || \
    PATH="$FALLBACK_BIN" command -v gtimeout >/dev/null 2>&1; then
  fail "стенд fallback обязан быть без нативного timeout"
fi

# Маршрут нативного timeout: минимальный стенд, повторяющий разбор аргументов
# GNU timeout и запускающий команду напрямую.
NATIVE_BIN="$TMP_DIR/native-bin"
mkdir -p "$NATIVE_BIN"
printf '%s\n' \
  '#!/bin/sh' \
  '# стенд GNU timeout: -s SIG -k N SECONDS команда…' \
  'while [ "$#" -gt 0 ]; do' \
  '  case "$1" in' \
  '    -s|-k) shift 2 ;;' \
  '    *) break ;;' \
  '  esac' \
  'done' \
  'shift' \
  'exec "$@"' > "$NATIVE_BIN/timeout"
chmod +x "$NATIVE_BIN/timeout"

elapsed_seconds() { # elapsed_seconds <окружение…> -- <команда…>
  "$PYTHON_RUNNER" - "$@" <<'PYX'
import subprocess
import sys
import time

argv = sys.argv[1:]
split = argv.index("--")
env_pairs = argv[:split]
command = argv[split + 1:]

import os

env = dict(os.environ)
for pair in env_pairs:
    name, _, value = pair.partition("=")
    env[name] = value

started = time.monotonic()
result = subprocess.run(command, env=env, capture_output=True, text=True)
print(f"{time.monotonic() - started:.2f}")
print(result.returncode)
PYX
}

# --- 1. Крючок паузы не расширяет окно ----------------------------------------
# Предел 3 с, пауза 30 с. Прежнее поведение дало бы не меньше 30 с; корректное —
# уложиться в предел и вернуть код истечения 124.

MEASURED="$(elapsed_seconds "PATH=$FALLBACK_BIN" \
  "U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS=30" -- \
  "$HELPER" 3 /bin/sleep 60)"
PAUSE_SECONDS="$(printf '%s\n' "$MEASURED" | sed -n '1p')"
PAUSE_RC="$(printf '%s\n' "$MEASURED" | sed -n '2p')"

WITHIN="$("$PYTHON_RUNNER" -c 'import sys; print("OK" if float(sys.argv[1]) <= 8 else "WIDENED")' "$PAUSE_SECONDS")"
assert_eq "$WITHIN" "OK" \
  "пауза крючка не растягивает окно сверх предела (замер $PAUSE_SECONDS с при пределе 3 с)"
assert_eq "$PAUSE_RC" "124" "по истечении предела помощник возвращает свой код истечения"

# Пауза ВНУТРИ предела обязана вычитаться из ожидания, а не прибавляться к нему.
# Предел 10 с, пауза 9 с, команда не завершается: корректное поведение — около
# 10 с всего (9 паузы + 1 ожидания), прежнее сложение дало бы около 19 с.
DEDUCTED="$(elapsed_seconds "PATH=$FALLBACK_BIN" \
  "U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS=9" -- \
  "$HELPER" 10 /bin/sleep 60)"
DEDUCTED_SECONDS="$(printf '%s\n' "$DEDUCTED" | sed -n '1p')"
DEDUCTED_RC="$(printf '%s\n' "$DEDUCTED" | sed -n '2p')"
DEDUCTED_OK="$("$PYTHON_RUNNER" -c 'import sys; print("OK" if float(sys.argv[1]) <= 14 else "ADDED")' "$DEDUCTED_SECONDS")"
assert_eq "$DEDUCTED_OK" "OK" \
  "пауза вычитается из ожидания, а не прибавляется (замер $DEDUCTED_SECONDS с при пределе 10 с)"
assert_eq "$DEDUCTED_RC" "124" "с вычтенной паузой предел всё равно срабатывает"

# Пауза внутри предела не ломает штатный запуск: команда успевает завершиться.
QUICK="$(elapsed_seconds "PATH=$FALLBACK_BIN" \
  "U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS=1" -- \
  "$HELPER" 20 /bin/sh -c 'exit 7')"
assert_eq "$(printf '%s\n' "$QUICK" | sed -n '2p')" "7" \
  "пауза внутри предела сохраняет код выхода команды"

# Мусорное значение крючка паузы не должно ни падать, ни растягивать окно.
GARBAGE="$(elapsed_seconds "PATH=$FALLBACK_BIN" \
  "U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS=не-число" -- \
  "$HELPER" 20 /bin/sh -c 'exit 5')"
assert_eq "$(printf '%s\n' "$GARBAGE" | sed -n '2p')" "5" \
  "нечисловое значение крючка паузы игнорируется"

# Без крючка поведение прежнее.
BASELINE="$(elapsed_seconds "PATH=$FALLBACK_BIN" -- "$HELPER" 3 /bin/sleep 60)"
assert_eq "$(printf '%s\n' "$BASELINE" | sed -n '2p')" "124" \
  "без крючка предел работает как раньше"

# --- 2. Прозрачность входного потока на обоих маршрутах -----------------------

FALLBACK_STDIN="$(printf 'полезная-нагрузка' | PATH="$FALLBACK_BIN" "$HELPER" 10 cat)"
assert_eq "$FALLBACK_STDIN" "полезная-нагрузка" \
  "маршрут Python-fallback пропускает входной поток к команде"

NATIVE_STDIN="$(printf 'полезная-нагрузка' | PATH="$NATIVE_BIN:$PATH" "$HELPER" 10 cat)"
assert_eq "$NATIVE_STDIN" "полезная-нагрузка" \
  "маршрут нативного timeout пропускает входной поток к команде"

# Закрытый входной поток не должен ронять помощник: команда просто получает пусто.
CLOSED_STDIN="$(PATH="$NATIVE_BIN:$PATH" "$HELPER" 10 /bin/sh -c 'cat; echo готово' 0<&- 2>&1)"
assert_eq "$?" "0" "закрытый входной поток не роняет помощник"
assert_eq "$CLOSED_STDIN" "готово" \
  "команда с закрытым входом выполняется, и помощник не печатает диагностики"

# --- 3. Тот же инвариант под строгой POSIX-оболочкой ---------------------------
# На Linux `/bin/sh` и так dash, поэтому проверка выше идёт под ним сама. На
# macOS `/bin/sh` — bash в режиме sh, и расхождение оставалось невидимым: тест
# был зелёным локально и красным в CI. Запускаем помощник строгой оболочкой явно.

STRICT_SHELL=""
for candidate in dash ash busybox; do
  if command -v "$candidate" >/dev/null 2>&1; then
    STRICT_SHELL="$(command -v "$candidate")"
    break
  fi
done

if [ -n "$STRICT_SHELL" ]; then
  STRICT_CLOSED="$(PATH="$NATIVE_BIN:$PATH" "$STRICT_SHELL" "$HELPER" 10 \
    /bin/sh -c 'cat; echo готово' 0<&- 2>&1)"
  STRICT_RC=$?
  assert_eq "$STRICT_RC" "0" \
    "строгая POSIX-оболочка ($STRICT_SHELL): закрытый вход не роняет помощник"
  assert_eq "$STRICT_CLOSED" "готово" \
    "строгая POSIX-оболочка: команда с закрытым входом выполняется без диагностики"

  STRICT_STDIN="$(printf 'полезная-нагрузка' | PATH="$NATIVE_BIN:$PATH" \
    "$STRICT_SHELL" "$HELPER" 10 cat)"
  assert_eq "$STRICT_STDIN" "полезная-нагрузка" \
    "строгая POSIX-оболочка: входной поток доходит до команды"
else
  # Пропуск обязан быть ВИДЕН: молчаливый пропуск читается как зелёный прогон.
  pass "строгая POSIX-оболочка на машине не найдена — проверка пропущена (в CI Linux она идёт через /bin/sh)"
fi

finish
