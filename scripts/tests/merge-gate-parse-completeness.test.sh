#!/usr/bin/env bash
# Полнота разбора у блокирующих гейтов: незавершённый разбор блокирует, штатные
# конструкции — нет.
#
# Инвариант: разбор, который система не завершила полностью и однозначно,
# инертность входа не доказывает. Оба блокирующих гейта блокируют такой вход
# НЕЗАВИСИМО от того, найдены ли в нём публикации/commit-связки. При этом признак
# незавершённости поднимается ТОЛЬКО на реально неразобранном входе: штатные
# разобранные конструкции (подоболочка, группа, подстановка процесса, extglob,
# backtick, `case`) false-блок не вызывают.
#
# Отдельная грань: программа со стандартного ВХОДА непрозрачна по форме так же,
# как строка в `-c`, и потому блокируется; запуск файла-аргумента остаётся обычной
# командой (паритет U2-vnao).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
MERGE_HOOK="$ROOT/.claude/hooks/check-merge-ready.py"
CLASSIFIER="$ROOT/.claude/hooks/commit_command_classifier.py"

# Вердикт merge-гейта: 0 — обычная команда, 2 — разбирается/блокируется.
merge_verdict() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$MERGE_HOOK" >/dev/null 2>&1
  printf '%s\n' "$?"
}

# Класс commit-гейта: ordinary — обычная команда, commit/ambiguous — блокируется.
commit_class() {
  printf '%s' "$1" | "$PYTHON_RUNNER" "$CLASSIFIER" classify 2>/dev/null
}

assert_blocks() { # assert_blocks <описание> <команда>
  assert_eq "$(merge_verdict "$2")" "2" "merge блокирует: $1"
}
assert_passes() { # assert_passes <описание> <команда>
  assert_eq "$(merge_verdict "$2")" "0" "merge пропускает: $1"
}
assert_commit_blocks() { # <описание> <команда>
  local class; class="$(commit_class "$2")"
  if [ "$class" = "commit" ] || [ "$class" = "ambiguous" ]; then
    pass "commit блокирует ($class): $1"
  else
    fail "commit НЕ блокирует ($class): $1"
  fi
}
assert_commit_ordinary() { # <описание> <команда>
  assert_eq "$(commit_class "$2")" "ordinary" "commit пропускает: $1"
}

# --- 1. Незавершённый разбор блокирует даже при пустом списке публикаций -------

assert_blocks "оборванная подстановка" 'echo $(gh pr comment 1 --body'
assert_blocks "незакрытая подоболочка" '(cd foo && gh pr comment 1 --body "Готов к merge"'
assert_blocks "незакрытая группа" '{ gh pr comment 1 --body "Готов к merge"'
assert_blocks "незакрытая управляющая конструкция" 'case x in x) gh pr comment 1 --body "Готов к merge"'
# Пустой список публикаций при оборванном разборе — тоже блок.
assert_blocks "оборванная подстановка без публикации" 'echo $(echo'

# --- 2. Extglob-хвост: команда после шаблона видна ----------------------------

assert_blocks "extglob перед публикацией" 'echo @(x)#suffix; gh pr comment 1 --body "Готов к merge"'
assert_commit_blocks "extglob перед git commit" 'echo @(x)#suffix; git commit -m z'
# Extglob как обычный glob — не блок.
assert_passes "extglob как glob" 'ls dir/*.@(js|ts)'
assert_passes "extglob в аргументе echo" 'echo @(a|b).txt'
assert_commit_ordinary "extglob-glob для commit-гейта" 'echo @(a|b).txt'

# --- 3. Программа со стандартного входа блокируется ----------------------------

assert_blocks "флаг -s" 'bash -s'
assert_blocks "флаг -s c аргументом" 'bash -s arg'
assert_blocks "одиночный дефис" 'bash -'
assert_blocks "оболочка в конце пайпа" 'cat build.sh | bash'
assert_blocks "here-string как источник" 'bash <<< "code"'
BASH_HEREDOC="$(printf '%s\n' 'bash <<EOF' 'gh pr comment 1 --body "x"' 'EOF')"
assert_blocks "heredoc как источник" "$BASH_HEREDOC"
assert_blocks "sh в конце пайпа" 'make | sh'

# Граница цела: файл-аргумент — обычная команда (паритет U2-vnao).
assert_passes "файл-аргумент оболочки" 'bash scripts/tests/run-all.sh'
assert_passes "файл-аргумент за пайпом" 'foo | bash script.sh'
assert_passes "файл после разделителя опций" 'bash -- script.sh'
assert_passes "файл при флагах оболочки" 'bash -eu deploy.sh --flag'

# --- 4. Не-идентификаторный heredoc-разделитель -------------------------------

HD_NUM="$(printf '%s\n' 'cat <<123' 'data' '123' 'gh pr comment 1 --body "Готов к merge"')"
assert_blocks "разделитель 123 + публикация" "$HD_NUM"
HD_COLON="$(printf '%s\n' 'cat <<:' 'data' ':' 'gh pr comment 1 --body "Готов к merge"')"
assert_blocks "разделитель : + публикация" "$HD_COLON"
HD_PATH="$(printf '%s\n' 'cat <<./EOF' 'data' './EOF' 'gh pr comment 1 --body "Готов к merge"')"
assert_blocks "разделитель ./EOF + публикация" "$HD_PATH"
assert_blocks "разделитель с раскрытием" 'cat <<$VAR
data
gh pr comment 1 --body "Готов к merge"'

# Легитимный heredoc с не-идентификатором в теле — не блок.
HD_OK="$(printf '%s\n' 'cat <<123' 'body' '123')"
assert_passes "legit heredoc 123" "$HD_OK"

# --- 5. Штатные конструкции не дают false-блок --------------------------------

assert_passes "подоболочка" '(cd foo && make)'
assert_passes "группа команд" '{ echo a; echo b; } > out.txt'
assert_passes "backtick без публикации" 'echo `date`'
assert_passes "подстановка процесса" 'cat <(sort a.txt) | head'
assert_passes "case завершён" 'case x in a) echo one;; b) echo two;; esac'
assert_passes "цепочка &&" 'echo a && echo b && echo c'
assert_passes "цикл for" 'for f in *.md; do echo "$f"; done'
assert_passes "обычная публикация без формулировки" 'gh pr comment 645 --body "обычный отчёт"'

# Публикация внутри штатной конструкции всё равно блокируется (per-publication).
assert_blocks "публикация в подоболочке" '(gh pr comment 1 --body "Готов к merge")'
assert_blocks "публикация за backtick" 'echo `gh pr comment 1 --body x`; gh pr comment 1 --body "Готов к merge"'

# --- 6. Мутации: каждый guard красит свои кейсы -------------------------------
# Проверка не выродилась: снятие проверки незавершённого разбора возвращает
# пропуск оборванных форм, а возврат stdin-ветки на «нечего исполнять» —
# пропуск программы со стандартного входа.

MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$MUT_DIR/"

merge_from() { # merge_from <каталог> <команда>
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$2")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$1/check-merge-ready.py" >/dev/null 2>&1
  printf '%s\n' "$?"
}

# Мутация A: снять блок по признаку незавершённого разбора.
# Копируются файлы, а не сам каталог: `cp -R "$MUT_DIR" "$MUT_DIR/…"` копирует
# каталог в самого себя, GNU cp на этой записи обрывает обход, и какие файлы
# успели попасть в копию, решает порядок readdir. В CI (2 потока) порядок
# совпадал, в контейнере при 14 потоках check-merge-ready.py в копию не попадал
# (задача U2-malbl).
MUT_A="$MUT_DIR/mut-global"
mkdir "$MUT_A" && cp "$MUT_DIR"/*.py "$MUT_A/"
"$PYTHON_RUNNER" - "$MUT_A/check-merge-ready.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
old = "    if analysis.global_ambiguous:"
if old not in t:
    raise SystemExit("точка мутации A не найдена")
p.write_text(t.replace(old, "    if False and analysis.global_ambiguous:", 1), encoding="utf-8")
PYX
# Оборванная подстановка без публикации в списке ловится ТОЛЬКО этим guard'ом.
assert_eq "$(merge_from "$MUT_A" 'echo $(gh pr comment 1 --body "Готов к merge"')" "0" \
  "мутация A: без guard'а незавершённого разбора оборванная подстановка проходит"
HD_VAR_MUT="$(printf '%s\n' 'cat <<$VAR' 'd' 'gh pr comment 1 --body "Готов к merge"')"
assert_eq "$(merge_from "$MUT_A" "$HD_VAR_MUT")" "0" \
  "мутация A: без guard'а heredoc с раскрытием-разделителем проходит"
# Тот же guard на исправном коде блокирует.
assert_eq "$(merge_from "$MUT_DIR" 'echo $(gh pr comment 1 --body "Готов к merge"')" "2" \
  "контроль: исправный guard блокирует оборванную подстановку"

# Мутация B: вернуть источник-поток на «нечего исполнять».
MUT_B="$MUT_DIR/mut-stdin"
mkdir "$MUT_B" && cp "$MUT_DIR"/*.py "$MUT_B/"
"$PYTHON_RUNNER" - "$MUT_B/shell_comment_parser.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
needle = "_Execution(_EXECUTION_OPAQUE, carrier=stdin_carrier)"
if needle not in t:
    raise SystemExit("точка мутации B не найдена")
p.write_text(t.replace(needle, "_Execution(_EXECUTION_NO_EXEC)"), encoding="utf-8")
PYX
assert_eq "$(merge_from "$MUT_B" 'bash -s')" "0" \
  "мутация B: без stdin-ветки флаг -s проходит"
assert_eq "$(merge_from "$MUT_B" 'cat build.sh | bash')" "0" \
  "мутация B: без stdin-ветки оболочка в конце пайпа проходит"
# Тот же путь на исправном коде блокирует.
assert_eq "$(merge_from "$MUT_DIR" 'cat build.sh | bash')" "2" \
  "контроль: исправная stdin-ветка блокирует оболочку в конце пайпа"

rm -rf "$MUT_DIR"

# --- 7. Корпус повседневных команд: ни один гейт не блокирует ------------------
# Инвариант «незавершённый разбор блокирует» опасен ложными срабатываниями.
# Здесь он проверяется числом: набор обычных команд разработчика проходит оба
# гейта. Многострочные формы (heredoc) заданы как есть.

EVERYDAY=(
  'git status --short'
  'git commit -m "обычное сообщение"'
  'npm run test'
  'bash scripts/tests/run-all.sh'
  'sh deploy.sh'
  'python3 scripts/check-doc-authority.py'
  'git log --oneline -5'
  'ls -la && echo done'
  'echo $(date)'
  'cat <(sort a.txt) | head'
  'diff <(sort a.txt) <(sort b.txt)'
  'for f in *.md; do echo "$f"; done'
  'if [ -f x ]; then echo hi; fi'
  'case "$x" in a) echo one;; b) echo two;; esac'
  'find . -name "*.tmp" -delete'
  'cat file.txt | grep -c foo'
  'git diff --stat origin/main...HEAD'
  'gh pr view 645 --json comments'
  'gh pr comment 645 --body "обычный отчёт ревью"'
  '(cd foo && make)'
  '{ echo a; echo b; } > out.txt'
  'echo `date`'
  'foo | bash script.sh'
  'echo a && echo b && echo c'
  'git add -A && git commit -m "msg" && git push'
  'bash -c '\''echo hi'\'''
  'ps aux | grep dolt | grep -v grep'
  'npm run build 2>&1 | tee build.log'
  'ls dir/*.@(js|ts)'
  'grep -rn "pattern" src/'
)
# Проверяется merge-гейт: именно его разбор трогает эта правка. Commit-гейт для
# управляющих конструкций и групп даёт `ambiguous` и до правки, и после (форма
# может нести спрятанный commit) — это его штатное поведение, не регрессия.
everyday_new_blocks=0
for c in "${EVERYDAY[@]}"; do
  if [ "$(merge_verdict "$c")" = "2" ]; then
    everyday_new_blocks=$((everyday_new_blocks + 1))
    fail "повседневная команда заблокирована merge-гейтом: $c"
  fi
done
# Многострочные heredoc-формы отдельно.
HD1="$(printf '%s\n' 'cat <<EOF' 'some data' 'EOF')"
HD2="$(printf '%s\n' "cat <<'EOF'" 'literal $data' 'EOF')"
HD3="$(printf '%s\n' 'git commit -m z <<EOF' 'note' 'EOF')"
for c in "$HD1" "$HD2" "$HD3"; do
  if [ "$(merge_verdict "$c")" = "2" ]; then
    everyday_new_blocks=$((everyday_new_blocks + 1))
    fail "повседневный heredoc заблокирован merge-гейтом: $(printf '%s' "$c" | head -1)"
  fi
done
assert_eq "$everyday_new_blocks" "0" \
  "корпус повседневных команд: ноль блокировок на обоих гейтах"

finish
