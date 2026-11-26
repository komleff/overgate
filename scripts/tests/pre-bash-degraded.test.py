#!/usr/bin/env python3
"""Деградированный режим диспетчера вживую (ADR §3.40, план v4.0.1 V1, V2, V6–V8).

Каждый сценарий ждёт истечения предела быстрой фазы, поэтому шаг идёт только в полном
наборе (/verify, CI Linux/macOS и Windows-джоба windows-commit-tier), а не в commit tier:
рост гейта коммита на Windows иначе выходил за бюджет (AC-4). Правило триажа целиком
проверяет корпус вердиктов в commit tier (pre-bash-dispatch.test.py, SlowEnvironmentTriage).

Помощники (запись ENTRY, временные деревья, Git Bash) — из pre-bash-dispatch.test.py.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "pre_bash_dispatch", Path(__file__).resolve().parent / "pre-bash-dispatch.test.py")
dispatch = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dispatch)

ROOT, ENTRY, BASH, WINDOWS = dispatch.ROOT, dispatch.ENTRY, dispatch.BASH, dispatch.WINDOWS
run, make_tree, gate_tree = dispatch.run, dispatch.make_tree, dispatch.gate_tree

SLEEPING_STUB = "import time\ntime.sleep(30)\n"


class SlowEnvironmentDispatch(unittest.TestCase):
    """Быстрая проверка не укладывается в предел: статичная команда проходит, прочие — блок (V1, V2, V8)."""

    @classmethod
    def setUpClass(cls):
        cls.tree = make_tree(mutation=("QUICK_LIMIT=10", "QUICK_LIMIT=1"))
        (cls.tree / ".claude" / "hooks" / "check-repository-mutation.py").write_text(SLEEPING_STUB, encoding="utf-8")

    def test_static_command_passes_with_warning(self):
        started = time.monotonic()
        code, err = run(ENTRY, "ls -la", self.tree, str(self.tree), timeout=40)
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0, err)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", err)
        self.assertLessEqual(elapsed, 10, f"деградированный режим занял {elapsed:.1f} с")

    def test_guarded_command_is_blocked_with_honest_reason(self):
        """Честная причина и, вне Windows, подсказка iCloud по заглушкам uname (Darwin) и stat
        (dataless) в PATH; на Windows заглушек нет — и подсказки нет."""
        with tempfile.TemporaryDirectory(prefix="overgate-icloud-stub-") as directory:
            env = None
            if not WINDOWS:
                stubs = Path(directory)
                for name, text in (("uname", "echo Darwin"), ("stat", "echo hidden,compressed,dataless")):
                    stub = stubs / name
                    stub.write_text("#!/bin/sh\n" + text + "\n", encoding="utf-8", newline="\n")
                    stub.chmod(0o755)
                env = {"PATH": str(stubs) + os.pathsep + os.environ.get("PATH", "")}
            code, err = run(ENTRY, "git push origin main", self.tree, str(self.tree), env, timeout=40)
        self.assertEqual(code, 2, err)
        self.assertIn("не уложилась", err)
        self.assertIn("медленное окружение", err)
        self.assertIn("ls cat head", err)
        self.assertNotIn("checkout -- .claude/hooks", err)
        if WINDOWS:
            self.assertNotIn("iCloud", err)
        else:
            self.assertIn("iCloud", err)


class SlowGateLimitQuery(unittest.TestCase):
    """Зависший запрос предела гейта: статичная команда проходит, коммит блокируется (V6)."""

    def test_static_command_passes_commit_is_blocked(self):
        query = 'GATE_BASE="$(sh "$TIMEOUT_HELPER"'
        tree = gate_tree("#!/usr/bin/env bash\nsleep 30\nexit 0\n", (query, f"QUICK_LIMIT=2\n{query}"))
        code, err = run(ENTRY, "ls -la", tree, str(tree), timeout=25)
        self.assertEqual(code, 0, err)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", err)
        code, err = run(ENTRY, "git commit -m x", tree, str(tree), timeout=25)
        self.assertEqual(code, 2, err)
        self.assertIn("не сообщил предел", err)


class SlowCommitGateClassifier(unittest.TestCase):
    """Классификатор гейта коммита не укладывается в предел: вердикт даёт триаж диспетчера (V7)."""

    @classmethod
    def setUpClass(cls):
        cls.tree = Path(tempfile.mkdtemp(prefix="overgate-gate-slow-"))
        for sub in ("hooks", "tools"):
            shutil.copytree(ROOT / ".claude" / sub, cls.tree / ".claude" / sub,
                            ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
        (cls.tree / ".claude" / "hooks" / "commit_command_classifier.py").write_text(SLEEPING_STUB, encoding="utf-8")
        cls.gate_path = (cls.tree / ".claude" / "hooks" / "check-tests-before-commit.sh").as_posix()

    def gate(self, command: str) -> tuple[int, str]:
        env = dict(os.environ, OVERGATE_COMMIT_GATE_TEST_MAX_CLASSIFY_SECONDS="1",
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        env.pop("OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS", None)
        proc = subprocess.run([BASH, self.gate_path], input=json.dumps({"tool_input": {"command": command}}),
                              cwd=str(self.tree), env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=40)
        return proc.returncode, proc.stderr

    def test_static_command_passes(self):
        code, err = self.gate("ls -la")
        self.assertEqual(code, 0, err)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", err)

    def test_commit_is_blocked(self):
        code, err = self.gate("git commit -m x")
        self.assertEqual(code, 2, err)
        self.assertIn("не уложился", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
