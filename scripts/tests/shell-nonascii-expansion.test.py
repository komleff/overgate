#!/usr/bin/env python3
"""Запрещает раскрытие `$имя` вплотную к не-ASCII символу в shell-поверхности пайплайна.

Системный bash 3.2 на macOS (локаль C.UTF-8 там не поддерживается) берёт первый байт
не-ASCII символа в имя переменной: `«$label»` читается как переменная `label` плюс байт
кавычки. Под `set -u` это «unbound variable» и код 1. В `.claude/hooks/pre-bash.sh` такой
код 1 вместо 2 означал бы, что авария проверки не блокирует команду.

Поведенческие тесты краснеют только на bash 3.2, а Linux CI и Git Bash на Windows идут на
bash 5, где дефект невиден. Поэтому проверка лексическая: она краснеет на любой платформе.
Правило строгое и без исключений — весь текст файла (код, heredoc, комментарий, одинарные
кавычки); лекарство одно: `${имя}`.

Граница лексической проверки: имя, которое собирает сам bash во время исполнения —
подстановка в фигурных скобках (`$l{abel»,}`), `eval`, `sh -c` со склеенной строкой, — и
shell-текст внутри файлов не-shell типов отсюда не видны. Для этого нужен прогон под
bash 3.2, а не разбор текста.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCOPES = (".claude", ".codex", "scripts")
HOOK_CONFIGS = (".claude/settings.json", ".codex/hooks.json")
# Опоры перечисления: если их нет среди проверенных файлов, перечисление сломано, и
# зелёный результат был бы пустым.
ANCHORS = (".claude/hooks/pre-bash.sh", "scripts/verify-reference.sh")
# Файлы, которые заведомо не исполняются оболочкой. Проверяется ВСЁ остальное, включая
# файлы без расширения и с любым shebang: распознавание shell-файла по shebang даёт
# пропуски (`env -S -u FOO bash`, `env -Sbash`, `env -S ba"s"h`). Неизвестное
# расширение — проверяется: лишняя проверка безвредна, пропущенный файл — нет.
NON_SHELL_SUFFIXES = (
    ".md", ".py", ".pyc", ".json", ".jsonl", ".mjs", ".js", ".ps1", ".bat", ".txt",
)
# Любой `$`, за которым идут необязательное имя переменной и сразу байт вне ASCII.
# Исключений нет НАМЕРЕННО: попытки признать пару `$$` безопасной дают обход. Цена —
# сигнал на безопасном `«$$»`; лекарство то же — `${$}`.
UNSAFE_EXPANSION = re.compile(rb"\$(?:[A-Za-z_][A-Za-z0-9_]*)?(?=[\x80-\xff])")
REMEDY = "замени `$имя` на `${имя}` (bash 3.2 на macOS читает байт символа как часть имени)"


def without_escapes(data: bytes) -> tuple[bytes, list[int]]:
    """Текст без обратных косых черт и продолжений строки + номер исходной строки байта.

    Каждый уровень разбора bash (обратные кавычки, двойные кавычки, продолжение строки)
    только УДАЛЯЕТ `\\` и пары `\\`+перевод строки, поэтому удаление их всех сразу —
    надмножество любого числа уровней: `\\$$имя`, `$lab\\\\`⏎`el»` в обратных кавычках
    становятся видимыми. Лишние склейки дают только лишние сигналы.
    """
    out = bytearray()
    lines: list[int] = []
    line, index, size = 1, 0, len(data)
    while index < size:
        if data[index] == 0x5C:  # серия обратных косых черт
            end = index
            while end < size and data[end] == 0x5C:
                end += 1
            if data[end:end + 2] == b"\r\n":
                end += 2
                line += 1
            elif data[end:end + 1] == b"\n":
                end += 1
                line += 1
            index = end
            continue
        out.append(data[index])
        lines.append(line)
        if data[index] == 0x0A:
            line += 1
        index += 1
    return bytes(out), lines


def is_shell_file(relative: str) -> bool:
    return not relative.endswith(NON_SHELL_SUFFIXES)


def listed_paths(root: Path) -> list[str]:
    """Отслеживаемые и неигнорируемые файлы областей; без git — обход каталогов."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others",
         "--exclude-standard", "-z", "--", *SCOPES],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        names = {n for n in result.stdout.decode("utf-8", "surrogateescape").split("\0") if n}
    else:
        names = set()
        for scope in SCOPES:
            base = root / scope
            if not base.is_dir():
                continue
            names.update(path.relative_to(root).as_posix() for path in base.rglob("*"))
    # Вложенные рабочие деревья — чужие checkout'ы, не поверхность этого дерева.
    return sorted(
        n for n in names
        if not n.startswith(".claude/worktrees/") and (root / n).is_file()
    )


def unsafe_lines(origin: str, data: bytes) -> list[str]:
    text, lines = without_escapes(data)
    physical = data.split(b"\n")
    numbers = sorted({lines[match.start()] for match in UNSAFE_EXPANSION.finditer(text)})
    return [
        f"{origin}:{number}: {physical[number - 1].decode('utf-8', 'replace').strip()}"
        for number in numbers
    ]


def hook_commands(root: Path) -> list[tuple[str, str]]:
    """Поле `command` хуков (его исполняет bash); `commandWindows` — PowerShell, вне класса."""
    commands = []
    for config in HOOK_CONFIGS:
        path = root / config
        if not path.is_file():
            continue
        hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
        for event, entries in hooks.items():
            for i, entry in enumerate(entries):
                for j, hook in enumerate(entry.get("hooks", [])):
                    command = hook.get("command")
                    if isinstance(command, str):
                        commands.append((f"{config} hooks.{event}[{i}].hooks[{j}].command", command))
    return commands


def scan(root: Path) -> tuple[list[str], list[str]]:
    """Возвращает (проверенные файлы, нарушения)."""
    checked, violations = [], []
    for relative in listed_paths(root):
        if not is_shell_file(relative):
            continue
        checked.append(relative)
        violations.extend(unsafe_lines(relative, (root / relative).read_bytes()))
    for origin, command in hook_commands(root):
        violations.extend(unsafe_lines(origin, command.encode("utf-8")))
    return checked, violations


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


class RepositoryTree(unittest.TestCase):
    def test_no_unsafe_expansion_in_shell_surface(self) -> None:
        _, violations = scan(ROOT)
        self.assertEqual(violations, [], "\n" + "\n".join(violations) + f"\n{REMEDY}")

    def test_enumeration_is_not_empty(self) -> None:
        checked, _ = scan(ROOT)
        for anchor in ANCHORS:
            self.assertIn(anchor, checked, "перечисление shell-файлов не нашло опору")

    def test_hook_commands_are_read(self) -> None:
        origins = [origin for origin, _ in hook_commands(ROOT)]
        self.assertTrue(any(o.startswith(".claude/settings.json") for o in origins), origins)
        self.assertTrue(any(o.startswith(".codex/hooks.json") for o in origins), origins)


class Detector(unittest.TestCase):
    def test_flags_name_followed_by_non_ascii(self) -> None:
        for line in ('echo "«$label»"', "echo $имя", 'echo "$a_b«"', "«$label» в heredoc", "echo $$$имя"):
            with self.subTest(line=line):
                self.assertTrue(unsafe_lines("x", line.encode("utf-8")))

    def test_escaping_does_not_hide_expansion(self) -> None:
        # Экранирование и пары `$$` исключений не дают: каждая форма — известный обход.
        for line in (
            'echo "\\$$label»"',
            'echo "\\\\$label»"',
            "x=`echo \\$label»`",
            "x=`echo \\\\$$label»`",
            'x="`echo \\\\$$label»`"',
            'echo "«$$»"',
        ):
            with self.subTest(line=line):
                self.assertTrue(unsafe_lines("x", line.encode("utf-8")))

    def test_line_continuation_is_joined(self) -> None:
        # Последняя форма: в обратных кавычках два уровня экранирования, и продолжение
        # строки склеивает имя.
        for text in (
            'echo "$lab\\\nel»"',
            'echo "$\\\nlabel»"',
            'echo "$label\\\n»"',
            "x=`echo $lab\\\\\nel»`",
            "echo $lab\\\r\nel»",
        ):
            with self.subTest(text=text):
                self.assertTrue(unsafe_lines("x", text.encode("utf-8")))

    def test_passes_braced_and_positional(self) -> None:
        for line in ('echo "«${label}»"', 'echo "«$1»"', 'echo "«$?» «$#» «${$}»"', 'echo "$label."'):
            with self.subTest(line=line):
                self.assertEqual(unsafe_lines("x", line.encode("utf-8")), [])

    def test_reports_path_and_line(self) -> None:
        self.assertEqual(unsafe_lines("a.sh", 'ok\necho "«$x»"'.encode("utf-8")), ['a.sh:2: echo "«$x»"'])
        self.assertEqual(
            unsafe_lines("a.sh", 'ok\necho \\\n"«$x»"\nok'.encode("utf-8")),
            ['a.sh:3: "«$x»"'],
        )


class Enumeration(unittest.TestCase):
    BAD = 'echo "«$label»"\n'

    def make_tree(self, root: Path) -> None:
        write(root, "scripts/a.sh", self.BAD)
        write(root, "scripts/tool", "#!/usr/bin/env bash\n" + self.BAD)
        write(root, ".claude/hooks/plain", "#!/bin/sh\n" + self.BAD)
        # Формы `env`, где интерпретатор — не отдельное первое слово.
        write(root, "scripts/env-option", "#!/usr/bin/env -S -u FOO bash\n" + self.BAD)
        write(root, "scripts/env-joined", "#!/usr/bin/env -Sbash\n" + self.BAD)
        write(root, "scripts/env-quoted", '#!/usr/bin/env -S "bash"\n' + self.BAD)
        write(root, "scripts/env-split", '#!/usr/bin/env -S ba"s"h\n' + self.BAD)
        # Без shebang и с неизвестным расширением: такой файл можно исполнить `bash файл`.
        write(root, "scripts/fragment.inc", self.BAD)
        write(root, ".codex/x.bash", self.BAD)
        write(root, "scripts/note.md", self.BAD)
        write(root, "scripts/fixture.txt", self.BAD)
        write(root, "scripts/helper.py", "#!/usr/bin/env python3\n" + self.BAD)
        write(root, "docs/out-of-scope.sh", self.BAD)
        write(root, ".claude/worktrees/other/scripts/a.sh", self.BAD)

    def flagged(self, root: Path) -> set[str]:
        return {v.split(":", 1)[0] for v in scan(root)[1]}

    EXPECTED = {
        "scripts/a.sh", "scripts/tool", ".claude/hooks/plain", "scripts/env-option",
        "scripts/env-joined", "scripts/env-quoted", "scripts/env-split",
        "scripts/fragment.inc", ".codex/x.bash",
    }

    def test_without_git_walks_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_tree(root)
            self.assertEqual(self.flagged(root), self.EXPECTED)

    def test_git_tree_includes_untracked_and_skips_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            self.make_tree(root)
            write(root, ".gitignore", "scripts/ignored.sh\n")
            write(root, "scripts/ignored.sh", self.BAD)
            subprocess.run(["git", "-C", str(root), "add", "scripts/a.sh"], check=True)
            self.assertEqual(self.flagged(root), self.EXPECTED)

    def test_hook_command_is_checked_and_windows_command_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hook = {"type": "command", "command": "bash -c 'echo «$x»'", "commandWindows": "echo «$x»"}
            write(root, ".codex/hooks.json", json.dumps({"hooks": {"PreToolUse": [{"hooks": [hook]}]}}, ensure_ascii=False))
            self.assertEqual(self.flagged(root), {".codex/hooks.json hooks.PreToolUse[0].hooks[0].command"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
