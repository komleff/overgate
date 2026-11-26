#!/usr/bin/env bash
# Единая точка входа PreToolUse для инструмента Bash.
#
# Запись в .claude/settings.json ищет этот файл только в каталоге сессии и передаёт
# ему payload (JSON на stdin). Поэтому диспетчер всегда исполняется в корне своего
# checkout: корень — каталог самого файла, и проверки (включая гейт тестов, который
# гоняет набор в текущем каталоге) работают над тем деревом, где идёт работа.
#
# Почему один файл вместо четырёх inline-обёрток (инцидент 2026-10-01, PR #782):
# текст обёртки Claude Code передаёт Git Bash аргументом командной строки из
# нативного процесса Windows, и пара `\\` в нём схлопывается в один `\` —
# нормализация `${ROOT//\\//}` превращалась в «удалить все `/`», и каждая обёртка
# блокировала любую команду. Файл-скрипт читается bash напрямую, без разбора
# командной строки, поэтому вся логика живёт здесь, а запись в settings.json
# обязана оставаться без обратных слэшей (инвариант закреплён тестом
# scripts/tests/pre-bash-dispatch.test.py).
#
# Проверки идут последовательно, каждая получает payload на stdin; порядок — от
# дешёвых к тяжёлой. Код 0 — пропустить; 2 — заблокировать с текстом проверки;
# любой другой код — блокировка с фактами (fail-closed: раньше снятую по пределу
# проверку диспетчер Claude Code считал неблокирующей, и команда проходила).
# Истечение предела быстрой фазы — деградированный режим (ADR §3.40): проходит только
# статичная команда из короткого списка, всё прочее блокируется с честной причиной.
#
# Каталог сессии без этого файла (подпапка checkout, чужой каталог) обрабатывает
# сама запись: проходит ровно одна команда — `cd <абсолютный путь к корню
# checkout>`, всё остальное блокируется с подсказкой. Охраняемые операции там не
# выразимы по построению, поэтому новую проверку достаточно подключить ниже.
#
# Пригодно любому runtime, передающему payload PreToolUse на stdin (Claude Code,
# Codex и будущие адаптеры): адаптеру достаточно одной строки вызова.
set -u

HOOK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$HOOK_DIR/../.." && pwd -P)"
LAUNCHER="$ROOT/.claude/tools/run-python.sh"
TIMEOUT_HELPER="$ROOT/.claude/tools/with-timeout.sh"
# Предел быстрой проверки, секунды: запуск интерпретатора и разбор команды занимают
# доли секунды; у merge-ready собственный предел разбора 2 с, у защиты репозитория —
# обращения к git по 2 с. Десять секунд — запас на загруженную машину.
QUICK_LIMIT=10

PAYLOAD="$(cat)"

# >>> static-triage
# Триаж деградированного режима (ADR §3.40). Вызывается ТОЛЬКО после истечения предела
# быстрой фазы, поэтому быстрый режим его не исполняет. Решает одно: может ли команда по
# построению запустить что-либо, кроме программ списка. Программы списка не исполняют
# внешних команд по аргументам и не меняют состояние оболочки, от которого зависит разрешение
# следующей команды (поэтому исключены printf — `printf -v` пишет BASH_CMDS/commands/PATH —
# hash, find, xargs, sed, awk, sort, env, command, exec, time, интерпретаторы и оболочки).
# Слово команды сверяется буквально: путь, .exe, кавычки, {}, глоб, присваивание или
# перенаправление на его месте не совпадают со списком. Подстановки и сборка слова требуют $,
# обратной кавычки или обратной косой черты — они запрещены. Чистый bash 3.2 (системный bash
# macOS): без ${x,,}, массивов и mapfile; LC_ALL=C — байтовая семантика и скорость.
STATIC_COMMANDS='ls cat head tail wc grep stat file du df pwd cd echo date uname whoami id hostname which type true false sleep ps uptime sw_vers cut tr uniq nl basename dirname realpath readlink'
STATIC_PAYLOAD_MAX=4096

# Печатает static, только если команда payload статична. Любой иной исход, включая срыв
# bash, означает guarded; вызывающий принимает только точный вывод static.
static_verdict_raw() {
  LC_ALL=C
  local p="$PAYLOAD" rest cmd seg word n=0 ws=$' \t\r\n' x1=$'\001' x2=$'\002' nl=$'\n'
  [ "${#p}" -le "$STATIC_PAYLOAD_MAX" ] || return 0
  case "$p" in *"$x1"*|*"$x2"*) return 0 ;; esac
  # Ключ "command" ровно один. Внутри строкового значения JSON кавычка всегда экранирована,
  # поэтому совпадение внутри значения невозможно.
  rest="${p#*\"command\"}"
  [ "$rest" != "$p" ] || return 0
  case "$rest" in *'"command"'*) return 0 ;; esac
  rest="${rest#"${rest%%[!$ws]*}"}"
  [ "${rest:0:1}" = ":" ] || return 0
  rest="${rest:1}"
  rest="${rest#"${rest%%[!$ws]*}"}"
  [ "${rest:0:1}" = '"' ] || return 0
  rest="${rest:1}"
  # Сначала пары \\, затем \": иначе \\" принялся бы за экранированную кавычку.
  rest="${rest//\\\\/$x1}"
  rest="${rest//\\\"/$x2}"
  cmd="${rest%%\"*}"
  [ "$cmd" != "$rest" ] || return 0
  case "$cmd" in *"$x1"*|*'\u'*|*'\b'*|*'\f'*) return 0 ;; esac
  cmd="${cmd//\\n/;}"
  cmd="${cmd//\\r/;}"
  cmd="${cmd//\\t/ }"
  cmd="${cmd//\\\//\/}"
  cmd="${cmd//$x2/\"}"
  case "$cmd" in *'\'*|*'$'*|*'`'*|*/dev/tcp*|*/dev/udp*) return 0 ;; esac
  # Перенаправления >&, <&, &> — не разделители команд.
  cmd="${cmd//>&/>}"
  cmd="${cmd//<&/<}"
  cmd="${cmd//&>/>}"
  # Деление и внутри кавычек только добавляет сегменты (ложный guarded), но не скрывает настоящий.
  cmd="${cmd//[;&|()]/$nl}"
  while IFS= read -r seg; do
    seg="${seg#"${seg%%[!$ws]*}"}"
    [ -n "$seg" ] || continue
    word="${seg%%[$ws<>]*}"
    [ -n "$word" ] || return 0
    case " $STATIC_COMMANDS " in
      *" $word "*) n=$((n + 1)) ;;
      *) return 0 ;;
    esac
  done <<EOF
$cmd
EOF
  [ "$n" -gt 0 ] && echo static
}
# <<< static-triage

# Вердикт один раз за вызов, в подоболочке: срыв bash внутри триажа не завершает диспетчер
# кодом 1 (код 1 хук не блокирует), а даёт guarded.
TRIAGE=''
static_verdict() {
  if [ -z "$TRIAGE" ]; then
    TRIAGE="$(static_verdict_raw 2>/dev/null)"
    [ "$TRIAGE" = static ] || TRIAGE=guarded
  fi
  [ "$TRIAGE" = static ]
}

# Диагностический режим для гейта коммита и тестов: печатает вердикт триажа, ничего не
# проверяя. Запись settings.json вызывает диспетчер без аргументов.
if [ "${1-}" = "--print-static-verdict" ]; then
  if static_verdict; then echo static; else echo guarded; fi
  exit 0
fi

facts() {
  printf 'ROOT=[%s] PWD=[%s] CLAUDE_PROJECT_DIR=[%s]' "$ROOT" "$PWD" "${CLAUDE_PROJECT_DIR-}"
}

# $1 — причина, $2 — одна команда восстановления.
block() {
  printf 'БЛОКИРОВКА: %s; %s. Восстановление: %s\n' "$1" "$(facts)" "$2" >&2
  exit 2
}
RESTORE_FILES="git -C $ROOT checkout -- .claude/hooks .claude/tools"

# Команда восстановления, которую печатает block(), обязана проходить сама — иначе
# сообщение нечестно, а сессия заперта (Code Review, круг 3). Это восстановление
# файлов хуков из индекса того же репозитория: охранять его нечем.
case "$PAYLOAD" in
  *"\"command\":\"$RESTORE_FILES\""*|*"\"command\": \"$RESTORE_FILES\""*) exit 0 ;;
esac

for required in "$LAUNCHER" "$TIMEOUT_HELPER"; do
  [ -f "$required" ] || block "нет файла $required" "$RESTORE_FILES"
done

# Деградированный режим (ADR §3.40). Истечение предела быстрой фазы — признак медленного
# окружения (выгруженные iCloud файлы, перегруженный диск), а не повреждения файлов. Раньше
# оно блокировало любую команду, даже ls, и агент оставался заперт. Теперь статичная команда
# (триаж выше) проходит с предупреждением без оставшихся проверок, всё прочее — блок с
# честной причиной. Подсказка восстановления файлов здесь не печатается: файлы целы.
DEGRADED=0

# Подсказка про iCloud: только macOS, только метаданные (флаг dataless), содержимое не читается.
icloud_hint() {
  [ "$(uname -s 2>/dev/null)" = Darwin ] || return 0
  if stat -f %Sf "$HOOK_DIR"/* "$ROOT"/.claude/tools/*.sh "$ROOT/.git/index" 2>/dev/null | grep -q dataless; then
    printf ' %s' "Файлы хуков или git выгружены iCloud (dataless): вынесите репозиторий из папки под синхронизацией iCloud (Documents/Desktop), например в ~/Developer."
  fi
}

# $1 — что не уложилось в предел.
warn_degraded() {
  printf 'ПРЕДУПРЕЖДЕНИЕ: %s; команда пропущена без оставшихся проверок: это простая команда из списка (%s). Вероятная причина — медленное окружение.%s\n' \
    "$1" "$STATIC_COMMANDS" "$(icloud_hint)" >&2
}

block_slow() {
  printf 'БЛОКИРОВКА: %s; %s. Вероятная причина — медленное окружение (диск, синхронизация, нагрузка), а не повреждение файлов: восстанавливать .claude/hooks не нужно.%s Пока проверки не укладываются в предел, проходят только простые команды из списка: %s — без $, обратных кавычек и обратной косой черты. Диагностика: ls -l .claude/hooks (на macOS ls -lO показывает флаг dataless). Для оператора в терминале: time git -C %s status --short\n' \
    "$1" "$(facts)" "$(icloud_hint)" "$STATIC_COMMANDS" "$ROOT" >&2
  exit 2
}

degrade_or_block() {
  if static_verdict; then
    warn_degraded "$1"
    DEGRADED=1
    return 0
  fi
  block_slow "$1"
}

# $1 — название проверки для сообщения, остальное — команда проверки.
guard() {
  local label="$1"
  shift
  [ "$DEGRADED" = 0 ] || return 0
  printf '%s' "$PAYLOAD" | "$@"
  local rc=$?
  case "$rc" in
    0) return 0 ;;
    2) exit 2 ;;
    124) degrade_or_block "проверка «${label}» не уложилась в отведённое время" ;;
    *) block "проверка «${label}» завершилась кодом $rc, команда не пропускается" "$RESTORE_FILES" ;;
  esac
}

for hook in check-repository-mutation.py check-merge-ready.py check-tests-before-commit.sh; do
  [ -f "$HOOK_DIR/$hook" ] || block "нет файла проверки $HOOK_DIR/$hook" "$RESTORE_FILES"
done

guard "защита репозитория" sh "$TIMEOUT_HELPER" "$QUICK_LIMIT" sh "$LAUNCHER" "$HOOK_DIR/check-repository-mutation.py"
guard "публикация в PR" sh "$TIMEOUT_HELPER" "$QUICK_LIMIT" sh "$LAUNCHER" "$HOOK_DIR/check-merge-ready.py"
# Статичная команда в деградированном режиме не коммит по построению: гейт ей не нужен.
[ "$DEGRADED" = 0 ] || exit 0
# Гейт тестов — последним: он единственный тяжёлый. Его бюджет (разбор ≤ 10 с,
# прогон ≤ 570 с, добивание и запуск ≈ 5 с, итого 585 с при запасе 15 с до
# объявленных записи 600 с) рассчитан на старт в момент запуска записи. Быстрая
# фаза перед ним съедала бы запас: код 2 мог прийти после снятия обработчика, и
# коммит прошёл бы без набора. Поэтому окно прогона сужается на длительность
# быстрой фазы (плюс секунда на округление SECONDS) через крючок гейта, который
# по его контракту только сужает окно и не может расширить; число 570 сюда не
# копируется — действующий предел гейт сообщает сам, с учётом уже заданного
# сужения. Запрос предела идёт под пределом быстрой проверки и входит в быструю
# фазу; сам гейт — под внешним пределом «остаток + 20 с»: его собственные пределы
# (разбор ≤ 10 с, прогон ≤ остаток, добивание ≈ 5 с) укладываются в остаток + 15,
# а внешний срабатывает не позднее 591 с от старта записи (предел 570 + 20 +
# секунда добивания помощника), даже если гейт завис до своего помощника
# времени (иначе снятие обработчика по пределу пропустило бы коммит).
GATE_BASE="$(sh "$TIMEOUT_HELPER" "$QUICK_LIMIT" bash "$HOOK_DIR/check-tests-before-commit.sh" --print-timeout-seconds 2>/dev/null)"
GATE_RC=$?
# Истечение предела запроса — та же быстрая фаза: деградированный режим (ADR §3.40).
if [ "$GATE_RC" -eq 124 ]; then
  degrade_or_block "гейт тестов не сообщил предел прогона за $QUICK_LIMIT с"
  exit 0
fi
[ "$GATE_RC" -eq 0 ] || block "гейт тестов не сообщил предел прогона за $QUICK_LIMIT с (код $GATE_RC)" "$RESTORE_FILES"
case "$GATE_BASE" in
  ''|*[!0-9]*) block "гейт тестов сообщил непригодный предел прогона [$GATE_BASE]" "$RESTORE_FILES" ;;
esac
QUICK_ELAPSED=$((SECONDS + 1))
GATE_LEFT=$((GATE_BASE - QUICK_ELAPSED))
[ "$GATE_LEFT" -gt 0 ] || block "бюджет гейта тестов исчерпан быстрой фазой ($QUICK_ELAPSED с из $GATE_BASE с)" "$RESTORE_FILES"
export OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS="$GATE_LEFT"
guard "гейт тестов перед коммитом" sh "$TIMEOUT_HELPER" "$((GATE_LEFT + 20))" bash "$HOOK_DIR/check-tests-before-commit.sh"
exit 0
