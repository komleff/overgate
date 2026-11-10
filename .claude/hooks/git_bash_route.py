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
Windows; `$OSTYPE` msys/cygwin — дополнительная проверка. Любая неоднозначность,
отсутствие или ошибка запуска — `RouteError`, guard блокирует (fail-closed).

argv git передаётся через окружение, а не командной строкой Windows: MSYS/Cygwin
разбирает командную строку нативного родителя сам (одинарные кавычки, обратные
слэши, glob), и argv lookup мог бы отличаться от argv реального запуска. Скрипт
читается bash со stdin и эквивалентен `exec git "$@"`.

Окружение команды до процесса bash не доходит (Code Review PR #19, BLOCKER 1):
`BASH_ENV`, `SHELLOPTS`+`PS4`, `BASH_FUNC_*`, `OSTYPE` и подобные меняли бы ход
скрипта ещё до сборки argv, и lookup отвечал бы «нет alias». Bash получает только
allowlist системных переменных, а окружение команды — транспортом и только для git.
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
_ENVC = "OVERGATE_GUARD_GIT_ENVC"
_ENV = "OVERGATE_GUARD_GIT_ENV_"
_TRANSPORT_PREFIX = "OVERGATE_GUARD_GIT_"
# Окружение самого процесса bash — только этот allowlist из окружения команды
# (имена без учёта регистра, как в Windows). Переменные стартовой обработки bash
# (BASH_ENV, ENV, SHELLOPTS, BASHOPTS, PS4, BASH_XTRACEFD, POSIXLY_CORRECT,
# BASH_COMPAT, OSTYPE, BASH_FUNC_*) до bash не доходят никогда: иначе команда
# меняла бы ход скрипта сборки argv, и lookup отвечал бы «нет alias». Всё окружение
# команды доходит до git отдельным транспортом через `env -i` (MSYS-преобразование
# при запуске git.exe то же, что при реальном запуске).
BASH_ENV_ALLOWLIST = frozenset(
    name.upper() for name in (
        "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
        "TEMP", "TMP", "HOME", "USERPROFILE", "MSYSTEM",
    )
)
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


# Дополнительная проверка, что запущен bash MSYS/Cygwin-рода, а не WSL или иной:
# Git for Windows до 2.5x сообщает `msys`, начиная с 2.56 (bash x86_64-pc-cygwin) — `cygwin`.
# Отличить Git for Windows от отдельного Cygwin/MSYS2 по ней нельзя; решающий признак —
# раскладка установки в resolve_bash.
GIT_BASH_OSTYPES = "msys*|cygwin*"


def bash_script(program: str = "git", ostype: str | None = None) -> str:
    """Скрипт для `bash -s`: семантика `exec git "$@"` с окружением команды.

    argv и окружение команды собираются из транспортных переменных; git запускается
    через `env -i` только с окружением команды (PATH — в форме, преобразованной самим
    bash). OSTYPE читается у настоящего bash: из окружения команды он не приходит.
    Служебные имена уникальны и до git не доходят (`env -i`).
    """
    pattern = GIT_BASH_OSTYPES if ostype is None else ostype
    return (
        f'case "$OSTYPE" in {pattern}) ;; *) exit {EXIT_NOT_MSYS} ;; esac\n'
        "set --\n"
        "__overgate_i=0\n"
        f'while [ "$__overgate_i" -lt "${{{_ARGC}:-0}}" ]; do\n'
        f'  __overgate_n="{_ARG}$__overgate_i"\n'
        '  set -- "$@" "${!__overgate_n}"\n'
        "  __overgate_i=$((__overgate_i + 1))\n"
        "done\n"
        "__overgate_env=()\n"
        "__overgate_i=0\n"
        f'while [ "$__overgate_i" -lt "${{{_ENVC}:-0}}" ]; do\n'
        f'  __overgate_n="{_ENV}$__overgate_i"\n'
        '  __overgate_env+=("${!__overgate_n}")\n'
        "  __overgate_i=$((__overgate_i + 1))\n"
        "done\n"
        f'exec /usr/bin/env -i "${{__overgate_env[@]}}" PATH="$PATH" {program} "$@"\n'
    )


def _bash_allowed(name: str) -> bool:
    return name.upper() in BASH_ENV_ALLOWLIST


def bash_environment(argv: Sequence[str], env: Mapping[str, str]) -> dict[str, str]:
    """Окружение процесса bash: allowlist + транспорт argv и окружения команды."""
    result = {
        key: value
        for key, value in env.items()
        if _bash_allowed(key) and not key.startswith(_TRANSPORT_PREFIX)
    }
    result[_ARGC] = str(len(argv))
    for index, value in enumerate(argv):
        result[f"{_ARG}{index}"] = value
    # PATH до git доходит отдельно, уже преобразованным самим bash (иначе env не найдёт git).
    pairs = [
        f"{key}={value}"
        for key, value in env.items()
        if key.upper() != "PATH" and not key.startswith(_TRANSPORT_PREFIX)
    ]
    result[_ENVC] = str(len(pairs))
    for index, pair in enumerate(pairs):
        result[f"{_ENV}{index}"] = pair
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
    # CP-4: вывод git — строгий UTF-8 (не ANSI code page Windows); кириллица в пути
    # проекта не даёт ложного блока, невалидный UTF-8 — RouteError, guard блокирует.
    if os_name() != "nt":
        try:
            return _launch(
                ["git", *argv], check=False, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="strict", timeout=POSIX_TIMEOUT, env=dict(env), cwd=cwd,
            )
        except UnicodeDecodeError as exc:
            raise RouteError(f"git output is not valid UTF-8: {exc}") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise RouteError(f"git did not run: {exc}") from exc
    bash = _hook_bash()
    try:
        proc = _launch(
            [bash, "--noprofile", "--norc", "-s"], input=bash_script(), check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="strict", timeout=NT_TIMEOUT,
            env=bash_environment(argv, env), cwd=cwd,
        )
    except UnicodeDecodeError as exc:
        raise RouteError(f"git output is not valid UTF-8: {exc}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise RouteError(f"Git Bash {bash} did not run git: {exc}") from exc
    if proc.returncode == EXIT_NOT_MSYS:
        raise RouteError(f"{bash} is not Git Bash (OSTYPE is not msys/cygwin)")
    return proc
