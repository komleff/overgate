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
        path.write_text(path.read_text(encoding='utf-8').replace('.agents/skills/diagnose/SKILL.md', '.agents/skills/missing/SKILL.md'), encoding='utf-8')
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
        path.write_text(path.read_text(encoding='utf-8') + '\n| `diagnose` | `.agents/skills/diagnose/SKILL.md` | duplicate |\n', encoding='utf-8')
        self.check(1, 'SKILL-005')

    def test_unresolved_role_pointer(self):
        path = self.root / '.claude/agents/tester.md'
        path.write_text(path.read_text(encoding='utf-8').replace('.agents/QA_ROLE.md', '.agents/UNKNOWN_ROLE.md'), encoding='utf-8')
        self.check(1, 'ROLE-003')

    # og-bo6: шпаргалка оператора и роль проекта GD держатся структурной проверкой.
    def edit(self, rel, old, new):
        path = self.root / rel
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text, rel)
        path.write_text(text.replace(old, new), encoding='utf-8')

    def test_missing_gd_role(self):
        (self.root / '.agents/GD_ROLE.md').unlink()
        self.check(1, 'ROLE-001')

    def test_unregistered_gd_role(self):
        self.edit('.agents/AGENT_ROLES.md', '.agents/GD_ROLE.md', '.agents/GAME_DESIGN.md')
        self.check(1, 'ROLE-002')

    def test_unknown_extra_role(self):
        (self.root / '.agents/XX_ROLE.md').write_text('# extra\n', encoding='utf-8')
        self.check(1, 'ROLE-002')

    def test_missing_role_prompt_in_guide(self):
        for role in ('PM', 'SV', 'GD', 'PL', 'DEV', 'QA', 'RV'):
            with self.subTest(role=role):
                self.setUp()
                self.edit('.agents/HOW_TO_USE.md', f'Прочитай .agents/{role}_ROLE.md', 'Прочитай свою роль')
                self.check(1, 'GUIDE-001')

    def test_role_prompt_below_beads_section(self):
        path = self.root / '.agents/HOW_TO_USE.md'
        text = path.read_text(encoding='utf-8')
        prompt = 'Ты QA. Прочитай .agents/QA_ROLE.md.\n'
        self.assertIn(prompt, text)
        path.write_text(text.replace(prompt, '') + '\n```text\n' + prompt + '```\n', encoding='utf-8')
        self.check(1, 'GUIDE-001')

    def test_missing_guide(self):
        (self.root / '.agents/HOW_TO_USE.md').unlink()
        self.check(1, 'GUIDE-001')

    def test_renamed_beads_anchor_heading(self):
        self.edit('.agents/HOW_TO_USE.md', '## Beads: основной checkout, worktree и облачный агент', '## Beads')
        self.check(1, 'GUIDE-002')


if __name__ == '__main__':
    unittest.main()
