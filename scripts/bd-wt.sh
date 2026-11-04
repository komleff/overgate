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

# После регистрации managed publisher прямой bd из основного/linked checkout не
# меняет task state: опубликованный snapshot читается отдельно, запись — typed queue.
if git config --local --get overgate.beadsPublisher >/dev/null 2>&1; then
  case "$sub" in
    ready|show|list)
      if [ "${1:-}" != "$sub" ]; then
        echo "ERROR: managed read запускай без префиксных bd flags: bash scripts/bd-read.sh ${sub}." >&2
        exit 2
      fi
      exec bash "${SCRIPT_DIR}/bd-read.sh" "$@" ;;
    *)
      echo "ERROR: managed publisher активен; прямой bd-wt write запрещён. Подготовь typed queue и публикуй из trusted main publisher." >&2
      exit 2 ;;
  esac
fi

# Незарегистрированный clone тоже может видеть managed remote: legacy bd-wt не должен
# менять локальный Dolt до проверки опубликованного protocol/history.
remote_mode() {
  local rc=0 shallow tip markers prior
  git ls-remote --exit-code --heads origin refs/heads/beads-backup >/dev/null 2>&1 || rc=$?
  case "$rc" in
    2)
      if git show-ref --verify --quiet refs/remotes/origin/beads-backup \
        || git show-ref --verify --quiet refs/overgate-bd-managed/last-seen; then
        printf 'unknown'; return
      fi
      printf 'legacy'; return ;;
    0) ;;
    *) printf 'unknown'; return ;;
  esac
  shallow="$(git rev-parse --is-shallow-repository 2>/dev/null)" || { printf 'unknown'; return; }
  if [ "$shallow" != false ] || ! git fetch -q origin "$BD_BACKUP_REFSPEC"; then
    printf 'unknown'; return
  fi
  tip="$(git rev-parse --verify 'refs/remotes/origin/beads-backup^{commit}' 2>/dev/null)" || { printf 'unknown'; return; }
  markers="$(git ls-tree -r --name-only "$tip" -- .beads/overgate-managed-v1.json .beads/overgate-outcomes-v1.json)" || { printf 'unknown'; return; }
  if [ -n "$markers" ]; then printf 'managed'; return; fi
  prior="$(git log -1 --format=%H "$tip" -- .beads/overgate-managed-v1.json .beads/overgate-outcomes-v1.json)" || { printf 'unknown'; return; }
  if [ -n "$prior" ]; then printf 'managed'; else printf 'legacy'; fi
}
published_mode="$(remote_mode)"
case "$published_mode" in
  managed)
    case "$sub" in
      ready|show|list)
        if [ "${1:-}" = "$sub" ]; then exec bash "${SCRIPT_DIR}/bd-read.sh" "$@"; fi ;;
    esac
    echo "ERROR: remote managed protocol активен; прямой bd-wt write запрещён. Используй trusted typed queue publisher." >&2
    exit 2 ;;
  unknown)
    case "$sub" in
      ready|show|list)
        if [ "${1:-}" = "$sub" ]; then exec bash "${SCRIPT_DIR}/bd-read.sh" "$@"; fi ;;
    esac
    echo "ERROR: remote task state недоступен или неизвестен; bd-wt mutation остановлена до Dolt write." >&2
    exit 2 ;;
esac

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
