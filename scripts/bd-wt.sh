#!/usr/bin/env bash
# Обёртка bd для git-worktree: сама подставляет --db основного checkout.
#
# В worktree прямой bd с auto-discovery создаёт пустую базу и рвёт синхронизацию
# (см. .claude/rules/beads.md, правила проекта .claude/rules/beads.md). Обёртка подключает bd к живому
# dolt-серверу основного checkout через явный --db. Из основного checkout —
# прозрачный pass-through без --db. ИСКЛЮЧЕНИЕ (в любом окружении): export/import/dolt
# и пользовательский --db отклоняются (их канон — только sync-скрипты из основного дерева).
#
# Usage: scripts/bd-wt.sh <bd-команда, кроме export/import/dolt>  (BD_BIN=... — стаб для тестов)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/bd-env.sh
. "${SCRIPT_DIR}/lib/bd-env.sh"

BD_BIN="${BD_BIN:-bd}"

# Глобальные флаги bd (allowlist из `bd --help`). Со значением в СЛЕДУЮЩЕМ токене:
GLOBAL_VALUE_FLAGS=" --db --actor --dolt-auto-commit "
# Булевы (значение не потребляют):
GLOBAL_BOOL_FLAGS=" --global --json --profile --quiet -q --readonly --sandbox --verbose -v --help -h --version -V "
is_value_flag() { case "$GLOBAL_VALUE_FLAGS" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
is_bool_flag()  { case "$GLOBAL_BOOL_FLAGS"  in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# Печатает подкоманду bd, пропустив ТОЛЬКО известные глобальные флаги. Неизвестный
# флаг до подкоманды → печатает '__UNKNOWN__' (fail-closed): иначе нераспознанный
# value-флаг мог бы съесть подкоманду и пропустить запрещённые export/import/dolt.
find_subcommand() {
  local skip=0 a name
  while [ $# -gt 0 ]; do
    a="$1"; shift
    if [ "$skip" = "1" ]; then skip=0; continue; fi
    case "$a" in
      --) [ $# -gt 0 ] && printf '%s' "$1"; return 0 ;;
      --*=*) name="${a%%=*}"
             if is_value_flag "$name" || is_bool_flag "$name"; then continue; fi
             printf '__UNKNOWN__'; return 0 ;;
      -*) if is_value_flag "$a"; then skip=1; continue; fi
          if is_bool_flag "$a"; then continue; fi
          printf '__UNKNOWN__'; return 0 ;;
      *) printf '%s' "$a"; return 0 ;;
    esac
  done
  return 1
}

# Отказ оборачивать export/import/dolt (канон — только из основного checkout через
# scripts/bd-sync-*.sh) + fail-closed на нераспознанном глобальном флаге.
sub="$(find_subcommand "$@" || true)"
case "$sub" in
  __UNKNOWN__)
    echo "ERROR: неизвестный глобальный флаг bd до подкоманды — bd-wt не может безопасно" >&2
    echo "       определить команду (fail-closed). Легитимный флаг — добавь в allowlist bd-wt.sh." >&2
    exit 2 ;;
  export|import|dolt)
    echo "ERROR: '${sub}' нельзя через bd-wt." >&2
    echo "       Синхронизацию beads делать из основного checkout:" >&2
    echo "       scripts/bd-sync-export.sh / scripts/bd-sync-restore.sh (правила проекта .claude/rules/beads.md)." >&2
    exit 2 ;;
esac

# Не передавать --db в bd-wt: обёртка подставляет его сама, а пользовательский --db
# переопределил бы основную базу (в pflag выигрывает последний --db) — обход гарантии.
for a in "$@"; do
  case "$a" in --db|--db=*) echo "ERROR: не передавайте --db в bd-wt — обёртка ставит его сама." >&2; exit 2 ;; esac
done

# Не git-репозиторий / bare — нет контекста для вычисления базы.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: не git-репозиторий — нет контекста для .beads/dolt." >&2
  exit 1
fi
if [ "$(git rev-parse --is-bare-repository 2>/dev/null)" = "true" ]; then
  echo "ERROR: bare-репозиторий не поддерживается." >&2
  exit 1
fi

# Основной checkout — auto-discovery корректен, прозрачно пропускаем без --db.
if bd_env_is_main_checkout; then
  exec "$BD_BIN" "$@"
fi

# Worktree: вычисляем и валидируем путь основной базы, проверяем живой сервер.
db="$(bd_env_main_db)" || exit 1     # печатает ошибку с путём
main_root="$(bd_env_main_root)"
if ! bd_env_dolt_alive "$main_root"; then
  echo "ERROR: dolt-сервер основного checkout не запущен ($main_root)." >&2
  echo "       --db подключается к живому серверу, а не поднимает второй." >&2
  echo "       Прогрейте bd любой командой из основного checkout и повторите." >&2
  exit 3
fi

exec "$BD_BIN" --db "$db" "$@"
