#!/usr/bin/env python3
"""Поведение commit fast path; проверка действительного project verify entrypoint."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CommitGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('hooks', 'tools'):
            shutil.copytree(ROOT / '.claude' / name, self.root / '.claude' / name)
        self.verify = self.root / '.agents/project/verify.sh'
        self.verify.parent.mkdir(parents=True)
        self.verify.write_text('#!/usr/bin/env bash\nprintf called > "$VERIFY_MARKER"\nexit 7\n')
        self.marker = self.root / 'called'
        self.env = dict(os.environ, VERIFY_MARKER=str(self.marker))

    def run_hook(self, command, expected):
        result = subprocess.run(['bash', str(self.root / '.claude/hooks/check-tests-before-commit.sh')],
            input=json.dumps({'tool_input': {'command': command}}), text=True, capture_output=True,
            env=self.env, cwd=self.root)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_ordinary_no_suite(self):
        self.run_hook('git status --short', 0)
        self.assertFalse(self.marker.exists())

    def test_ambiguous_blocks_without_suite(self):
        self.run_hook('eval "$UNKNOWN"', 2)
        self.assertFalse(self.marker.exists())

    def test_exact_commit_runs_failing_suite(self):
        self.run_hook('git -c user.name=Tester commit -m x', 2)
        self.assertTrue(self.marker.exists())

    def test_passing_suite_allows(self):
        self.verify.write_text('#!/usr/bin/env bash\nexit 0\n')
        self.run_hook('git commit -m x', 0)

    def test_missing_verify_blocks(self):
        self.verify.unlink()
        self.run_hook('git commit -m x', 2)

    def test_missing_classifier_blocks(self):
        (self.root / '.claude/hooks/commit_command_classifier.py').unlink()
        self.run_hook('git status', 2)

    def test_timeout_blocks(self):
        self.env['OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS'] = '1'
        self.verify.write_text('#!/usr/bin/env bash\nsleep 10\n')
        self.run_hook('git commit -m x', 2)


if __name__ == '__main__':
    unittest.main()
