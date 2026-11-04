#!/usr/bin/env python3
"""Нативная проверка восстановления legacy Beads только в disposable Git-репозиториях."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2]
FILES = (
    'scripts/bd-bootstrap.sh', 'scripts/bd-sync-common.sh', 'scripts/bd-sync-export.sh',
    'scripts/bd-sync-restore.sh', 'scripts/lib/bd-env.sh',
    '.claude/tools/run-python.sh', '.agents/distribution-manifest.json',
)


def run(cwd, *args, env=None, check=True):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, encoding='utf-8',
                            capture_output=True)
    if check and result.returncode:
        raise AssertionError(f'{args}: {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result


def git(cwd, *args):
    return run(cwd, 'git', *args).stdout.strip()


def records(raw):
    return sorted((json.loads(line) for line in raw.splitlines() if line.strip()),
                  key=lambda row: json.dumps(row, sort_keys=True))


class NativeClone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('bd') or not re.match(r'^bd version 1\.2\.2(?: |$)',
                                                run(SOURCE, 'bd', '--version').stdout.strip()):
            raise unittest.SkipTest('native bd 1.2.2 unavailable')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='overgate-rc4-native-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.primary = self.root / 'primary'
        run(self.root, 'git', 'init', '-q', '--bare', str(self.remote))
        run(self.root, 'git', 'clone', '-q', str(self.remote), str(self.primary))
        git(self.primary, 'switch', '-q', '-c', 'main')
        self.configure(self.primary)
        for name in FILES:
            target = self.primary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, target)
        git(self.primary, 'add', '.')
        git(self.primary, 'commit', '-q', '-m', 'trusted helpers')
        git(self.primary, 'push', '-q', 'origin', 'main')
        git(self.remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        run(self.primary, 'bd', '--sandbox', 'init', '--prefix', 'big-heroes', '--skip-agents',
            '--skip-hooks', '--non-interactive', '--remote', '')
        first = run(self.primary, 'bd', '--sandbox', 'create', '--title', 'First', '--silent').stdout.strip()
        second = run(self.primary, 'bd', '--sandbox', 'create', '--title', 'Second', '--silent').stdout.strip()
        run(self.primary, 'bd', '--sandbox', 'dep', 'add', second, first)
        self.ids = (first, second)
        git(self.primary, 'push', '-q', 'origin', 'main')
        run(self.primary, 'bash', 'scripts/bd-sync-export.sh')
        self.base = git(self.primary, 'ls-remote', 'origin', 'refs/heads/beads-backup').split()[0]
        self.snapshot = git(self.primary, 'show', f'{self.base}:.beads/issues.jsonl')
        self.receipt = self.root / 'config-receipt.json'
        self.receipt.write_text(run(self.primary, 'bd', '--readonly', 'config', 'list', '--json').stdout,
                                encoding='utf-8')
        self.receipt_hash = hashlib.sha256(self.receipt.read_bytes()).hexdigest()

    @staticmethod
    def configure(root):
        git(root, 'config', 'user.name', 'fixture')
        git(root, 'config', 'user.email', 'fixture@example.invalid')

    def clone(self, name):
        target = self.root / name
        run(self.root, 'git', 'clone', '-q', str(self.remote), str(target))
        self.configure(target)
        return target

    def environment(self, **overrides):
        env = dict(os.environ, BD_BOOTSTRAP_PREFIX='big-heroes',
                   BD_BOOTSTRAP_PREFIX_RECEIPT=str(self.receipt),
                   BD_BOOTSTRAP_PREFIX_RECEIPT_SHA256=self.receipt_hash,
                   BD_BOOTSTRAP_EXPECTED_R=self.base)
        env.update(overrides)
        return env

    def test_clean_fresh_helper_commits_only_beads_and_publishes_snapshot(self):
        remote = self.root / 'fresh-remote.git'
        target = self.root / 'fresh-project'
        run(self.root, 'git', 'init', '-q', '--bare', str(remote))
        run(self.root, 'git', 'clone', '-q', str(remote), str(target))
        git(target, 'switch', '-q', '-c', 'main')
        self.configure(target)
        for name in FILES:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, destination)
        git(target, 'add', '.')
        git(target, 'commit', '-q', '-m', 'trusted install source')
        git(target, 'push', '-q', 'origin', 'main')
        git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        (target / 'untracked-sentinel.txt').write_bytes(b'untouched project bytes\n')
        result = run(target, 'bash', 'scripts/bd-bootstrap.sh', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('bd init:', git(target, 'log', '-1', '--format=%s'))
        committed = git(target, 'show', '--format=', '--name-only', 'HEAD').splitlines()
        self.assertTrue(committed)
        self.assertTrue(all(name.startswith('.beads/') or name == '.gitignore' for name in committed), committed)
        self.assertNotIn('untracked-sentinel.txt', committed)
        self.assertEqual((target / 'untracked-sentinel.txt').read_bytes(), b'untouched project bytes\n')
        self.assertTrue(git(target, 'ls-remote', 'origin', 'refs/heads/beads-backup'))

    def test_clone_restores_full_snapshot_without_git_or_metadata_change(self):
        target = self.clone('arbitrary-clone-name')
        metadata = (target / '.beads/metadata.json').read_bytes()
        config = (target / '.beads/config.yaml').read_bytes()
        index_path = target / git(target, 'rev-parse', '--git-path', 'index')
        index = index_path.read_bytes()
        head = git(target, 'rev-parse', 'HEAD')
        result = run(target, 'bash', 'scripts/bd-bootstrap.sh', env=self.environment(), check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), head)
        self.assertEqual((target / '.beads/metadata.json').read_bytes(), metadata)
        self.assertEqual((target / '.beads/config.yaml').read_bytes(), config)
        self.assertEqual(index_path.read_bytes(), index)
        self.assertEqual(git(target, 'config', '--local', '--get', 'beads-sync.lastSeen'), self.base)
        self.assertEqual(git(target, 'ls-remote', 'origin', 'refs/heads/beads-backup').split()[0], self.base)
        self.assertEqual(json.loads(run(target, 'bd', '--readonly', 'config', 'get', 'issue_prefix', '--json').stdout)['value'], 'big-heroes')
        self.assertEqual(json.loads(run(target, 'bd', '--readonly', 'dolt', 'remote', 'list', '--json').stdout), [])
        export = self.root / 'restored.jsonl'
        run(target, 'bd', '--sandbox', 'export', '--all', '-o', str(export))
        self.assertEqual(records(export.read_text()), records(self.snapshot))
        self.assertEqual({row['id'] for row in records(export.read_text()) if row.get('_type') == 'issue'}, set(self.ids))

    def test_unknown_and_wrong_prefix_refuse_before_database_creation(self):
        for name, env in (
            ('unknown', dict(BD_BOOTSTRAP_PREFIX='')),
            ('wrong', dict(BD_BOOTSTRAP_PREFIX='other')),
            ('receipt-hash', dict(BD_BOOTSTRAP_PREFIX_RECEIPT_SHA256='0' * 64)),
            ('advanced', dict(BD_BOOTSTRAP_EXPECTED_R='0' * 40)),
        ):
            with self.subTest(name=name):
                target = self.clone(name)
                head = git(target, 'rev-parse', 'HEAD')
                result = run(target, 'bash', 'scripts/bd-bootstrap.sh', env=self.environment(**env), check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((target / '.beads/embeddeddolt').exists())
                self.assertEqual(git(target, 'rev-parse', 'HEAD'), head)
                self.assertEqual(git(target, 'ls-remote', 'origin', 'refs/heads/beads-backup').split()[0], self.base)
        missing = self.root / 'missing.git'
        run(self.root, 'git', 'init', '-q', '--bare', str(missing))
        git(self.primary, 'push', str(missing), 'main:main')
        target = self.clone('missing-remote-snapshot')
        git(target, 'remote', 'set-url', 'origin', str(missing))
        result = run(target, 'bash', 'scripts/bd-bootstrap.sh', env=self.environment(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('STOP:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((target / '.beads/embeddeddolt').exists())

    def test_active_tracked_prefix_restores_without_external_receipt(self):
        config = self.primary / '.beads/config.yaml'
        config.write_text(config.read_text(encoding='utf-8') + '\nissue-prefix: big-heroes\n', encoding='utf-8')
        git(self.primary, 'add', '.beads/config.yaml')
        git(self.primary, 'commit', '-q', '-m', 'project owned prefix')
        git(self.primary, 'push', '-q', 'origin', 'main')
        target = self.clone('tracked-prefix-clone')
        result = run(target, 'bash', 'scripts/bd-bootstrap.sh',
                     env=self.environment(BD_BOOTSTRAP_PREFIX='', BD_BOOTSTRAP_PREFIX_RECEIPT='',
                                          BD_BOOTSTRAP_PREFIX_RECEIPT_SHA256=''), check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(run(target, 'bd', '--readonly', 'config', 'get', 'issue_prefix', '--json').stdout)['value'], 'big-heroes')
        self.assertEqual(git(target, 'config', '--local', '--get', 'beads-sync.lastSeen'), self.base)

    def test_existing_unsynced_local_database_is_preserved(self):
        target = self.clone('local-pending')
        run(target, 'bd', '--sandbox', 'init', '--prefix', 'big-heroes', '--skip-agents',
            '--skip-hooks', '--non-interactive', '--remote', '')
        local_id = run(target, 'bd', '--sandbox', 'create', '--title', 'Local pending', '--silent').stdout.strip()
        before = self.root / 'local-before.jsonl'
        after = self.root / 'local-after.jsonl'
        run(target, 'bd', '--sandbox', 'export', '--all', '-o', str(before))
        result = run(target, 'bash', 'scripts/bd-bootstrap.sh', env=self.environment(), check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        run(target, 'bd', '--sandbox', 'export', '--all', '-o', str(after))
        self.assertEqual(records(after.read_text()), records(before.read_text()))
        self.assertEqual({row['id'] for row in records(after.read_text()) if row.get('_type') == 'issue'}, {local_id})
        self.assertEqual(git(target, 'ls-remote', 'origin', 'refs/heads/beads-backup').split()[0], self.base)

    def test_staged_pending_unknown_and_corrupt_state_refuse_before_init(self):
        for name in ('staged', 'pending', 'unknown-file', 'unsupported-mode', 'force-override'):
            with self.subTest(name=name):
                target = self.clone(name)
                env = self.environment()
                if name == 'staged':
                    (target / 'sentinel.txt').write_bytes(b'project bytes\n')
                    git(target, 'add', 'sentinel.txt')
                elif name == 'pending':
                    (target / '.bd-intents').mkdir()
                    (target / '.bd-intents/queue.jsonl').write_text('{"op":"create"}\n')
                elif name == 'unknown-file':
                    (target / '.beads/local-only').write_bytes(b'pending local state')
                elif name == 'unsupported-mode':
                    metadata = target / '.beads/metadata.json'
                    value = json.loads(metadata.read_text())
                    value['dolt_mode'] = 'server'
                    metadata.write_text(json.dumps(value))
                else:
                    env['BD_SYNC_FORCE'] = '1'
                head = git(target, 'rev-parse', 'HEAD')
                index = (target / git(target, 'rev-parse', '--git-path', 'index')).read_bytes()
                result = run(target, 'bash', 'scripts/bd-bootstrap.sh', env=env, check=False)
                self.assertNotEqual(result.returncode, 0, name + result.stdout + result.stderr)
                self.assertFalse((target / '.beads/embeddeddolt').exists(), name)
                self.assertEqual(git(target, 'rev-parse', 'HEAD'), head)
                self.assertEqual((target / git(target, 'rev-parse', '--git-path', 'index')).read_bytes(), index)

        index = self.root / 'corrupt-index'
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        parent = self.base
        invalid_rows = (
            ('syntax', '{not json}\n'),
            ('type', '{"_type":"future","id":"big-heroes-x"}\n'),
            ('edge', '{"_type":"issue","id":"big-heroes-x","title":"x","status":"open","priority":2,"issue_type":"task","dependencies":[{"issue_id":"big-heroes-x","depends_on_id":"big-heroes-missing","type":"alien"}]}\n'),
        )
        for name, body in invalid_rows:
            invalid = self.root / f'{name}.jsonl'
            invalid.write_text(body, encoding='utf-8')
            run(self.primary, 'git', 'read-tree', f'{parent}^{{tree}}', env=env)
            blob = git(self.primary, 'hash-object', '-w', str(invalid))
            run(self.primary, 'git', 'update-index', '--add', '--cacheinfo',
                f'100644,{blob},.beads/issues.jsonl', env=env)
            tree = run(self.primary, 'git', 'write-tree', env=env).stdout.strip()
            corrupt = git(self.primary, 'commit-tree', tree, '-p', parent, '-m', f'{name} snapshot')
            git(self.primary, 'push', 'origin', f'{corrupt}:refs/heads/beads-backup')
            target = self.clone(name)
            result = run(target, 'bash', 'scripts/bd-bootstrap.sh',
                         env=self.environment(BD_BOOTSTRAP_EXPECTED_R=corrupt), check=False)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((target / '.beads/embeddeddolt').exists(), name)
            self.assertEqual(git(target, 'ls-remote', 'origin', 'refs/heads/beads-backup').split()[0], corrupt)
            parent = corrupt


if __name__ == '__main__':
    unittest.main()
