#!/usr/bin/env python3
"""og-cfx: уровень гейта коммита ограничен, полный reference-набор остаётся в /verify и CI."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'scripts/verify-reference.sh'
# Шаги, которые уровень гейта обязан пропустить: длинные интеграционные наборы установщика и Beads.
INTEGRATION = ('install-fresh-upgrade-rollback', 'install-helpers', 'bd-bootstrap-native', 'bd-sync',
               'bd-managed-routes')


def bash():
    sys.path.insert(0, str(ROOT / 'scripts/tests/lib'))
    from claude_hooks import native_bash
    return native_bash()


class VerifyTierTests(unittest.TestCase):
    def setUp(self):
        self.text = RUNNER.read_text(encoding='utf-8')

    def test_commit_tier_cut_precedes_every_integration_step(self):
        # Граница уровня стоит до первого интеграционного шага и после всех структурных/guard шагов.
        cut = self.text.index('if [ "$TIER" = commit ]')
        for label in INTEGRATION:
            self.assertGreater(self.text.index(f'run {label} '), cut, label)
        for label in ('structure', 'structural-mutations', 'closure-mutations', 'pre-bash-dispatch',
                      'mutation-guard', 'classifier', 'commit-gate', 'readiness', 'publisher'):
            self.assertLess(self.text.index(f'run {label} '), cut, label)

    def test_project_entrypoint_uses_commit_tier_and_ci_uses_full_suite(self):
        project = (ROOT / '.agents/project/verify.sh').read_text(encoding='utf-8')
        self.assertIn('scripts/verify-reference.sh" --commit-tier', project)
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        runs = re.findall(r'run: bash scripts/verify-reference\.sh(.*)', ci)
        self.assertGreaterEqual(len(runs), 2)
        for tail in runs:
            self.assertEqual(tail.strip(), '', 'CI must run the full reference suite')
        skill = (ROOT / '.claude/skills/verify/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('`bash scripts/verify-reference.sh`', skill)

    def test_unknown_argument_is_not_run(self):
        run = subprocess.run([bash(), str(RUNNER), '--fast'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('NOT RUN', run.stderr)
        self.assertNotIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
