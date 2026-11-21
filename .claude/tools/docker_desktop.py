#!/usr/bin/env python3
"""Ограниченное владение Docker Desktop на Windows/macOS, без фонового агента."""
import argparse
from contextlib import contextmanager
import ctypes
import getpass
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid


START_TIMEOUT = 120
# Из резерва Windows gate в 120 с: prepared acquire ≤ 20 с, cleanup ≤ 85 с.
# Остаток нужен для запуска процессов, возврата из timeout child и записи результата.
COMMIT_CLEANUP_TIMEOUT = 85


class DesktopError(RuntimeError):
    pass


class MacDesktopStillActive(DesktopError):
    pass


def alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def time_left(limit, deadline):
    if deadline is None:
        return limit
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DesktopError('Предел времени операции Docker Desktop исчерпан; владение сохранено')
    return min(limit, remaining)


class Desktop:
    def __init__(self, state_dir=None, run=subprocess.run, platform=sys.platform, hook=False):
        self.windows = platform == 'win32'
        self.macos = platform == 'darwin'
        self.enabled = self.windows or self.macos
        self.directory = Path(state_dir or (Path(tempfile.gettempdir()) /
                              ('overgate-desktop-' + getpass.getuser())))
        self.state_file = self.directory / 'owner.json'
        self.run, self.hook = run, hook
        self.owned = False
        self.previous_scope = os.environ.get('OVERGATE_DOCKER_SCOPE')

    def command(self, *args, timeout=5, deadline=None):
        try:
            return self.run(['docker', *args], capture_output=True, text=True, timeout=time_left(timeout, deadline),
                            encoding='utf-8')
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DesktopError('Docker CLI: ' + str(error)) from error

    @contextmanager
    def lock(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_file = self.directory / 'acquire.lock'
        if any(p.is_symlink() for p in (self.directory, self.state_file, lock_file)):
            raise DesktopError('Каталог владения Desktop не может быть symlink')
        info = self.directory.stat()
        if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise DesktopError('Каталог владения Desktop должен быть приватным')
        # OS lock освобождается и при hard kill; файл не является признаком занятости.
        with lock_file.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise DesktopError('Desktop занят другой операцией acquire/recover') from error
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def read(self):
        return (json.loads(self.state_file.read_text(encoding='utf-8'))
                if self.state_file.exists() else None)

    def save(self, state):
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='owner-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.state_file)
        finally:
            Path(name).unlink(missing_ok=True)

    def windows_desktop_absent(self, timeout):
        system_root = os.environ.get('SystemRoot')
        if not system_root:
            raise DesktopError('Не удалось определить каталог Windows для проверки Desktop')
        powershell = Path(system_root) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        # Отсутствие Desktop подтверждаем независимо от CLI: обе проверки должны выполниться.
        probe = r"""
$ErrorActionPreference = 'Stop'
$processes = Get-Process | Where-Object { $_.ProcessName -in @('Docker Desktop', 'com.docker.backend') }
$pipes = [IO.Directory]::GetFiles('\\.\pipe\') | Where-Object {
    [IO.Path]::GetFileName($_) -in @('dockerDesktopLinuxEngine', 'dockerDesktopWindowsEngine', 'docker_engine')
}
if (-not ($processes -or $pipes)) { [Console]::WriteLine('desktop-absent') }
"""
        try:
            result = self.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', probe],
                              capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DesktopError('Активность Docker Desktop в Windows не определена') from error
        return result.returncode == 0 and not result.stderr.strip() and result.stdout.strip() == 'desktop-absent'

    def confirm_macos_stopped(self, deadline):
        # Desktop CLI can report "stopped" while the native Engine is still serving.
        endpoint = self.command('context', 'inspect', '--format', '{{.Endpoints.docker.Host}}',
                                deadline=deadline)
        host = endpoint.stdout.strip()
        if endpoint.returncode or endpoint.stderr.strip() or not host.startswith('unix:///'):
            raise DesktopError('Не подтверждён локальный сокет Docker Desktop на macOS')
        selected = Path(host[len('unix://'):]).resolve()
        desktop_socket = (Path.home() / '.docker/run/docker.sock').resolve()
        if selected != desktop_socket:
            raise DesktopError('Выбранный endpoint не совпадает с сокетом Docker Desktop на macOS')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(time_left(5, deadline))
            try:
                probe.connect(str(desktop_socket))
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            except OSError as error:
                raise DesktopError('Доступность сокета Docker Desktop не определена') from error
            else:
                raise MacDesktopStillActive('Desktop сообщает stopped, но локальный сокет Engine отвечает')
        try:
            processes = self.run(['/bin/ps', '-A', '-o', 'comm='], capture_output=True,
                                 text=True, timeout=time_left(5, deadline))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DesktopError('Активность процессов Docker Desktop на macOS не определена') from error
        if processes.returncode or processes.stderr.strip() or not processes.stdout.strip():
            raise DesktopError('Не удалось проверить процессы Docker Desktop на macOS')
        names = {Path(line.strip()).name for line in processes.stdout.splitlines()}
        if names.intersection(('Docker Desktop', 'com.docker.backend')):
            raise MacDesktopStillActive('Desktop сообщает stopped, но процессы Docker Desktop ещё работают')

    def status(self, *, allow_cold=True, allow_starting=False, deadline=None):
        # Windows Desktop 4.99 при выключенном приложении возвращает диагностический RC1 с задержкой.
        cold = self.enabled and allow_cold
        result = self.command('desktop', 'status', '--format', 'json',
                              timeout=25 if cold else 5, deadline=deadline)
        if result.returncode:
            if (cold and result.returncode == 1 and not result.stdout.strip()
                    and result.stderr.partition('\n')[0].strip() == 'Could not retrieve status. Is Docker Desktop running?'):
                if self.macos:
                    self.confirm_macos_stopped(deadline)
                    return 'stopped', None
                if self.windows_desktop_absent(time_left(5, deadline)):
                    return 'stopped', None
            raise DesktopError('Статус Desktop не определён; нужен Docker Desktop CLI с status/start/stop')
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise DesktopError('Неизвестный JSON статуса Desktop; владение сохранено')
        status = str(data.get('Status', data.get('status', ''))).strip().lower()
        if status not in ('running', 'stopped') and not (allow_starting and status == 'starting'):
            raise DesktopError('Desktop в неизвестном/переходном состоянии; владение сохранено')
        if self.macos and status == 'stopped':
            self.confirm_macos_stopped(deadline)
        session_id = data.get('SessionID')
        if status == 'stopped' or not isinstance(session_id, str) or not session_id.strip():
            session_id = None
        return status, session_id

    def require_session(self, state, session_id):
        if session_id is None or state.get('session_id') != session_id:
            raise DesktopError('Сеанс Docker Desktop не подтверждён или изменился; владение сохранено')

    def engine(self, *, wait_ready=False, deadline=None):
        endpoint = self.command('context', 'inspect', '--format', '{{.Endpoints.docker.Host}}',
                                deadline=deadline)
        if endpoint.returncode or not endpoint.stdout.strip().startswith(('unix://', 'npipe:////./pipe/')):
            raise DesktopError('Проверка требует локальный Desktop endpoint, не remote Docker context')
        result = self.command('info', '--format', '{{.OperatingSystem}}', deadline=deadline)
        if wait_ready and result.returncode:
            return False
        if result.returncode or 'docker desktop' not in result.stdout.lower():
            raise DesktopError('Локальный Desktop engine не готов или его identity не подтверждена')
        return True

    def start_owned(self):
        deadline = time.monotonic() + START_TIMEOUT
        result = self.command('desktop', 'start', timeout=START_TIMEOUT, deadline=deadline)
        if result.returncode:
            raise DesktopError('docker desktop start отказал')
        # RC0 также бывает у «already running»; такой экземпляр нельзя присваивать.
        if result.stdout.strip() != '\N{CHECK MARK} Starting Docker Desktop' or result.stderr.strip():
            raise DesktopError('Собственный запуск Docker Desktop не подтверждён')
        while True:
            status, session_id = self.status(allow_starting=True, deadline=deadline)
            if status == 'stopped':
                raise DesktopError('Desktop выключен после start')
            if 'session_id' not in self.state and session_id is not None:
                self.state['session_id'] = session_id
                self.save(self.state)
            self.require_session(self.state, session_id)
            if status == 'running' and self.engine(wait_ready=True, deadline=deadline):
                return
            time.sleep(time_left(1, deadline))

    def __enter__(self):
        if not self.enabled:
            return self
        try:
            with self.lock():
                state = self.read()
                if state:
                    if state['token'] == self.previous_scope and alive(state['pid']):
                        _, session_id = self.status(allow_cold=False)
                        self.require_session(state, session_id)
                        return self
                    if not state.get('prepared'):
                        if alive(state['pid']):
                            raise DesktopError('Desktop занят другой активной операцией')
                        raise DesktopError('Незавершённое владение: выполни docker_desktop.py recover')
                status, session_id = self.status(allow_cold=not self.hook)
                running = status == 'running'
                if running:
                    if not (state and state.get('prepared')):
                        raise DesktopError('Desktop уже запущен без нашего владения; чужую работу не останавливаем')
                    self.require_session(state, session_id)
                if not running and self.hook:
                    raise DesktopError('Перед commit выполни: bash .claude/tools/run-python.sh .claude/tools/docker_desktop.py prepare')
                self.state = {'token': str(uuid.uuid4()), 'pid': os.getpid(), 'prepared': False}
                if running:
                    self.state['session_id'] = session_id
                self.save(self.state)
                self.owned = True
                os.environ['OVERGATE_DOCKER_SCOPE'] = self.state['token']
                if not running:
                    self.start_owned()
                else:
                    _, session_id = self.status(allow_cold=False)
                    self.require_session(self.state, session_id)
                    self.engine()
        except BaseException:
            if self.owned:
                self.__exit__(None, None, None)
            raise
        return self

    def close_locked(self, *, in_hook=False):
        deadline = time.monotonic() + COMMIT_CLEANUP_TIMEOUT if self.windows and in_hook else None
        if self.read() != self.state:
            raise DesktopError('Владение Desktop изменилось; остановка запрещена')
        status, session_id = self.status(allow_cold=not in_hook, deadline=deadline)
        if status == 'running':
            self.require_session(self.state, session_id)
            self.engine(deadline=deadline)
            token = self.state.get('token')
            if not isinstance(token, str) or not token:
                raise DesktopError('Scope контейнеров в журнале не подтверждён; stop запрещён')
            owned_query = ('ps', '-a', '-q', '--no-trunc', '--filter', 'label=overgate.desktop.scope=' + token)
            owned = self.command(*owned_query, deadline=deadline)
            ids = owned.stdout.split()
            if owned.returncode or any(len(i) != 64 or not all(c in '0123456789abcdef' for c in i) for i in ids):
                raise DesktopError('ID контейнеров собственного scope не подтверждены; stop запрещён')
            if ids:
                _, session_id = self.status(allow_cold=False, deadline=deadline)
                self.require_session(self.state, session_id)
                if self.command('rm', '-f', *ids, timeout=10, deadline=deadline).returncode:
                    raise DesktopError('Не удалён контейнер собственного scope; cleanup FAILED')
                owned = self.command(*owned_query, deadline=deadline)
                if owned.returncode or owned.stdout.strip():
                    raise DesktopError('Очистка контейнеров собственного scope не подтверждена; cleanup FAILED')
            running = self.command('ps', '-q', '--no-trunc', deadline=deadline)
            if running.returncode or running.stdout.strip():
                raise DesktopError('В Desktop осталась чужая/неизвестная работа; stop запрещён')
            _, session_id = self.status(allow_cold=False, deadline=deadline)
            self.require_session(self.state, session_id)
            if self.command('desktop', 'stop', timeout=20, deadline=deadline).returncode:
                raise DesktopError('docker desktop stop отказал; cleanup FAILED')
            # macOS may return from stop before the Engine socket and backend close.
            if self.macos:
                deadline = time.monotonic() + 35  # includes a possible 25 s Desktop CLI probe
            while True:
                try:
                    status, _ = self.status(deadline=deadline)
                    break
                except MacDesktopStillActive:
                    time.sleep(time_left(1, deadline))
            if status != 'stopped':
                raise DesktopError('Desktop остался запущен; cleanup FAILED')
        self.state_file.unlink()
        self.owned = False

    def restore_scope(self):
        if self.previous_scope is None:
            os.environ.pop('OVERGATE_DOCKER_SCOPE', None)
        else:
            os.environ['OVERGATE_DOCKER_SCOPE'] = self.previous_scope

    def __exit__(self, *exc):
        if self.owned:
            try:
                with self.lock():
                    self.close_locked(in_hook=self.hook)
            finally:
                self.restore_scope()

    def prepare(self, command=None):
        with self:
            if command:
                subprocess.run(command, check=True)
            if self.enabled:
                with self.lock():
                    self.state.update(prepared=True, pid=0)
                    self.save(self.state)
                    self.owned = False
                self.restore_scope()

    def recover(self):
        if not self.enabled:
            return
        with self.lock():
            self.state = self.read()
            if self.state:
                if alive(self.state['pid']):
                    raise DesktopError('Владелец Desktop ещё работает')
                self.close_locked()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'recover', 'run'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    def terminated(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminated)
    desktop = Desktop(hook=os.environ.get('OVERGATE_COMMIT_GATE') == '1')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if args.operation == 'prepare':
        desktop.prepare(command)
    elif args.operation == 'recover':
        desktop.recover()
    else:
        if not command:
            parser.error('run требует команду')
        with desktop:
            child = subprocess.Popen(command)
            try:
                return child.wait()
            except BaseException:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                raise
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (DesktopError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print('DESKTOP FAILED: ' + str(error), file=sys.stderr)
        sys.exit(1)
