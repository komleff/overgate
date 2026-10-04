#!/usr/bin/env bash
# Минимальный харнесс для shell-тестов beads-инструментов (bats в проекте нет —
# тесты на Vitest/NUnit, поэтому здесь самодостаточные .sh с assert-функциями).
TESTS_PASS=0
TESTS_FAIL=0
pass() { TESTS_PASS=$((TESTS_PASS + 1)); echo "  PASS: $1"; }
fail() { TESTS_FAIL=$((TESTS_FAIL + 1)); echo "  FAIL: $1" >&2; }

assert_eq() { if [ "$1" = "$2" ]; then pass "$3"; else fail "$3 — ожидалось '$2', получено '$1'"; fi; }
assert_ne() { if [ "$1" != "$2" ]; then pass "$3"; else fail "$3 — не ожидалось '$1'"; fi; }
# grep читает весь stdin: -q закрывает pipe при раннем совпадении и ломает
# положительную/отрицательную проверку под pipefail из-за SIGPIPE у printf.
# Сохраняем ОБА кода независимо от pipefail вызывающего shell. У grep код 1
# означает отсутствие совпадения, но ошибка писателя/grep не доказывает отсутствие.
assert_contains() {
  local -a search_status
  if printf '%s' "$1" | grep -F >/dev/null -- "$2"; then
    search_status=("${PIPESTATUS[@]}")
  else
    search_status=("${PIPESTATUS[@]}")
  fi
  case "${search_status[*]}" in
    '0 0') pass "$3" ;;
    '0 1') fail "$3 — нет '$2'" ;;
    *) fail "$3 — ошибка поиска (printf/grep: ${search_status[*]})" ;;
  esac
}
assert_not_contains() {
  local -a search_status
  if printf '%s' "$1" | grep -F >/dev/null -- "$2"; then
    search_status=("${PIPESTATUS[@]}")
  else
    search_status=("${PIPESTATUS[@]}")
  fi
  case "${search_status[*]}" in
    '0 1') pass "$3" ;;
    '0 0') fail "$3 — найдено '$2'" ;;
    *) fail "$3 — ошибка поиска (printf/grep: ${search_status[*]})" ;;
  esac
}

finish() { echo "ИТОГО $(basename "$0"): PASS=$TESTS_PASS FAIL=$TESTS_FAIL"; [ "$TESTS_FAIL" = "0" ]; }
