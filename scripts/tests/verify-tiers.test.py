#!/usr/bin/env python3
"""og-cfx, ADR §3.38: commit tier — ядро пути коммита; полный набор остаётся в /verify и CI."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'scripts/verify-reference.sh'
CI = ROOT / '.github/workflows/ci.yml'
CUT = 'if [ "$TIER" = commit ]'
WINDOWS_JOB = 'windows-commit-tier'
# Точный состав по обе стороны границы: перенос шага через границу — осознанная правка теста.
COMMIT_TIER = [
    'structure', 'structural-mutations', 'closure-mutations', 'pre-bash-dispatch', 'portability-names',
    'activation', 'mutation-guard', 'classifier', 'commit-gate', 'readiness', 'python-launcher',
    'verify-tiers']
# Шаги прежнего commit tier (rc.5.1), вынесенные в full: обязаны остаться в full и в Windows CI.
MOVED = {
    'publisher', 'with-timeout', 'with-timeout-transparency', 'merge-gate-script-run-parity',
    'merge-gate-parse-completeness', 'merge-gate-parse-budget', 'gate-arithmetic-expansion',
    'gate-heredoc-delimiter', 'gate-line-continuation-parity', 'shell-grammar-single-source',
    'module-resolution-closure', 'finalize-triage-parse', 'finalize-gate-script', 'bd-node-path', 'bd-read',
    'bd-wt', 'merge-gate-parse-complexity', 'readiness-declaration-corpus', 'readiness-policy-complexity',
    'shell-nonascii-expansion', 'finalizer-validator', 'finalize-no-beads'}
INTEGRATION = {
    'install-fresh-upgrade-rollback', 'install-helpers', 'bd-bootstrap-native', 'bd-upgrade-preserve',
    'bd-legacy-fence', 'bd-sync', 'bd-managed-prefix', 'bd-managed-snapshot', 'bd-managed-two-clone',
    'bd-publisher-guard', 'bd-publisher-setup', 'bd-managed-routes'}


def bash():
    sys.path.insert(0, str(ROOT / 'scripts/tests/lib'))
    from claude_hooks import native_bash
    return native_bash()


def steps(text):
    # (номер строки, метка, исполняемый файл шага) в порядке файла: прямые `run <label>`
    # и имена из циклов `for test_name in ...` с шаблоном файла из тела цикла.
    found = []
    lines = text.splitlines()
    for number, line in enumerate(lines):
        loop = re.match(r'for test_name in (.+); do$', line)
        if loop:
            body = re.search(r'"(\S+)\$test_name(\.test\.\w+)"', lines[number + 1])
            found += [(number, name, body.group(1) + name + body.group(2)) for name in loop.group(1).split()]
        direct = re.match(r'run ([a-z0-9-]+) (.+)$', line)
        if direct and not direct.group(1).startswith('"'):
            script = next(word for word in direct.group(2).split() if '/' in word and '$' not in word)
            found.append((number, direct.group(1), script))
    return found


def job(text, name):
    match = re.search(rf'^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)', text, re.M | re.S)
    return match.group(1) if match else ''


class VerifyTierTests(unittest.TestCase):
    def setUp(self):
        self.text = RUNNER.read_text(encoding='utf-8')
        self.ci = CI.read_text(encoding='utf-8')
        cut = [i for i, line in enumerate(self.text.splitlines()) if line.startswith(CUT)]
        self.assertEqual(len(cut), 1, 'exactly one commit tier boundary')
        self.cut = cut[0]

    def test_commit_tier_is_exact_core(self):
        before = [name for number, name, _ in steps(self.text) if number < self.cut]
        self.assertEqual(before, COMMIT_TIER)

    def test_full_tier_keeps_every_moved_step(self):
        after = [name for number, name, _ in steps(self.text) if number > self.cut]
        self.assertEqual(len(after), len(set(after)))
        self.assertEqual(set(after), MOVED | INTEGRATION)
        self.assertEqual(len(MOVED) + len(COMMIT_TIER), 34, 'прежний commit tier rc.5.1 — 34 шага')

    def test_windows_job_runs_commit_tier_and_every_moved_step(self):
        windows = job(self.ci, WINDOWS_JOB)
        self.assertTrue(windows, f'CI job {WINDOWS_JOB} is missing')
        self.assertIn('bash .agents/project/verify.sh', windows)
        self.assertIn('timeout-minutes: 60', windows)
        self.assertIn("python-version: '3.14'", windows)
        self.assertNotIn('PYTHONUTF8: ', windows)
        self.assertNotIn('PYTHONIOENCODING: ', windows)
        scripts = {name: script for number, name, script in steps(self.text) if number > self.cut}
        for name in sorted(MOVED):
            with self.subTest(step=name):
                self.assertRegex(windows, rf'(?m)^\s+step {re.escape(name)} .*{re.escape(scripts[name])}\s*$')

    def test_project_entrypoint_uses_commit_tier_and_ci_uses_full_suite(self):
        project = (ROOT / '.agents/project/verify.sh').read_text(encoding='utf-8')
        self.assertIn('scripts/verify-reference.sh" --commit-tier', project)
        runs = re.findall(r'run: bash scripts/verify-reference\.sh(.*)', self.ci)
        self.assertGreaterEqual(len(runs), 2)
        for tail in runs:
            self.assertEqual(tail.strip(), '', 'CI must run the full reference suite')
        self.assertIn('run: bash scripts/verify-reference.sh', job(self.ci, 'verify-reference'))
        skill = (ROOT / '.claude/skills/verify/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('`bash scripts/verify-reference.sh`', skill)

    def test_run_prints_step_time_and_commit_tier_total(self):
        self.assertIn("printf 'PASS %s (%s s)\\n'", self.text)
        self.assertIn("printf 'commit tier steps total: %s s\\n'", self.text)

    def test_unknown_or_extra_argument_is_not_run(self):
        for args in (['--fast'], ['--commit-tier', 'extra'], ['']):
            with self.subTest(args=args):
                run = subprocess.run([bash(), str(RUNNER), *args], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace')
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn('NOT RUN', run.stderr)
                self.assertNotIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()
