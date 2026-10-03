#!/usr/bin/env bash
# Правило «где начинается слово и где комментарий» — ОДНО на пакет.
#
# Причина существования: правило жило двумя копиями. У разборщика публикаций
# набор метасимметалов был `;|&(){}`, у классификатора коммитов — `;&|()<>`.
# Оболочка согласна со вторым: закрывающая фигурная скобка границей слова НЕ
# является. Из-за расхождения гейт публикации считал остаток строки после `}#`
# комментарием и пропускал публикацию, которую живой bash ИСПОЛНЯЕТ.
# Каждый прошлый раунд правил одну копию, поэтому здесь проверяется не значение
# набора, а единственность источника. Равенства наборов для этого мало: копия
# функции расходилась с копией набора отдельно. Поэтому проверяется ИМПОРТ —
# предикат обоих разборщиков обязан быть ТЕМ ЖЕ объектом, что в общем модуле,
# а собственных копий набора и функции у них быть не должно.
#
# Вторая половина — поведение относительно ЖИВОГО bash: для каждой формы
# запускается настоящий bash со стендовым `gh`, и вердикт гейта сверяется с тем,
# исполнил ли bash публикацию. Расхождение «bash исполнил, гейт пропустил» —
# провал; «bash не исполнил, гейт заблокировал» — допустимая перестраховка.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
HOOK="$ROOT/.claude/hooks/check-merge-ready.py"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# --- 1. Единственность источника ----------------------------------------------

SETS_OUT="$("$PYTHON_RUNNER" - "$ROOT" <<'PYX'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
hooks = root / ".claude" / "hooks"
sys.path.insert(0, str(hooks))

import shell_grammar
import commit_command_classifier as classifier
import shell_comment_parser as parser

# ЕДИНСТВЕННОСТЬ ОБЪЕКТА, а не совпадение значений. Копии расходились именно
# потому, что сверялось значение: одинаковый набор при разошедшихся функциях
# по-прежнему давал два разных ответа на один вопрос.
print("CLASSIFIER_IMPORTS" if classifier.shell_grammar is shell_grammar else "CLASSIFIER_OWN")
print("PARSER_IMPORTS" if parser.shell_grammar is shell_grammar else "PARSER_OWN")
print(
    "PREDICATE_SHARED"
    if parser.is_comment_start is shell_grammar.is_comment_start
    else "PREDICATE_FORKED"
)
# Нормализация продолжения строки — тоже из общего источника: у гейта коммита
# это ТОТ ЖЕ объект, что в общем модуле. Иначе класс «перенос строки распадается
# на две команды» был бы закрыт на одном гейте из двух.
print(
    "SPLICE_SHARED"
    if classifier._splice_line_continuations is shell_grammar.splice_line_continuations
    else "SPLICE_FORKED"
)
print(
    "HEREDOC_SHARED"
    if classifier._heredoc_spans is shell_grammar.heredoc_spans
    else "HEREDOC_FORKED"
)

# Собственных копий набора у разборщиков быть не должно ни в коде, ни в тексте.
for name, module_path in (
    ("classifier", hooks / "commit_command_classifier.py"),
    ("parser", hooks / "shell_comment_parser.py"),
):
    text = module_path.read_text(encoding="utf-8")
    # Копия — это ПРИСВАИВАНИЕ набора строковым литералом. Производные наборы
    # (например граница групп, собранная из общего) копией не являются: они
    # ломаются вместе с источником, а не живут своей жизнью.
    literal_copies = [
        line
        for line in text.splitlines()
        if re.search(
            r"COMMENT_START_METACHARACTERS\s*=\s*(?:frozen)?set\(\s*[\"']", line
        )
    ]
    print(f"{name.upper()}_NO_LITERAL_SET" if not literal_copies else f"{name.upper()}_LITERAL_SET {literal_copies}")

# У разборщика публикаций КАЖДОЕ решение «это начало комментария» обязано звать
# общее правило. Строка вида `visible[position] == 0 and char == "#"` решения НЕ
# принимает: она читает готовый вердикт лексера из карты видимости.
parser_text = (hooks / "shell_comment_parser.py").read_text(encoding="utf-8")
hash_lines = [
    line.strip()
    for line in parser_text.splitlines()
    if 'char == "#"' in line or "char == '#'" in line
]
undelegated = [
    line
    for line in hash_lines
    if "is_comment_start" not in line and "visible[" not in line
]
print("HASH_SITES", len(hash_lines))
print("DELEGATED" if hash_lines and not undelegated else f"OWN_RULE {undelegated}")

# Граница групп `(`/`{` — смежный вопрос, но она обязана быть НАДМНОЖЕСТВОМ
# общего набора, а не третьей независимой копией: иначе наборы снова разъедутся.
group = set(parser._GROUP_BOUNDARY_CHARACTERS)
shared = set(shell_grammar.COMMENT_START_METACHARACTERS)
print("GROUP_SUPERSET" if shared <= group else f"GROUP_DRIFT {sorted(group)}")
PYX
)"
SETS_RC=$?
assert_eq "$SETS_RC" "0" "оба разборщика загружаются вместе с общим модулем"
assert_contains "$SETS_OUT" "CLASSIFIER_IMPORTS" \
  "классификатор коммитов импортирует общий модуль правила"
assert_contains "$SETS_OUT" "PARSER_IMPORTS" \
  "разборщик публикаций импортирует общий модуль правила"
assert_contains "$SETS_OUT" "PREDICATE_SHARED" \
  "предикат начала комментария у разборщика — тот же объект, что в общем модуле"
assert_contains "$SETS_OUT" "SPLICE_SHARED" \
  "нормализация продолжения строки у commit-гейта — тот же объект, что в общем модуле"
assert_contains "$SETS_OUT" "HEREDOC_SHARED" \
  "сканер тел heredoc у commit-гейта — тот же объект, что в общем модуле"
assert_contains "$SETS_OUT" "CLASSIFIER_NO_LITERAL_SET" \
  "у классификатора нет собственной литеральной копии набора метасимволов"
assert_contains "$SETS_OUT" "PARSER_NO_LITERAL_SET" \
  "у разборщика публикаций нет собственной литеральной копии набора метасимволов"
assert_contains "$SETS_OUT" "DELEGATED" \
  "каждое решение о начале комментария в разборщике делегировано общему правилу"
assert_not_contains "$SETS_OUT" "HASH_SITES 0" \
  "мест принятия решения о комментарии не ноль (проверка не выродилась)"
assert_contains "$SETS_OUT" "GROUP_SUPERSET" \
  "граница групп выведена из общего набора, а не написана третьей копией"

# --- 2. Поведение против живого bash -------------------------------------------

STUB_BIN="$TMP_DIR/bin"
mkdir -p "$STUB_BIN"
printf '%s\n' '#!/bin/sh' 'printf "GH-EXECUTED\n" >> "$GH_MARKER"' 'exit 0' > "$STUB_BIN/gh"
chmod +x "$STUB_BIN/gh"
GH_MARKER="$TMP_DIR/gh-called"
export GH_MARKER

# Возвращает "yes"/"no": исполнил ли настоящий bash стендовый `gh`.
bash_executes_gh() {
  : > "$GH_MARKER"
  PATH="$STUB_BIN:$PATH" bash -c "$1" >/dev/null 2>&1
  if [ -s "$GH_MARKER" ]; then printf 'yes\n'; else printf 'no\n'; fi
}

gate_verdict() {
  local payload
  payload="$("$PYTHON_RUNNER" -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1")"
  printf '%s' "$payload" | env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$HOOK" >/dev/null 2>&1
  printf '%s\n' "$?"
}

# Каждая форма проверяется дважды: с безобидным телом (bash-эталон) и с
# запрещённой формулировкой (вердикт гейта).
check_form() { # check_form <описание> <команда-с-телом-b>
  local title="$1" probe="$2" armed verdict executed
  armed="${probe//--body \"b\"/--body \"Готов к merge\"}"
  executed="$(bash_executes_gh "$probe")"
  verdict="$(gate_verdict "$armed")"
  if [ "$executed" = "yes" ]; then
    assert_eq "$verdict" "2" "$title: bash публикует → гейт блокирует"
  elif [ "$verdict" = "0" ] || [ "$verdict" = "2" ]; then
    pass "$title: bash не публикует → гейт не пропускает лишнего (код $verdict)"
  else
    fail "$title: неожиданный код гейта $verdict"
  fi
}

# ПОЛОЖИТЕЛЬНЫЙ случай дефекта: решётка после `}` комментария НЕ открывает,
# публикация за `;` реальна — и обязана блокироваться.
check_form "решётка после закрывающей фигурной скобки" \
  'echo ${x}#y; gh pr comment 645 --body "b"'

# Тот же класс, круглая скобка. Она МНОГОЗНАЧНА: закрывающая скобка подстановки
# оставляет слово открытым (решётка за ней комментария не начинает), а
# закрывающая скобка подоболочки командой заканчивает. Прежнее правило видело
# только символ и гасило исполняемый остаток строки вместе с публикацией.
check_form "решётка после закрытия подстановки команды" \
  'echo $(echo hi)#y; gh pr comment 645 --body "b"'
check_form "решётка после закрытия арифметической подстановки" \
  'echo $((1+1))#y; gh pr comment 645 --body "b"'
check_form "решётка после закрытия подстановки процесса" \
  'cat <(echo hi)#y; gh pr comment 645 --body "b"'
check_form "решётка после закрытия подстановки в присваивании" \
  'x=$(echo hi)#y; gh pr comment 645 --body "b"'

# Носитель с подкомандой в кавычках: буквального образца в тексте нет, а
# оболочка публикацию исполняет. Разбор обязан идти по недоказанности
# инертности, а не по совпадению позитивного образца.
check_form "носитель с подкомандой в кавычках" \
  $'eval \'gh pr "comment" 645 --body "b"\''
check_form "носитель с именем инструмента в кавычках" \
  $'eval \'gh "pr" comment 645 --body "b"\''

# Он же в чистом виде: без чужого префикса гейт обязан блокировать всегда.
assert_eq "$(gate_verdict 'gh pr comment 645 --body "Готов к merge"')" "2" \
  "контроль без префикса: обычная публикация блокируется"

# ОТРИЦАТЕЛЬНЫЕ случаи: формы, где решётка ДЕЙСТВИТЕЛЬНО открывает комментарий,
# обязаны остаться инертными — иначе правило перекошено в другую сторону и
# обычная работа встанет.
INERT_FORMS=(
  'начало строки:# gh pr comment 645 --body "b"'
  'после пробела:echo hi #gh pr comment 645 --body "b"'
  'после точки с запятой:echo hi;#gh pr comment 645 --body "b"'
  'после двойного амперсанда:echo hi &&#gh pr comment 645 --body "b"'
  'после двойной вертикали:echo hi ||#gh pr comment 645 --body "b"'
  'после вертикали:echo hi |#gh pr comment 645 --body "b"'
  'после закрывающей круглой скобки:(echo hi)#gh pr comment 645 --body "b"'
)
for form in "${INERT_FORMS[@]}"; do
  title="${form%%:*}"
  probe="${form#*:}"
  assert_eq "$(bash_executes_gh "$probe")" "no" \
    "эталон живого bash: комментарий $title гасит публикацию"
  assert_eq "$(gate_verdict "${probe//--body \"b\"/--body \"Готов к merge\"}")" "0" \
    "гейт: комментарий $title остаётся инертным"
done

# Штатная работа не задета: обычная публикация без запрещённой формулировки
# проходит и инлайн, и через heredoc с квотированным делимитером.
assert_eq "$(gate_verdict "gh pr comment 645 --body 'обычный отчёт ревью'")" "0" \
  "легитимная инлайн-публикация проходит"
HEREDOC_FORM="$(printf '%s\n' "gh pr comment 645 --body \"\$(cat <<'GH_BODY_7f31a2c4'" 'обычный отчёт ревью' 'GH_BODY_7f31a2c4' ')"')"
assert_eq "$(gate_verdict "$HEREDOC_FORM")" "0" \
  "легитимная публикация через heredoc проходит"

finish
