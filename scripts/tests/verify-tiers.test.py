#!/usr/bin/env python3
"""og-cfx: уровень гейта коммита ограничен, полный reference-набор остаётся в /verify и CI."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'scripts/verify-reference.sh'
CUT = 'if [ "$TIER" = commit ]'
# Точный состав по обе стороны границы: перенос шага через границу — осознанная правка теста.
INTEGRATION = {
    'install-fresh-upgrade-rollback', 'install-helpers', 'bd-bootstrap-native', 'bd-upgrade-preserve',
    'bd-legacy-fence', 'bd-sync', 'bd-managed-prefix', 'bd-managed-snapshot', 'bd-managed-two-clone',
    'bd-publisher-guard', 'bd-publisher-setup', 'bd-managed-routes'}
COMMIT_TIER = {
    'structure', 'structural-mutations', 'closure-mutations', 'pre-bash-dispatch', 'portability-names',
    'activation', 'mutation-guard', 'classifier', 'commit-gate', 'readiness', 'publisher',
    'python-launcher', 'with-timeout', 'with-timeout-transparency', 'merge-gate-script-run-parity',
    'merge-gate-parse-completeness', 'merge-gate-parse-budget', 'gate-arithmetic-expansion',
    'gate-heredoc-delimiter', 'gate-line-continuation-parity', 'shell-grammar-single-source',
    'module-resolution-closure', 'finalize-triage-parse', 'finalize-gate-script', 'bd-node-path', 'bd-read',
    'bd-wt', 'merge-gate-parse-complexity', 'readiness-declaration-corpus', 'readiness-policy-complexity',
    'shell-nonascii-expansion', 'finalizer-validator', 'finalize-no-beads', 'verify-tiers'}


def bash():
    sys.path.insert(0, str(ROOT / 'scripts/tests/lib'))
    from claude_hooks import native_bash
    return native_bash()


def steps(text):
    # Метки шагов в порядке файла: прямые `run <label>` и имена из циклов `for test_name in ...`.
    found = []
    for number, line in enumerate(text.splitlines()):
        loop = re.match(r'for test_name in (.+); do$', line)
        if loop:
            found += [(number, name) for name in loop.group(1).split()]
        direct = re.match(r'run ([a-z0-9-]+) ', line)
        if direct:
            found.append((number, direct.group(1)))
    return found


class VerifyTierTests(unittest.TestCase):
    def setUp(self):
        self.text = RUNNER.read_text(encoding='utf-8')

    def test_commit_tier_boundary_is_exact(self):
        lines = self.text.splitlines()
        cut = [i for i, line in enumerate(lines) if line.startswith(CUT)]
        self.assertEqual(len(cut), 1, 'exactly one commit tier boundary')
        before = {name for number, name in steps(self.text) if number < cut[0]}
        after = {name for number, name in steps(self.text) if number > cut[0]}
        self.assertEqual(before, COMMIT_TIER)
        self.assertEqual(after, INTEGRATION)

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

    def test_unknown_or_extra_argument_is_not_run(self):
        for args in (['--fast'], ['--commit-tier', 'extra'], ['']):
            with self.subTest(args=args):
                run = subprocess.run([bash(), str(RUNNER), *args], capture_output=True, text=True)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn('NOT RUN', run.stderr)
                self.assertNotIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
