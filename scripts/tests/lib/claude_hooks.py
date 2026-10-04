"""Общий доступ тестов к единственной записи PreToolUse(Bash) Claude и диспетчеру.

Записи `.claude/settings.json` больше не несут имён проверок: все три подключены
в `.claude/hooks/pre-bash.sh`, а запись только находит его. Тест, которому нужна
«запись проверки X», берёт единственную запись и подтверждает подключение X в
диспетчере через `guard_wired`. Пределы: у записи — `entry_timeout` (бюджет гейта
тестов), у быстрых проверок — `quick_limit` диспетчера.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DISPATCHER_RELATIVE = ".claude/hooks/pre-bash.sh"
GUARDS = (
    "check-repository-mutation.py",
    "check-merge-ready.py",
    "check-tests-before-commit.sh",
)


def settings(root: Path | str) -> dict:
    return json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))


def bash_entries(root: Path | str) -> list[dict]:
    """Обработчики всех записей PreToolUse с matcher ровно `Bash`."""
    return [
        hook
        for entry in settings(root).get("hooks", {}).get("PreToolUse", [])
        if entry.get("matcher") == "Bash"
        for hook in entry.get("hooks", [])
    ]


def dispatcher_entry(root: Path | str) -> dict:
    """Единственная managed запись Bash; custom project hooks сохраняются."""
    entries = [h for h in bash_entries(root) if any(name in h.get("command", "")
               for name in (*GUARDS, "pre-bash.sh"))]
    if len(entries) != 1:
        raise SystemExit(f"ожидалась ровно одна managed запись PreToolUse(Bash), найдено {len(entries)}")
    if DISPATCHER_RELATIVE not in entries[0].get("command", ""):
        raise SystemExit(f"запись PreToolUse(Bash) не ссылается на {DISPATCHER_RELATIVE}")
    return entries[0]


def entry_command(root: Path | str) -> str:
    return dispatcher_entry(root)["command"]


def entry_timeout(root: Path | str) -> int:
    timeout = dispatcher_entry(root).get("timeout")
    if not isinstance(timeout, int):
        raise SystemExit("у записи PreToolUse(Bash) нет числового объявленного предела")
    return timeout


def dispatcher_text(root: Path | str) -> str:
    return (Path(root) / DISPATCHER_RELATIVE).read_text(encoding="utf-8")


def guard_wired(root: Path | str, name: str) -> bool:
    """Подключена ли проверка `name` в диспетчере (строкой `guard … "$HOOK_DIR/<name>"`)."""
    pattern = r'^guard\s+"[^"]*"\s+.*' + re.escape(f'"$HOOK_DIR/{name}"')
    return re.search(pattern, dispatcher_text(root), re.MULTILINE) is not None


def quick_limit(root: Path | str) -> int:
    """Предел одной быстрой проверки, секунды (строка `QUICK_LIMIT=<n>` диспетчера)."""
    match = re.search(r"^QUICK_LIMIT=(\d+)\s*$", dispatcher_text(root), re.MULTILINE)
    if match is None:
        raise SystemExit("в диспетчере нет строки QUICK_LIMIT=<n>")
    return int(match.group(1))


def native_bash() -> str:
    """Нативный Git Bash; System32/bash.exe ведёт в WSL и не проверяет Windows quoting."""
    if os.name!='nt':return 'bash'
    candidates=[Path(p)/'bash.exe' for p in os.environ.get('PATH','').split(os.pathsep)]
    candidates += [Path('C:/Program Files/Git/usr/bin/bash.exe'),Path('C:/Program Files/Git/bin/bash.exe')]
    for candidate in candidates:
        if candidate.is_file() and 'system32' not in str(candidate).lower():return str(candidate)
    raise RuntimeError('native Git Bash is required')
