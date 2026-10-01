#!/bin/sh
# Переносимое ограничение времени: GNU timeout предпочтителен, Python — обязательный fallback.

usage() {
  echo "Использование: with-timeout.sh <секунды> <команда> [аргументы…]" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage

seconds="$1"
shift

case "$seconds" in
  ''|*[!0-9]*)
    echo "ОШИБКА: секунды должны быть положительным целым числом: '$seconds'." >&2
    exit 2
    ;;
  0)
    echo "ОШИБКА: секунды должны быть больше нуля." >&2
    exit 2
    ;;
esac

run_native_timeout() {
  native_timeout="$1"
  shift

  status_dir=$(mktemp -d "${TMPDIR:-/tmp}/u2-with-timeout.XXXXXX") || {
    echo "ОШИБКА: не удалось создать временный каталог для контроля timeout." >&2
    return 127
  }
  status_file="$status_dir/command-status"
  native_pid=""

  cancel_native_timeout() {
    cancel_signal="$1"
    cancel_rc="$2"
    # Игнор, а не сброс: со снятыми trap второй сигнал (например INT после TERM)
    # убивал обёртку по default action посреди grace-периода — группа оставалась
    # без SIGKILL и wait, TERM-устойчивый потомок жил сиротой. Игнорируем
    # сигналы отмены до завершения kill/reap; код выхода задаёт ПЕРВЫЙ сигнал.
    trap '' TERM INT HUP

    # Сигнал может прийти сразу после запуска async-list, до явного присваивания
    # `native_pid=$!`. В trap специальный `$!` уже указывает на последний
    # запущенный background process; до spawn он пуст.
    if [ -z "$native_pid" ]; then
      native_pid=$!
    fi

    # Native timeout обычно является лидером отдельной группы и сам передаёт
    # сигнал команде. Посылаем сигнал и процессу, и группе: первый маршрут
    # сохраняет семантику GNU timeout, второй закрывает устойчивых потомков.
    case "$native_pid" in
      ''|*[!0-9]*) ;;
      *)
        kill -"$cancel_signal" "$native_pid" 2>/dev/null || true
        kill -"$cancel_signal" "-$native_pid" 2>/dev/null || true
        /bin/sleep 1
        kill -KILL "-$native_pid" 2>/dev/null || true
        kill -KILL "$native_pid" 2>/dev/null || true
        wait "$native_pid" 2>/dev/null || true
        ;;
    esac
    rm -rf "$status_dir"
    exit "$cancel_rc"
  }

  trap 'cancel_native_timeout TERM 143' TERM
  trap 'cancel_native_timeout INT 130' INT
  trap 'cancel_native_timeout HUP 129' HUP

  # Асинхронный список по POSIX получает stdin из /dev/null, если сам его не
  # перенаправил. Обёртка обязана быть прозрачной для stdin: иначе команда,
  # читающая вход по конвейеру (например разбор payload хука), видела бы пустоту
  # ровно на тех машинах, где есть нативный timeout. Дублируем свой stdin в fd 3
  # и явно отдаём его дочернему списку. Если stdin недоступен, берём /dev/null —
  # это ровно прежнее поведение, а не ошибка.
  #
  # Проверка выполнимости идёт в ПОДОБОЛОЧКЕ, а не в группе. По POSIX ошибка
  # перенаправления у специальной встроенной команды (`exec` — специальная)
  # завершает саму оболочку, и подавление диагностики этого не отменяет. В dash
  # (то есть в `/bin/sh` типичного Linux) обёртка на закрытом входе умирала с
  # кодом 2 ещё до ветки else; bash и zsh на macOS вели себя мягче, поэтому
  # расхождение видел только Linux. Внутри подоболочки завершение убивает
  # подоболочку, а её код возврата и есть ответ «получится или нет».
  if (exec 3<&0) 2>/dev/null; then
    exec 3<&0
  else
    exec 3</dev/null
  fi

  "$native_timeout" -s TERM -k 1 "$seconds" /bin/sh -c '
    status_file=$1
    shift
    "$@"
    command_rc=$?
    printf "%s\n" "$command_rc" >"$status_file"
    exit "$command_rc"
  ' _ "$status_file" "$@" <&3 &
  native_pid=$!
  exec 3<&-

  wait "$native_pid"
  native_rc=$?
  trap - TERM INT HUP

  if [ -s "$status_file" ]; then
    command_rc=$(sed -n '1p' "$status_file")
    rm -rf "$status_dir"
    # Код 124 зарезервирован для deadline самой обёртки. Иначе потребитель
    # не может отличить timeout от обычной команды, которая выбрала тот же код.
    if [ "$command_rc" -eq 124 ]; then
      return 125
    fi
    return "$command_rc"
  fi

  if [ "$native_rc" -eq 124 ]; then
    # GNU timeout может выйти сразу после TERM корня, пока потомок ещё жив.
    # Выдерживаем grace-период сами и независимо добиваем исходную группу.
    /bin/sleep 1
    kill -KILL "-$native_pid" 2>/dev/null || true
    rm -rf "$status_dir"
    return 124
  fi

  rm -rf "$status_dir"
  if [ "$native_rc" -eq 137 ]; then
    # Нет записанного статуса команды: KILL послал native timeout по deadline.
    return 124
  fi
  # Статус-файл — ЕДИНСТВЕННОЕ доказательство того, что дочерняя команда реально
  # запустилась и завершилась (её обёртка пишет туда код возврата ПОСЛЕ запуска).
  # Его отсутствие при native_rc, не равном коду тайм-аута (124/137), означает,
  # что доказательства запуска нет: несовместимый timeout-shim мог вернуть свой
  # код (в том числе 0), не запустив команду. Голый код внешней утилиты без
  # статус-файла успехом не считается — fail-closed, а не пропуск непроверенного
  # результата. Иначе commit-гейт принял бы «зелёные тесты», которых не было.
  echo "ОШИБКА: внешний timeout завершился (код $native_rc) без записи статуса дочерней команды; её фактический запуск не доказан." >&2
  return 127
}

if command -v timeout >/dev/null 2>&1; then
  run_native_timeout "$(command -v timeout)" "$@"
  exit $?
fi

if command -v gtimeout >/dev/null 2>&1; then
  run_native_timeout "$(command -v gtimeout)" "$@"
  exit $?
fi

case "$0" in
  */*) helper_path="$0" ;;
  *) helper_path="$(command -v "$0" 2>/dev/null || printf '%s' "$0")" ;;
esac
tools_dir="${helper_path%/*}"
python_launcher="$tools_dir/run-python.sh"

if [ ! -x "$python_launcher" ] || \
    ! "$python_launcher" -c 'raise SystemExit(0)' >/dev/null 2>&1; then
  echo "ОШИБКА: нет timeout/gtimeout и исправного Python 3; запуск без ограничения времени запрещён." >&2
  exit 127
fi

exec "$python_launcher" -c '
import os
import signal
import subprocess
import sys
import time

timeout_rc = 124
child_timeout_rc = 125
seconds = int(sys.argv[1])
command = sys.argv[2:]

class ExternalCancellation(BaseException):
    def __init__(self, signum):
        self.signum = signum


process = None
pending_cancellation = None
supervisor_ready = False


def record_cancellation(signum, _frame):
    global pending_cancellation
    # Сохраняем ПЕРВЫЙ полученный сигнал. Пока супервизор не готов, повторный
    # сигнал НЕ перезаписывает причину отмены, иначе код выхода отражал бы
    # последний, а не первый сигнал (инвариант первого сигнала: TERM затем INT в
    # окне запуска обязаны дать код TERM). Отмена во время ожидания также идёт по
    # первому сохранённому сигналу.
    if pending_cancellation is None:
        pending_cancellation = signum
    if supervisor_ready:
        raise ExternalCancellation(pending_cancellation)


handled_signals = [signal.SIGTERM, signal.SIGINT]
if hasattr(signal, "SIGHUP"):
    handled_signals.append(signal.SIGHUP)
for handled_signal in handled_signals:
    signal.signal(handled_signal, record_cancellation)

# Тестовый крючок: расширяет окно «сигналы до готовности супервизора», в котором
# проверяется сохранение ПЕРВОГО сигнала. Обработчики уже установлены, поэтому
# сигналы в паузе записываются, но не поднимают отмену. В обычной работе
# переменная не задана и пауза не выполняется.
#
# Крючок не имеет права РАСШИРИТЬ общее окно обёртки. Раньше пауза добавлялась
# к пределу: переменная в окружении растягивала обработчик сверх объявленного
# диспетчеру предела, тот снимал обработчик — и защита превращалась в пропуск.
# На машине без нативного timeout это боевой маршрут, а не только тестовый.
# Поэтому пауза (а) не длиннее самого предела и (б) вычитается из ожидания:
# суммарное время обёртки с крючком и без него одинаково.
startup_pause = os.environ.get("U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS")
paused_seconds = 0.0
if startup_pause:
    try:
        requested_pause = float(startup_pause)
    except (TypeError, ValueError):
        requested_pause = 0.0
    paused_seconds = min(max(requested_pause, 0.0), float(seconds))
    if paused_seconds > 0:
        time.sleep(paused_seconds)

# Остаток предела после паузы. Ноль означает, что весь бюджет уже израсходован,
# и ожидание завершится по deadline немедленно — это корректный вердикт «не
# уложились», а не пропуск.
remaining_seconds = max(float(seconds) - paused_seconds, 0.0)

if os.name == "nt":
    popen_options = {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    }
else:
    popen_options = {"start_new_session": True}

try:
    process = subprocess.Popen(command, **popen_options)
except FileNotFoundError:
    print(f"ОШИБКА: команда не найдена: {command[0]}", file=sys.stderr)
    sys.exit(127)
except (PermissionError, OSError) as error:
    print(f"ОШИБКА: команда не может быть запущена: {command[0]}: {error}", file=sys.stderr)
    sys.exit(126)


def terminate_tree(initial_signal):
    if os.name == "nt":
        # Нативный Windows Python не имеет killpg. taskkill /T адресует всё
        # дерево до исчезновения корня; /F нужен для той же гарантии, что KILL.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return

    try:
        os.killpg(process.pid, initial_signal)
    except ProcessLookupError:
        return

    kill_deadline = time.monotonic() + 1
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    remaining = kill_deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


cleanup_required = True
try:
    try:
        # Открытие окна отмены и проверка ранее пришедшего сигнала выполняются
        # ВНУТРИ того же try, что и ожидание: сигнал, записанный до готовности
        # супервизора, обязан пройти тем же обработчиком отмены, а не всплыть
        # необработанным. Иначе TERM в окне запуска не давал бы код первого
        # сигнала.
        supervisor_ready = True
        if pending_cancellation is not None:
            raise ExternalCancellation(pending_cancellation)
        return_code = process.wait(timeout=remaining_seconds)
    except ExternalCancellation as cancellation:
        for handled_signal in handled_signals:
            signal.signal(handled_signal, signal.SIG_IGN)
        terminate_tree(cancellation.signum)
        cleanup_required = False
        return_code = 128 + cancellation.signum
    except subprocess.TimeoutExpired:
        for handled_signal in handled_signals:
            signal.signal(handled_signal, signal.SIG_IGN)
        terminate_tree(signal.SIGTERM)
        cleanup_required = False
        return_code = timeout_rc
    else:
        cleanup_required = False
        if return_code < 0:
            return_code = 128 + abs(return_code)
        elif return_code == timeout_rc:
            return_code = child_timeout_rc
finally:
    if cleanup_required:
        for handled_signal in handled_signals:
            signal.signal(handled_signal, signal.SIG_IGN)
        terminate_tree(signal.SIGTERM)

sys.exit(return_code)
' "$seconds" "$@"
