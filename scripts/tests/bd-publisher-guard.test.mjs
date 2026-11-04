import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { guardPush } from '../lib/bd-publisher-push-guard.mjs';
import { configureProjectPrefix, emptyLedger } from '../lib/bd-managed-contract.mjs';
import { ManagedGit } from '../lib/bd-managed-git.mjs';

const ZERO = '0'.repeat(40);
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
test('retired checkout denies an old writer and a branch deletion', () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-retired-guard-')));
  try {
    git(root, 'init', '-q');
    git(root, 'config', 'user.name', 'fixture');
    git(root, 'config', 'user.email', 'fixture@example.invalid');
    fs.writeFileSync(path.join(root, 'tracked.txt'), 'base\n');
    git(root, 'add', 'tracked.txt'); git(root, 'commit', '-q', '-m', 'base');
    const base = git(root, 'rev-parse', 'HEAD');
    fs.writeFileSync(path.join(root, 'tracked.txt'), 'old writer\n');
    git(root, 'add', 'tracked.txt'); git(root, 'commit', '-q', '-m', 'old writer');
    const candidate = git(root, 'rev-parse', 'HEAD');
    const config = { version: 1, mode: 'retired', repositoryRoot: root };
    const record = (local, remote) => Buffer.from(`refs/heads/beads-backup ${local} refs/heads/beads-backup ${remote}\n`);
    assert.throws(() => guardPush({ config, input: record(candidate, base) }), /retired checkout cannot publish/);
    assert.throws(() => guardPush({ config, input: record(ZERO, base) }), /branch deletion denied/);
    assert.equal(guardPush({ config, input: Buffer.from(`refs/heads/main ${candidate} refs/heads/main ${base}\n`) }).length > 0, true);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('managed guard permits exact CAS activation and denies force or ledger downgrade', () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-managed-guard-')));
  try {
    git(root, 'init', '-q');
    git(root, 'config', 'user.name', 'fixture'); git(root, 'config', 'user.email', 'fixture@example.invalid');
    git(root, 'config', '--local', 'overgate.beadsPrefix', 'big-heroes');
    fs.mkdirSync(path.join(root, '.beads'));
    fs.writeFileSync(path.join(root, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
    configureProjectPrefix('big-heroes');
    const repo = new ManagedGit({ cwd: root, readIssuePrefix: () => 'big-heroes' });
    const activation = repo.commitCandidate({ base: ZERO, snapshot: '', ledger: emptyLedger() });
    const config = { version: 1, mode: 'managed', repositoryRoot: root };
    const record = (local, remote) => Buffer.from(`refs/heads/beads-backup ${local} refs/heads/beads-backup ${remote}\n`);
    assert.equal(guardPush({ config, input: record(activation, ZERO), readIssuePrefix: () => 'big-heroes' }).length > 0, true);
    assert.throws(() => guardPush({ config, input: record(activation, activation), readIssuePrefix: () => 'big-heroes' }), /sole parent/);
    const index = path.join(root, '.git', 'fixture-index');
    const indexed = (args, input) => execFileSync('git', args, { cwd: root, env: { ...process.env, GIT_INDEX_FILE: index }, input, encoding: 'utf8' }).trim();
    indexed(['read-tree', `${activation}^{tree}`]);
    indexed(['update-index', '--force-remove', '--', '.beads/overgate-outcomes-v1.json', '.beads/overgate-managed-v1.json']);
    const tree = indexed(['write-tree']);
    const downgraded = git(root, 'commit-tree', tree, '-p', activation, '-m', 'drop managed ledger');
    assert.throws(() => guardPush({ config, input: record(downgraded, activation), readIssuePrefix: () => 'big-heroes' }), /protocol|ledger|managed/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
