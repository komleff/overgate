#!/usr/bin/env bash
# Замыкание разрешения имён модулей у обработчиков и инструментов.
#
# Инвариант, общий на пакет: имена модулей разрешаются только по стандартным
# путям интерпретатора, а соседние модули пакета грузятся по ЯВНОМУ пути файла.
# Рабочие каталоги (обработчиков и инструментов) в путях поиска не участвуют,
# поэтому решение программы зависит только от её собственных модулей.
#
# Второй инвариант — про отказ: если соседний модуль не загрузился, программа
# сообщает об этом и завершает работу по своему контракту, а не продолжает с
# неполным набором. У публикатора контракт — отказ в публикации; у информера
# петли ревью контракт — не блокировать команду, поэтому он выходит без записи
# состояния и печатает причину.
#
# Проверка ведётся в свежем интерпретаторе на КОПИИ дерева: рядом с модулями
# кладётся файл с именем модуля стандартной библиотеки, и сверяется, что решение
# программы прежнее. Мутационная половина показывает, что проверка не выродилась:
# на прежней версии тот же сосед решение менял.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"

PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Собрать рабочую копию дерева: обработчики, инструменты и сосед с именем модуля
# стандартной библиотеки. `revision` — какую версию файлов положить: `current`
# (рабочее дерево) либо git-ревизию для мутационной половины.
build_tree() { # build_tree <каталог> <revision> <файл-носитель…>
  local target="$1" revision="$2"
  shift 2
  mkdir -p "$target/.claude/hooks" "$target/.claude/tools"
  local name
  for name in "$ROOT"/.claude/hooks/*.py; do
    cp "$name" "$target/.claude/hooks/"
  done
  for name in "$ROOT"/.claude/tools/*.py "$ROOT"/.claude/tools/*.sh; do
    cp "$name" "$target/.claude/tools/"
  done
  if [ "$revision" != "current" ]; then
    local carrier
    for carrier in "$@"; do
      git -C "$ROOT" show "$revision:$carrier" > "$target/$carrier"
    done
  fi

  # Сосед с именем модуля стандартной библиотеки. Настоящий модуль так себя не
  # ведёт, поэтому любое изменение решения означало бы, что имя разрешилось не
  # по стандартным путям.
  local neighbour
  for neighbour in "$target/.claude/hooks" "$target/.claude/tools"; do
    printf '%s\n' \
      'def loads(*args, **kwargs):' \
      '    return {"tool_input": {"command": "echo сосед"}}' \
      'class JSONDecodeError(ValueError):' \
      '    pass' > "$neighbour/json.py"
    printf '%s\n' \
      'def compile(*args, **kwargs):' \
      '    raise RuntimeError("сосед")' \
      'def sub(pattern, repl, text, *args, **kwargs):' \
      '    return text' \
      'def search(*args, **kwargs):' \
      '    return None' \
      'def fullmatch(*args, **kwargs):' \
      '    return None' > "$neighbour/re.py"
  done
}

# --- 1. Публикатор: решение политики не зависит от соседа ----------------------
# Тело с формулировкой готовности без capability-token публиковаться не должно.
# Это и есть наблюдаемое решение политики: сверяем, что сосед его не меняет.

PUBLISHER_TREE="$TMP_DIR/publisher-current"
build_tree "$PUBLISHER_TREE" current

PUB_BIN="$TMP_DIR/pub-bin"
mkdir -p "$PUB_BIN"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$PUB_BIN/gh"
chmod +x "$PUB_BIN/gh"

# Публикатор принимает тело только из репозитория, поэтому копия дерева — сама
# репозиторий, и тело лежит в ней.
publisher_verdict() { # publisher_verdict <дерево> <текст тела>
  local tree="$1" body="$2"
  git -C "$tree" init -q 2>/dev/null || true
  printf '%s\n' "$body" > "$tree/body.md"
  ( cd "$tree" && PATH="$PUB_BIN:$PATH" env -u FINALIZE_PR_TOKEN \
      "$PYTHON_RUNNER" "$tree/.claude/tools/publish-pr-comment.py" 645 "$tree/body.md" \
      >/dev/null 2>&1 )
  printf '%s\n' "$?"
}

assert_eq "$(publisher_verdict "$PUBLISHER_TREE" '## ✅ Готов к merge')" "2" \
  "публикатор: модули грузятся по явному пути, решение политики прежнее"

# Обычное тело публикуется — проверка выше не выродилась в «всегда отказ».
assert_eq "$(publisher_verdict "$PUBLISHER_TREE" 'обычный отчёт ревью')" "0" \
  "публикатор: обычное тело публикуется при том же соседе"

# Мутационная половина: проверка обязана ловить снятие инварианта. Мутация — в
# самом файле копии, без опоры на историю репозитория: приведение путей поиска
# отключается, всё остальное остаётся прежним.
disable_path_closure() { # disable_path_closure <файл>
  "$PYTHON_RUNNER" - "$1" <<'PYX'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
marker = 'if __name__ == "__main__":\n    # Сверка идёт по разрешённым путям'
if marker not in text:
    raise SystemExit("мутация неприменима: приведение путей поиска не найдено")
path.write_text(
    text.replace(marker, 'if False:\n    # Сверка идёт по разрешённым путям', 1),
    encoding="utf-8",
)
PYX
}

PUBLISHER_MUT="$TMP_DIR/publisher-mutated"
build_tree "$PUBLISHER_MUT" current
if disable_path_closure "$PUBLISHER_MUT/.claude/tools/publish-pr-comment.py"; then
  MUT_VERDICT="$(publisher_verdict "$PUBLISHER_MUT" '## ✅ Готов к merge')"
  if [ "$MUT_VERDICT" = "2" ]; then
    fail "мутация публикатора: снятие инварианта обязано менять наблюдаемое поведение"
  else
    pass "мутация публикатора: без приведения путей поиска поведение иное (код $MUT_VERDICT)"
  fi
else
  fail "мутация публикатора не применилась — проверка выродилась"
fi

# --- 2. Shared mutation guard: stdlib neighbour не меняет policy ---------------
# Для guard оставляем подменный json.py, но снимаем подменный re.py: тогда без
# раннего исключения hook-dir json.loads() подменяет payload на безобидный
# `echo сосед` и опасная команда прошла бы. Пара dangerous/safe доказывает, что
# тест не выродился в «guard всегда блокирует».

GUARD_TREE="$TMP_DIR/repository-guard"
build_tree "$GUARD_TREE" current
rm -f "$GUARD_TREE/.claude/hooks/re.py"
DANGEROUS_PAYLOAD='{"tool_input":{"command":"gh pr merge 756 --squash"}}'
SAFE_PAYLOAD='{"tool_input":{"command":"git status --short"}}'
printf '%s' "$DANGEROUS_PAYLOAD" | \
  "$PYTHON_RUNNER" "$GUARD_TREE/.claude/hooks/check-repository-mutation.py" \
  >/dev/null 2>&1
assert_eq "$?" "2" "repository guard: соседний json.py не отключает блокировку merge"
printf '%s' "$SAFE_PAYLOAD" | \
  "$PYTHON_RUNNER" "$GUARD_TREE/.claude/hooks/check-repository-mutation.py" \
  >/dev/null 2>&1
assert_eq "$?" "0" "repository guard: при том же соседе безопасная команда проходит"

GUARD_MISSING="$TMP_DIR/repository-guard-missing"
build_tree "$GUARD_MISSING" current
rm -f "$GUARD_MISSING/.claude/hooks/commit_command_classifier.py"
GUARD_MISSING_OUT="$(printf '%s' "$SAFE_PAYLOAD" | \
  "$PYTHON_RUNNER" "$GUARD_MISSING/.claude/hooks/check-repository-mutation.py" 2>&1 >/dev/null)"
assert_eq "$?" "2" "repository guard: отсутствие sibling parser блокирует fail-secure"
assert_contains "$GUARD_MISSING_OUT" "parser package not loaded" \
  "repository guard: причина missing sibling видна"

# --- 3. Гейт публикации: тот же инвариант, тот же сосед ------------------------

GATE_TREE="$TMP_DIR/gate"
build_tree "$GATE_TREE" current
printf '%s' '{"tool_input":{"command":"gh pr comment 645 --body \"Готов к merge\""}}' | \
  env -u FINALIZE_PR_TOKEN "$PYTHON_RUNNER" "$GATE_TREE/.claude/hooks/check-merge-ready.py" \
  >/dev/null 2>&1
assert_eq "$?" "2" "гейт публикации: решение при том же соседе прежнее"

finish
