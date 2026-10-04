#!/usr/bin/env bash
# Продолжение строки убирается ДО разбора на обоих гейтах (паритет).
#
# Инвариант: оболочка убирает пару «обратная косая черта + перевод строки» ещё
# до разбиения на слова, поэтому `gh \<LF>pr comment` — одна команда `gh pr
# comment`, а не разорванные слова. Оба разборщика пакета выполняют эту
# нормализацию контекстно первым шагом. Промах здесь — ПРОПУСК публикации мимо
# гейта, а не лишняя блокировка, поэтому класс закрывается на ОБОИХ гейтах из
# одного источника (`shell_grammar.splice_line_continuations`).
#
# Контекст соблюдается: вне кавычек и в двойных — склейка; в одинарных кавычках
# обратная косая черта буквальна (склейки нет).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
MERGE_HOOK="$ROOT/.claude/hooks/check-merge-ready.py"
CLASSIFIER="$ROOT/.claude/hooks/commit_command_classifier.py"

# Продолжение строки: обратная косая черта + перевод строки.
BS='\'
LF=$'\n'

merge_verdict() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MERGE_HOOK" >/dev/null 2>&1
  printf '%s\n' "$?"
}
commit_class() { printf '%s' "$1" | "$PYTHON_RUNNER" "$CLASSIFIER" classify 2>/dev/null; }

assert_merge_blocks() { assert_eq "$(merge_verdict "$2")" "2" "merge блокирует: $1"; }
assert_merge_passes() { assert_eq "$(merge_verdict "$2")" "0" "merge пропускает: $1"; }
assert_commit_blocks() {
  local c; c="$(commit_class "$2")"
  if [ "$c" = "commit" ] || [ "$c" = "ambiguous" ]; then pass "commit блокирует ($c): $1"
  else fail "commit НЕ блокирует ($c): $1"; fi
}

FORBIDDEN="Готов к merge"

# --- 1. Продолжение строки между gh / pr / comment (каждая граница и обе) ------
# Оболочка склеивает в `gh pr comment`, публикация с запрещённым телом видна.

assert_merge_blocks "перенос между gh и pr" \
  "gh ${BS}${LF}pr comment 1 --body '${FORBIDDEN}'"
assert_merge_blocks "перенос между gh и pr (пробел после)" \
  "gh ${BS}${LF} pr comment 1 --body '${FORBIDDEN}'"
assert_merge_blocks "перенос между pr и comment" \
  "gh pr ${BS}${LF}comment 1 --body '${FORBIDDEN}'"
assert_merge_blocks "перенос внутри слова gh" \
  "g${BS}${LF}h pr comment 1 --body '${FORBIDDEN}'"
assert_merge_blocks "перенос на обеих границах сразу" \
  "gh ${BS}${LF} pr ${BS}${LF} comment 1 --body '${FORBIDDEN}'"

# Обычное тело с тем же переносом — не блок (склейка не создаёт ложных срабатываний).
assert_merge_passes "перенос между словами, обычное тело" \
  "gh ${BS}${LF}pr comment 1 --body 'обычный отчёт'"

# --- 2. Паритет: та же форма для git commit → commit-гейт блокирует -----------

assert_commit_blocks "перенос между git и commit" "git ${BS}${LF}commit -m z"
assert_commit_blocks "перенос внутри слова git" "g${BS}${LF}it commit -m z"
assert_commit_blocks "перенос между git и commit (пробел после)" \
  "git ${BS}${LF} commit -m z"

# --- 3. Одинарные кавычки: обратная косая черта буквальна, склейки НЕТ ---------
# Регресс-контроль: bash хранит literal backslash+LF в теле, это НЕ запрещённая
# формулировка, поэтому гейт не блокирует (иначе — ложный блок).

assert_merge_passes "перенос в одинарных кавычках тела" \
  "gh pr comment 1 --body 'Готов к ${BS}${LF}merge'"
assert_merge_passes "обратная косая в одинарной строке аргумента" \
  "echo 'a ${BS}${LF} b'"

# --- 4. Легитимные многострочные команды: ноль блокировок ---------------------

assert_merge_passes "многострочный docker run" \
  "docker run --rm ${BS}${LF}  -v /p:/app ${BS}${LF}  image"
assert_merge_passes "многострочный gcc" "gcc -Wall ${BS}${LF}  -o out main.c"
assert_merge_passes "многострочный find" "find . ${BS}${LF}  -name '*.py'"

# --- 5. Мутация: возврат к разбору по сырому тексту возвращает ПРОПУСК ----------
# Проверка не выродилась: если убрать нормализацию переносов из общего разбора,
# continuation-формы снова проходят мимо гейта.

MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$MUT_DIR/"
"$PYTHON_RUNNER" - "$MUT_DIR/shell_comment_parser.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
needle = "    source = shell_grammar.splice_line_continuations(source)\n"
if needle not in t:
    raise SystemExit("точка мутации не найдена")
p.write_text(t.replace(needle, "    source = source  # мутация: нормализация снята\n"), encoding="utf-8")
PYX
mut_merge() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MUT_DIR/check-merge-ready.py" >/dev/null 2>&1
  printf '%s\n' "$?"
}
# Проверяются формы МЕЖДУ словами: именно их закрывает нормализация. Перенос
# ВНУТРИ слова закрыт вторым слоем (декодирование слова), поэтому мутация его не
# вскрывает — он остаётся заблокированным и без нормализации.
assert_eq "$(mut_merge "gh ${BS}${LF} pr comment 1 --body '${FORBIDDEN}'")" "0" \
  "мутация: без нормализации перенос между gh и pr пропускает публикацию"
assert_eq "$(mut_merge "gh pr ${BS}${LF} comment 1 --body '${FORBIDDEN}'")" "0" \
  "мутация: без нормализации перенос между pr и comment пропускает публикацию"
assert_eq "$(mut_merge "gh ${BS}${LF} pr ${BS}${LF} comment 1 --body '${FORBIDDEN}'")" "0" \
  "мутация: без нормализации перенос на обеих границах пропускает публикацию"
# Контроль: исправный код те же формы блокирует.
assert_eq "$(merge_verdict "gh ${BS}${LF} pr comment 1 --body '${FORBIDDEN}'")" "2" \
  "контроль: исправная нормализация блокирует перенос между словами"
rm -rf "$MUT_DIR"

finish
