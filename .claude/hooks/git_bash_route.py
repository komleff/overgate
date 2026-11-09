"""Маршрут вызова git для repository mutation guard (og-5l6, ADR §3.38).

На macOS/Linux guard запускает `git` напрямую, как и раньше. На Windows нативный
Python передал бы MSYS-пути команды (`/d/...`) нативному `git.exe` без
преобразования: недоступный источник конфигурации git пропускает молча, lookup
alias даёт «нет alias», и команда, опасная при реальном запуске из Git Bash,
проходила. Поэтому на `nt` git запускается через Git Bash той же установки Git
for Windows, что исполняет команды агента: MSYS-преобразование argv и окружения
совпадает с реальным запуском, перечислять классы путей не нужно.

Входы выбора bash — только окружение процесса хука (`CLAUDE_CODE_GIT_BASH_PATH`
и PATH для поиска `git.exe`). Окружение самой команды получает лишь запущенный
bash для git; присваивание `CLAUDE_CODE_GIT_BASH_PATH=…`/`PATH=…` в команде выбор
не меняет. Решающий признак — bash и `git.exe` из одной установки Git for
Windows; `$OSTYPE == msys` — дополнительная проверка. Любая неоднозначность,
отсутствие или ошибка запуска — `RouteError`, guard блокирует (fail-closed).

argv git передаётся через окружение, а не командной строкой Windows: MSYS/Cygwin
разбирает командную строку нативного родителя сам (одинарные кавычки, обратные
слэши, glob), и argv lookup мог бы отличаться от argv реального запуска. Скрипт
читается bash со stdin и эквивалентен `exec git "$@"`.
"""

from __future__ import annotations

import ntpath
import os
import subprocess
from typing import Callable, Mapping, Sequence

# Префиксы раскладки Git for Windows, где лежит настоящий git.exe.
_MINGW_PREFIXES = ("mingw64", "mingw32", "clangarm64", "clang64", "ucrt64")
# WSL-заглушки bash.exe: CreateProcess находит их раньше Git Bash.
_WSL_STUB_DIRS = ("\\windows\\system32\\", "\\windows\\sysnative\\", "\\windowsapps\\")
_ARGC = "OVERGATE_GUARD_GIT_ARGC"
_ARG = "OVERGATE_GUARD_GIT_ARG_"
# Код выхода скрипта, если bash оказался не MSYS (Cygwin, WSL и т.п.).
EXIT_NOT_MSYS = 125
POSIX_TIMEOUT = 2
# Windows: запуск bash + git; замер Windows CI, ADR §3.38. Предел быстрой проверки
# диспетчера (10 с) остаётся общим ограничителем.
NT_TIMEOUT = 5


class RouteError(RuntimeError):
    pass


def os_name() -> str:
    """Отдельная функция: модульный тест подменяет её, чтобы пройти маршрут `nt`."""
    return os.name


def _norm(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


def _is_windows_absolute(path: str) -> bool:
    drive, rest = ntpath.splitdrive(path)
    return bool(drive) and rest[:1] in ("\\", "/")


def find_git_exe(path_value: str, is_file: Callable[[str], bool]) -> str | None:
    """Первый `git.exe` в PATH процесса хука; относительные и MSYS-записи пропускаются."""
    for entry in path_value.split(";"):
        entry = entry.strip().strip('"')
        if not entry or not _is_windows_absolute(entry):
            continue
        candidate = ntpath.join(entry, "git.exe")
        if is_file(candidate):
            return candidate
    return None


def install_root(git_exe: str) -> str | None:
    """Корень установки по раскладке: `<root>/cmd`, `<root>/<mingw>/bin`, `<root>/bin`."""
    parent = ntpath.dirname(ntpath.normpath(git_exe))
    name = ntpath.basename(parent).lower()
    if name == "cmd":
        return ntpath.dirname(parent)
    if name == "bin":
        upper = ntpath.dirname(parent)
        if ntpath.basename(upper).lower() in _MINGW_PREFIXES:
            return ntpath.dirname(upper)
        return upper
    return None


def resolve_bash(environ: Mapping[str, str], is_file: Callable[[str], bool]) -> str:
    """Git Bash той же установки Git for Windows, что и `git.exe` из PATH хука."""
    git_exe = find_git_exe(environ.get("PATH", "") or environ.get("Path", ""), is_file)
    if git_exe is None:
        raise RouteError("git.exe not found in hook PATH; Git for Windows is required")
    root = install_root(git_exe)
    # `cmd/git.exe` есть только у Git for Windows: отдельный MSYS2 и Cygwin его не имеют.
    if (
        root is None
        or not is_file(ntpath.join(root, "cmd", "git.exe"))
        or not is_file(ntpath.join(root, "usr", "bin", "bash.exe"))
    ):
        raise RouteError(f"{git_exe} is not part of a Git for Windows installation")
    allowed = [ntpath.join(root, "bin", "bash.exe"), ntpath.join(root, "usr", "bin", "bash.exe")]
    override = environ.get("CLAUDE_CODE_GIT_BASH_PATH", "")
    if override:
        if not _is_windows_absolute(override):
            raise RouteError("CLAUDE_CODE_GIT_BASH_PATH is not an absolute Windows path")
        lowered = _norm(override)
        if any(marker in lowered for marker in _WSL_STUB_DIRS):
            raise RouteError("CLAUDE_CODE_GIT_BASH_PATH points to a WSL bash stub")
        if lowered not in {_norm(path) for path in allowed}:
            raise RouteError(
                "CLAUDE_CODE_GIT_BASH_PATH and git.exe belong to different installations"
            )
        if not is_file(override):
            raise RouteError("CLAUDE_CODE_GIT_BASH_PATH does not exist")
        return override
    for candidate in allowed:
        if is_file(candidate):
            return candidate
    raise RouteError(f"Git Bash not found in {root}")


def bash_script(program: str = "git", ostype: str = "msys") -> str:
    """Скрипт для `bash -s`: собрать argv из окружения и выполнить `exec git "$@"`."""
    return (
        f'case "$OSTYPE" in {ostype}) ;; *) exit {EXIT_NOT_MSYS} ;; esac\n'
        "set --\n"
        "i=0\n"
        f'while [ "$i" -lt "${{{_ARGC}:-0}}" ]; do\n'
        f'  name="{_ARG}$i"\n'
        '  set -- "$@" "${!name}"\n'
        '  unset "$name"\n'
        "  i=$((i + 1))\n"
        "done\n"
        f"unset {_ARGC} name i\n"
        f'exec {program} "$@"\n'
    )


def bash_environment(argv: Sequence[str], env: Mapping[str, str]) -> dict[str, str]:
    result = {
        key: value
        for key, value in env.items()
        if key != _ARGC and not key.startswith(_ARG)
    }
    result[_ARGC] = str(len(argv))
    for index, value in enumerate(argv):
        result[f"{_ARG}{index}"] = value
    return result


# Точки подмены для модульного теста маршрута `nt` (кандидаты и launcher).
_is_file = os.path.isfile
_launch = subprocess.run
_RESOLVED: list[str] = []


def _hook_environ() -> Mapping[str, str]:
    return os.environ


def _hook_bash() -> str:
    # Выбор bash кэшируется на процесс хука; входы — только его окружение.
    if not _RESOLVED:
        _RESOLVED.append(resolve_bash(_hook_environ(), _is_file))
    return _RESOLVED[0]


def run_git(
    argv: Sequence[str], *, env: Mapping[str, str], cwd: str | None
) -> subprocess.CompletedProcess:
    """Запустить `git <argv>` с окружением и каталогом команды.

    Ошибка выбора bash или запуска — `RouteError`; код выхода git возвращается
    вызывающему (lookup alias трактует 1 как «нет alias», прочее — блок).
    """
    if os_name() != "nt":
        try:
            return _launch(
                ["git", *argv], check=False, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="surrogateescape", timeout=POSIX_TIMEOUT, env=dict(env), cwd=cwd,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RouteError(f"git did not run: {exc}") from exc
    bash = _hook_bash()
    try:
        proc = _launch(
            [bash, "-s"], input=bash_script(), check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="surrogateescape", timeout=NT_TIMEOUT,
            env=bash_environment(argv, env), cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RouteError(f"Git Bash {bash} did not run git: {exc}") from exc
    if proc.returncode == EXIT_NOT_MSYS:
        raise RouteError(f"{bash} is not Git Bash (OSTYPE is not msys)")
    return proc
