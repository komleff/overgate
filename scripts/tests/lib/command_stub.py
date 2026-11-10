#!/usr/bin/env python3
"""Заглушки команд для фикстур, которые видит и нативный процесс Windows (D-5, D-8).

Скрипт с shebang без расширения исполняет только bash. Нативный Python на Windows
(`subprocess.run(['gh', ...])`) ищет через CreateProcess `gh.exe` и находит
настоящий gh — заглушка не перехватывает вызов. Поэтому на Windows рядом со
скриптом кладётся `<имя>.exe`: стандартный launcher distlib (тот же, которым pip
делает console scripts) с встроенным `__main__.py`. Для Python-заглушки он
исполняет её текст тем же интерпретатором, для shell-заглушки — запускает её
Git Bash с тем же argv. На macOS/Linux ничего не добавляется.

CLI для shell-фикстур: `run-python.sh command_stub.py <каталог> <имя>` — после того
как фикстура записала `<каталог>/<имя>` (shell-скрипт).
"""
from __future__ import annotations

import io
import os
import platform
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_hooks import native_bash  # noqa: E402


def _launcher() -> bytes:
    try:
        from pip._vendor.distlib import scripts
    except ImportError as exc:  # pragma: no cover - зависит от установки Python
        raise RuntimeError("для заглушки .exe нужен pip (distlib launcher) в Python тестов") from exc
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        name = "t64-arm.exe"
    else:
        name = "t64.exe" if struct.calcsize("P") == 8 else "t32.exe"
    return (Path(scripts.__file__).parent / name).read_bytes()


# Стандартные потоки заглушки — двоичные: заглушка обязана видеть байты ровно как
# настоящая программа (CRLF в теле комментария не должен превращаться в LF).
_BINARY_STDIO = (
    "import msvcrt as _msvcrt, os as _os\n"
    "for _fd in (0, 1, 2):\n"
    "    _msvcrt.setmode(_fd, _os.O_BINARY)\n"
)


def _write_exe(target: Path, main_source: str) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("__main__.py", _BINARY_STDIO + main_source)
    shebang = f'#!"{sys.executable}"\r\n'.encode("utf-8")
    target.write_bytes(_launcher() + shebang + stream.getvalue())


def exe_stub(directory: Path, name: str, main_source: str) -> None:
    """На Windows — `<каталог>/<имя>.exe`, исполняющий `main_source`; иначе ничего."""
    if os.name == "nt":
        _write_exe(Path(directory) / (name + ".exe"), main_source)


def python_stub(directory: Path, name: str, source: str) -> Path:
    """Python-заглушка `<каталог>/<имя>`; на Windows ещё и `<имя>.exe` с тем же текстом."""
    path = Path(directory) / name
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8", newline="\n")
    path.chmod(0o755)
    exe_stub(Path(directory), name, source)
    return path


def shell_stub_exe(directory: Path, name: str) -> None:
    """Для уже записанной shell-заглушки на Windows добавить `<имя>.exe` через Git Bash."""
    if os.name != "nt":
        return
    script = Path(directory) / name
    if not script.is_file():
        raise RuntimeError(f"shell-заглушка не найдена: {script}")
    source = (
        "import subprocess, sys\n"
        f"raise SystemExit(subprocess.call([{native_bash()!r}, {str(script)!r}, *sys.argv[1:]]))\n"
    )
    _write_exe(script.with_name(name + ".exe"), source)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: command_stub.py <directory> <name>")
    shell_stub_exe(Path(sys.argv[1]), sys.argv[2])
