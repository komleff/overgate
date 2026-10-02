#!/usr/bin/env bash
# Засев синтетического дерева для тестов диспетчера PreToolUse(Bash).
#
# seed_claude_hooks <дерево> [исключение …]
#   Кладёт в <дерево>/.claude/hooks и <дерево>/.claude/tools ссылки на ВСЕ файлы
#   настоящего checkout, кроме названных по имени. Диспетчер требует все четыре
#   проверки, launcher и помощник времени; тест, проверяющий одну из них, засевает
#   остальные отсюда и подменяет или удаляет только своё.
#
# Корень настоящего checkout — каталог этого файла; переопределяется переменной
# SEED_CLAUDE_HOOKS_ROOT (для тестов самого помощника).
seed_claude_hooks() {
  local tree="$1"
  shift
  local source_root="${SEED_CLAUDE_HOOKS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
  local file name excluded sub
  mkdir -p "$tree/.claude/hooks" "$tree/.claude/tools" || return 1
  for sub in hooks tools; do
    for file in "$source_root/.claude/$sub"/*; do
      [ -f "$file" ] || continue
      name="$(basename "$file")"
      excluded=0
      for skip in "$@"; do
        [ "$skip" = "$name" ] && excluded=1
      done
      [ "$excluded" -eq 1 ] && continue
      ln -s "$file" "$tree/.claude/$sub/$name" || return 1
    done
  done
}
