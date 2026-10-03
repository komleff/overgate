#!/usr/bin/env bash
# Арифметическое раскрытие $((EXPR)) — обычная команда, не публикация/носитель.
#
# Инвариант: оболочка ВЫЧИСЛЯЕТ содержимое `$((…))` как арифметику, а не
# исполняет его как команду. Поэтому `result=$((a*b))` — обычная команда: голое
# выражение (`a*b`, `2**8`, `a?b:c`, сдвиги) командным словом не является, а
# метасимвол `*` в нём — не glob. Промах здесь был ЛОЖНОЙ блокировкой обычной
# арифметики разработчика.
#
# Граница (не открыть дыру): `$( (cmd) )` — подстановка команды с подоболочкой
# (закрытие НЕ смежными `))`) остаётся консервативной; невалидная арифметика со
# смежными `))` (`$((a b))`) оболочкой не исполняется и тоже инертна.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
MERGE_HOOK="$ROOT/.claude/hooks/check-merge-ready.py"
CLASSIFIER="$ROOT/.claude/hooks/commit_command_classifier.py"

merge_verdict() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MERGE_HOOK" >/dev/null 2>&1
  printf '%s\n' "$?"
}
commit_class() { printf '%s' "$1" | "$PYTHON_RUNNER" "$CLASSIFIER" classify 2>/dev/null; }

# --- 1. Повседневная арифметика: merge пропускает, commit — ordinary ----------

ARITHMETIC=(
  'result=$((a*b))'
  'area=$((w*h))'
  'n=$((2**8))'
  'val=$((a?b:c))'
  'echo $((x<<2))'
  'echo $((a>>1))'
  'make -j$((n*2))'
  'x=$(( a * b ))'
  'y=$(( (a+b)*c ))'
  'echo $((1+2))'
  'i=$((i+1))'
  'echo "$((count % 10))"'
)
for c in "${ARITHMETIC[@]}"; do
  assert_eq "$(merge_verdict "$c")" "0" "merge пропускает арифметику: $c"
  assert_eq "$(commit_class "$c")" "ordinary" "commit ordinary на арифметике: $c"
done

# --- 2. Граница: невалидная арифметика со смежными )) — тоже инертна -----------
# `$((a b))` оболочка НЕ исполняет (синтаксическая ошибка), команду не запускает.

assert_eq "$(merge_verdict 'echo $((a b))')" "0" \
  "merge пропускает невалидную арифметику со смежным закрытием"
assert_eq "$(commit_class 'echo $((a b))')" "ordinary" \
  "commit ordinary на невалидной арифметике со смежным закрытием"

# --- 3. Граница: $( (cmd) ) подоболочка остаётся консервативной ----------------
# Несмежное закрытие `) )` — подстановка команды; публикация/commit внутри видны.

assert_eq "$(merge_verdict 'echo $((gh pr comment 1 --body "Готов к merge") )')" "2" \
  "merge блокирует публикацию в подоболочке подстановки команды"
assert_eq "$(merge_verdict 'x=$((cd /tmp) && gh pr comment 1 --body "Готов к merge")')" "2" \
  "merge блокирует публикацию в хвосте подстановки команды"
CMD_SUB_COMMIT="$(commit_class 'echo "$((git commit --allow-empty -m x) )"')"
if [ "$CMD_SUB_COMMIT" = "commit" ] || [ "$CMD_SUB_COMMIT" = "ambiguous" ]; then
  pass "commit блокирует git commit в подоболочке подстановки ($CMD_SUB_COMMIT)"
else
  fail "commit НЕ блокирует git commit в подоболочке подстановки ($CMD_SUB_COMMIT)"
fi

# --- 4. Граница: реальная публикация внутри арифметики через $() блокируется ---
# `$(( $(gh pr comment …) ))` — вложенная подстановка команды реальна.

assert_eq "$(merge_verdict 'echo $(( $(gh pr comment 1 --body "Готов к merge") ))')" "2" \
  "merge блокирует вложенную в арифметику подстановку с публикацией"

# --- 5. Мутация: эскалация арифметики в носителя возвращает ложный блок --------

MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$MUT_DIR/"
"$PYTHON_RUNNER" - "$MUT_DIR/shell_comment_parser.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
# Снимаем распознавание арифметики в основном контексте: `$((` снова разбирается
# как `$(` + `(` (подстановка команды), и `a*b` эскалируется в фантом.
needle = (
    '            if self.source.startswith("$((", position):\n'
    "                arith_end = self._scan_arithmetic(position, command)\n"
    "                if arith_end is not None:\n"
    "                    position = arith_end\n"
    "                    continue\n"
)
if needle not in t:
    raise SystemExit("точка мутации не найдена")
p.write_text(t.replace(needle, "", 1), encoding="utf-8")
PYX
mut_merge() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MUT_DIR/check-merge-ready.py" >/dev/null 2>&1
  printf '%s\n' "$?"
}
assert_eq "$(mut_merge 'result=$((a*b))')" "2" \
  "мутация: без распознавания арифметики обычное $((a*b)) снова ложно блокируется"
assert_eq "$(merge_verdict 'result=$((a*b))')" "0" \
  "контроль: с распознаванием арифметики $((a*b)) проходит"
rm -rf "$MUT_DIR"

finish
