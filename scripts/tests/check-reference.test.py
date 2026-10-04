#!/usr/bin/env python3
"""Негативные fixtures structural contract AC-04; без runtime/LLM утверждений."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / 'scripts/check-reference.py'


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('.agents', '.claude/agents'):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.addCleanup(self.temp.cleanup)

    def check(self, expected, diagnostic=''):
        run = subprocess.run([sys.executable, str(CHECKER), '--root', str(self.root), '--structure-only'], capture_output=True, text=True)
        self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
        self.assertIn(diagnostic, run.stdout + run.stderr)

    def test_valid_reference(self):
        self.check(0)

    def test_missing_owner(self):
        (self.root / '.agents/QA_ROLE.md').unlink()
        self.check(1, 'ROLE-001')

    def test_dangling_registry(self):
        path = self.root / '.agents/SKILLS.md'
        path.write_text(path.read_text().replace('.agents/skills/diagnose/SKILL.md', '.agents/skills/missing/SKILL.md'))
        self.check(1, 'SKILL-002')

    def test_orphan_skill(self):
        path = self.root / '.agents/skills/orphan/SKILL.md'
        path.parent.mkdir()
        path.write_text('# orphan\n')
        self.check(1, 'SKILL-003')

    def test_nested_skill(self):
        path = self.root / '.agents/skills/diagnose/nested/SKILL.md'
        path.parent.mkdir()
        path.write_text('# nested\n')
        self.check(1, 'SKILL-004')

    def test_duplicate_membership(self):
        path = self.root / '.agents/SKILLS.md'
        path.write_text(path.read_text() + '\n| `diagnose` | `.agents/skills/diagnose/SKILL.md` | duplicate |\n')
        self.check(1, 'SKILL-005')

    def test_unresolved_role_pointer(self):
        path = self.root / '.claude/agents/tester.md'
        path.write_text(path.read_text().replace('.agents/QA_ROLE.md', '.agents/UNKNOWN_ROLE.md'))
        self.check(1, 'ROLE-003')


if __name__ == '__main__':
    unittest.main()
