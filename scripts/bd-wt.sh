#!/usr/bin/env bash
# Единая точка входа локальных агентов в Beads: основной checkout и git-worktree.
#
# В worktree прямой bd с auto-discovery может создать пустую базу и разорвать синхронизацию
# (.claude/rules/beads.md, PIPELINE_ADR §3.7). Обёртка сама подставляет --db основной базы по
# dolt_mode из <main>/.beads/metadata.json: embedded → .beads/embeddeddolt, server →
# .beads/dolt и живой dolt-сервер. Из основного checkout — прозрачный pass-through без --db.
# В ЛЮБОМ окружении проходит только allowlist подкоманд: всё прочее — export/import/dolt,
# delete, config, sql и т.д. — отклоняется до запуска bd. Флаги --db, -C/--directory,
# --global, --ignore-schema-skew, --repo и флаги чтения локального файла отклоняются в любой
# позиции аргументов; заданные BEADS_DIR / BEADS_DB — тоже отказ. Это защитный слой обёртки,
# а не граница безопасности: прямой bd остаётся доступен в рамках прав сессии.
#
# Usage: bash scripts/bd-wt.sh <подкоманда из allowlist> [аргументы]  (BD_BIN=... — стаб для тестов)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/bd-env.sh
. "${SCRIPT_DIR}/lib/bd-env.sh"

BD_BIN="${BD_BIN:-bd}"

# BEADS_DIR / BEADS_DB переопределяют выбор базы самим bd: в основном checkout pass-through
# ушёл бы в другую базу, в worktree — спор с подставленным --db. Отказ во всех режимах.
for var in BEADS_DIR BEADS_DB; do
  if [ -n "${!var:-}" ]; then
    echo "ERROR: переменная окружения ${var} задана — bd-wt выбирает основную базу сам (fail-closed)." >&2
    echo "       Уберите её (unset ${var}) и повторите." >&2
    exit 2
  fi
done

# Флаги, переключающие базу или каталог bd, запрещены в ЛЮБОЙ позиции: cobra принимает
# persistent-флаги и после подкоманды (`list -C /other`). Сравнение по целым токенам, поэтому
# значение аргумента, точно равное такому флагу (`create --title -C`), тоже отклоняется —
# осознанный fail-closed. Короткий -C ловится и слитно (-C/x), и в связке (-qC).
# --repo (локальный флаг `create`) направляет запись в чужую базу или создаёт новую .beads
# вне синхронизации — тоже обход основной базы.
# Флаги чтения локального файла (--body-file и его скрытый в --help алиас --description-file
# у create/update, --design-file, --reason-file, --file, --graph, короткий -f, --metadata @путь)
# унесли бы содержимое произвольного файла в общую базу.
# Длинный текст — через --stdin или --description. Короткий -f ловится как -C.
prev=""
for a in "$@"; do
  case "$a" in
    --db|--db=*)
      echo "ERROR: не передавайте --db в bd-wt — обёртка ставит его сама." >&2
      exit 2 ;;
    --directory|--directory=*|--global|--global=*|--ignore-schema-skew|--ignore-schema-skew=*|--repo|--repo=*)
      echo "ERROR: флаг '${a}' нельзя через bd-wt — он меняет базу или каталог bd (fail-closed)." >&2
      exit 2 ;;
    --body-file|--body-file=*|--description-file|--description-file=*|--design-file|--design-file=*|--reason-file|--reason-file=*|--file|--file=*|--graph|--graph=*|--metadata=@*)
      echo "ERROR: флаг '${a}' нельзя через bd-wt — он читает локальный файл (fail-closed)." >&2
      echo "       Длинный текст передавайте через --stdin или --description." >&2
      exit 2 ;;
    @*)
      if [ "$prev" = "--metadata" ]; then
        echo "ERROR: --metadata с @файлом нельзя через bd-wt — он читает локальный файл (fail-closed)." >&2
        echo "       Передавайте JSON значением: --metadata '{\"k\":\"v\"}'." >&2
        exit 2
      fi ;;
    --*) ;;
    -*C*)
      echo "ERROR: короткий флаг -C (в '${a}') нельзя через bd-wt — он меняет каталог bd (fail-closed)." >&2
      exit 2 ;;
    -*f*)
      echo "ERROR: короткий флаг -f (в '${a}') нельзя через bd-wt — он читает локальный файл (fail-closed)." >&2
      echo "       Длинный текст передавайте через --stdin или --description." >&2
      exit 2 ;;
  esac
  prev="$a"
done

# Глобальные флаги bd (allowlist из `bd --help`), допустимые до подкоманды.
# Со значением в СЛЕДУЮЩЕМ токене:
GLOBAL_VALUE_FLAGS=" --actor --dolt-auto-commit "
# Булевы (значение не потребляют):
GLOBAL_BOOL_FLAGS=" --json --profile --quiet -q --readonly --sandbox --verbose -v --help -h --version -V "
is_value_flag() { case "$GLOBAL_VALUE_FLAGS" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
is_bool_flag()  { case "$GLOBAL_BOOL_FLAGS"  in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# Печатает подкоманду bd, пропустив ТОЛЬКО известные глобальные флаги. Неизвестный
# флаг до подкоманды → печатает '__UNKNOWN__' (fail-closed): иначе нераспознанный
# value-флаг мог бы съесть подкоманду и пропустить запрещённую.
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

sub="$(find_subcommand "$@" || true)"
case "$sub" in
  __UNKNOWN__)
    echo "ERROR: неизвестный глобальный флаг bd до подкоманды — bd-wt не может безопасно" >&2
    echo "       определить команду (fail-closed). Легитимный флаг — добавь в allowlist bd-wt.sh." >&2
    exit 2 ;;
  "")
    echo "ERROR: не указана подкоманда bd — bd-wt пропускает только allowlist (fail-closed)." >&2
    exit 2 ;;
  export|import|dolt)
    echo "ERROR: '${sub}' нельзя через bd-wt." >&2
    echo "       Синхронизацию beads делать из основного checkout:" >&2
    echo "       bash scripts/bd-sync-export.sh / bash scripts/bd-sync-restore.sh (.claude/rules/beads.md)." >&2
    exit 2 ;;
  # Allowlist подкоманд — точное совпадение целого токена.
  ready|show|list|search|blocked|children|create|q|update|close|reopen|dep|comment|comments|note|label) ;;
  *)
    echo "ERROR: подкоманда '${sub}' не входит в allowlist bd-wt (fail-closed)." >&2
    echo "       Разрешены: ready show list search blocked children create q update close reopen" >&2
    echo "       dep comment comments note label. Прочее — только оператор (.claude/rules/beads.md)." >&2
    exit 2 ;;
esac

# Не git-репозиторий / bare — нет контекста для вычисления базы.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: не git-репозиторий — нет контекста для основной базы Beads." >&2
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

# Worktree: база по dolt_mode основного checkout; для server — проверка живого сервера.
main_root="$(bd_env_main_root)"
db_rc=0
bd_env_resolve_main_db "$main_root" || db_rc=$?
case "$db_rc" in
  0) ;;
  3)
    echo "ERROR: dolt-сервер основного checkout не запущен (${main_root})." >&2
    echo "       --db подключается к живому серверу, а не поднимает второй." >&2
    echo "       Прогрейте bd любой командой из основного checkout и повторите." >&2
    exit 3 ;;
  *) exit 1 ;;     # причина с путём уже в stderr
esac

exec "$BD_BIN" --db "$BD_ENV_DB_PATH" "$@"
