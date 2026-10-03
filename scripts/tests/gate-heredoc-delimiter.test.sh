#!/usr/bin/env bash
# Разделитель heredoc разбирается общим shell-word парсером (паритет гейтов).
#
# Инвариант: оболочка применяет к разделителю heredoc только снятие кавычек, без
# раскрытия, поэтому терминатор известен статически при любом кавычировании и
# экранировании (`<<\EOF`, `<<E"OF"`, `<<'E'OF`, `<<"EOF"`, `<<'123'`, `<<':'`).
# Такая команда разбирается штатно: тело инертно, а команда после терминатора
# решается по СВОЕМУ телу — а не глушится через global_ambiguous. Промах здесь —
# ЛОЖНАЯ блокировка легитимной команды (безопасная сторона, но реальная).
#
# global_ambiguous остаётся только для разделителя с незакавыченным раскрытием
# (`<<$VAR`), где форма выглядит динамической и не является рабочей.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
MERGE_HOOK="$ROOT/.claude/hooks/check-merge-ready.py"
CLASSIFIER="$ROOT/.claude/hooks/commit_command_classifier.py"
LF=$'\n'
FORBIDDEN="Готов к merge"

merge_verdict() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MERGE_HOOK" >/dev/null 2>&1
  printf '%s\n' "$?"
}
commit_class() { printf '%s' "$1" | "$PYTHON_RUNNER" "$CLASSIFIER" classify 2>/dev/null; }

# Форма: heredoc с разделителем <delim>, терминатор <term>, затем команда с телом.
heredoc_then() { # heredoc_then <delim> <term> <тело>
  printf 'cat <<%s\ndata\n%s\ngh pr comment --body %s' "$1" "$2" "$3"
}

# --- 1. Статические разделители любого кавычирования разбираются штатно --------
# Запрещённое тело команды после терминатора → блок по ТЕЛУ; безобидное → пропуск.

# delim | term (снятие кавычек)
DELIMS=(
  '\EOF|EOF'
  'E"OF"|EOF'
  "'E'OF|EOF"
  '"EOF"|EOF'
  "'123'|123"
  "':'|:"
  "'./EOF'|./EOF"
)
for entry in "${DELIMS[@]}"; do
  delim="${entry%%|*}"
  term="${entry#*|}"
  assert_eq "$(merge_verdict "$(heredoc_then "$delim" "$term" "'${FORBIDDEN}'")")" "2" \
    "merge блокирует по телу: <<${delim} + запрещённое тело"
  assert_eq "$(merge_verdict "$(heredoc_then "$delim" "$term" "'обычный отчёт'")")" "0" \
    "merge пропускает: <<${delim} + безобидное тело"
done

# --- 2. Регресс-контроль: разделитель с раскрытием остаётся недоказанным --------

assert_eq "$(merge_verdict "cat <<\$VAR${LF}data${LF}gh pr comment --body '${FORBIDDEN}'")" "2" \
  "merge блокирует: <<\$VAR (незакавыченное раскрытие) остаётся global_ambiguous"

# --- 3. Паритет commit-гейта: heredoc + git commit после терминатора ----------

for entry in "${DELIMS[@]}"; do
  delim="${entry%%|*}"
  term="${entry#*|}"
  cls="$(commit_class "$(printf 'cat <<%s\ndata\n%s\ngit commit -m z' "$delim" "$term")")"
  if [ "$cls" = "commit" ] || [ "$cls" = "ambiguous" ]; then
    pass "commit видит git commit после <<${delim} ($cls)"
  else
    fail "commit НЕ видит git commit после <<${delim} ($cls)"
  fi
done

# --- 4. Трудовой body-путь: $(cat <<TOKEN ... TOKEN) любого кавычирования -------
# Тело извлекается (решение по телу), а не глушится как непрозрачная подстановка.

body_form() { # body_form <delim> <term> <тело>
  printf 'gh pr comment 1 --body "$(cat <<%s\n%s\n%s\n)"' "$1" "$3" "$2"
}
for entry in "'EOF'|EOF" '"EOF"|EOF' "'123'|123" "':'|:"; do
  delim="${entry%%|*}"
  term="${entry#*|}"
  assert_eq "$(merge_verdict "$(body_form "$delim" "$term" "${FORBIDDEN}")")" "2" \
    "merge блокирует по телу heredoc-подстановки: <<${delim}"
  assert_eq "$(merge_verdict "$(body_form "$delim" "$term" "обычный отчёт")")" "0" \
    "merge пропускает heredoc-подстановку с безобидным телом: <<${delim}"
done

# --- 5. Легитимные heredoc без публикации → ноль блокировок -------------------

assert_eq "$(merge_verdict "$(printf 'cat <<\\EOF\nsome data\nEOF')")" "0" \
  "легитимный <<\\EOF без публикации не блокируется"
assert_eq "$(merge_verdict "$(printf 'cat <<"END"\nline\nEND')")" "0" \
  "легитимный <<\"END\" без публикации не блокируется"

# --- 6. Мутация: узкий разбор разделителя возвращает ложный блок ---------------
# Если вернуть разбор только через узкий regex вместо общего парсера, статические
# смешанно-кавычённые разделители снова ложно блокируются.

MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$MUT_DIR/"
"$PYTHON_RUNNER" - "$MUT_DIR/shell_comment_parser.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
needle = "        delimiter, end, quoted, exact = shell_grammar.read_heredoc_word(\n            self.source, position\n        )"
if needle not in t:
    raise SystemExit("точка мутации не найдена")
replacement = (
    "        import re as _re\n"
    "        _m = _re.match(r\"'(?P<t>[A-Za-z_][A-Za-z0-9_]*)'\", self.source[position:])\n"
    "        if not _m:\n"
    "            raise _LexError()\n"
    "        delimiter = _m.group('t'); end = position + _m.end(); quoted = True; exact = True"
)
p.write_text(t.replace(needle, replacement, 1), encoding="utf-8")
PYX
mut_merge() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MUT_DIR/check-merge-ready.py" >/dev/null 2>&1
  printf '%s\n' "$?"
}
assert_eq "$(mut_merge "$(heredoc_then '\EOF' EOF "'обычный отчёт'")")" "2" \
  "мутация: узкий разбор разделителя ложно блокирует <<\\EOF с безобидным телом"
assert_eq "$(merge_verdict "$(heredoc_then '\EOF' EOF "'обычный отчёт'")")" "0" \
  "контроль: общий разбор разделителя не блокирует легитим <<\\EOF"
rm -rf "$MUT_DIR"

finish
