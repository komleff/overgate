import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { guardPush } from '../lib/bd-publisher-push-guard.mjs';
import { appendOutcome, configureProjectPrefix, emptyLedger, prepareQueue } from '../lib/bd-managed-contract.mjs';
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

test('managed guard binds every snapshot transition to new authorized outcomes', () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-managed-preservation-')));
  try {
    git(root, 'init', '-q');
    git(root, 'config', 'user.name', 'fixture'); git(root, 'config', 'user.email', 'fixture@example.invalid');
    git(root, 'config', '--local', 'overgate.beadsPrefix', 'big-heroes');
    fs.mkdirSync(path.join(root, '.beads'));
    fs.writeFileSync(path.join(root, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
    configureProjectPrefix('big-heroes');
    const repo = new ManagedGit({ cwd: root, readIssuePrefix: () => 'big-heroes' });
    const issue = { _type: 'issue', id: 'big-heroes-A', title: 'Retained', status: 'open', priority: 2, issue_type: 'task' };
    const baseSnapshot = JSON.stringify(issue) + '\n';
    const base = repo.commitCandidate({ base: ZERO, snapshot: baseSnapshot, ledger: emptyLedger() });
    const config = { version: 1, mode: 'managed', repositoryRoot: root };
    const check = (candidate, remote = base) => guardPush({ config,
      input: Buffer.from(`refs/heads/beads-backup ${candidate} refs/heads/beads-backup ${remote}\n`), readIssuePrefix: () => 'big-heroes' });
    for (const snapshot of ['', JSON.stringify({ ...issue, title: 'Forged' }) + '\n']) {
      const candidate = repo.commitCandidate({ base, snapshot, ledger: emptyLedger() });
      assert.throws(() => check(candidate), /snapshot|outcome|preserv|postcondition/);
    }
    const actor = 'agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2';
    const [stale] = prepareQueue(JSON.stringify({ intent_id: 'stale-title', op: 'update', ref: issue.id, title: 'Forged' }),
      [{ ...issue, title: 'Old' }], emptyLedger(), { base, actor });
    const forged = repo.commitCandidate({ base, snapshot: JSON.stringify({ ...issue, title: 'Forged' }) + '\n',
      ledger: appendOutcome(emptyLedger(), stale, { ref: issue.id }) });
    assert.throws(() => check(forged), /precondition|conflict|stale/);
    const [intent] = prepareQueue(JSON.stringify({ intent_id: 'note-a', op: 'update', ref: issue.id, notes: 'Authorized' }),
      [issue], emptyLedger(), { base, actor });
    const ledger = appendOutcome(emptyLedger(), intent, { ref: issue.id });
    const valid = repo.commitCandidate({ base, snapshot: JSON.stringify({ ...issue, notes: 'Authorized' }) + '\n', ledger });
    assert.doesNotThrow(() => check(valid));
    const missing = repo.commitCandidate({ base, snapshot: '', ledger });
    assert.throws(() => check(missing), /snapshot|outcome|preserv|postcondition/);
    const noted = { ...issue, notes: 'Authorized' };
    const [closeIntent] = prepareQueue(JSON.stringify({ intent_id: 'close-a', op: 'close', ref: issue.id, close_reason: 'done' }),
      [noted], ledger, { base: valid, actor });
    const closed = { ...noted, status: 'closed', close_reason: 'done' };
    const closeLedger = appendOutcome(ledger, closeIntent, { ref: issue.id });
    const close = repo.commitCandidate({ base: valid, snapshot: JSON.stringify(closed) + '\n', ledger: closeLedger });
    assert.doesNotThrow(() => check(close, valid));
    const [reopenIntent] = prepareQueue(JSON.stringify({ intent_id: 'reopen-a', op: 'update', ref: issue.id,
      status: 'open', assignee: 'agent-other' }), [closed], closeLedger, { base: close, actor });
    const reopened = { ...closed, status: 'open', assignee: 'agent-other' };
    const reopenLedger = appendOutcome(closeLedger, reopenIntent, { ref: issue.id });
    const reopen = repo.commitCandidate({ base: close, snapshot: JSON.stringify(reopened) + '\n', ledger: reopenLedger });
    assert.doesNotThrow(() => check(reopen, close));
    const [staleClose] = prepareQueue(JSON.stringify({ intent_id: 'stale-close-a', op: 'close', ref: issue.id, close_reason: 'stale' }),
      [issue], emptyLedger(), { base, actor });
    const replay = repo.commitCandidate({ base: reopen, snapshot: JSON.stringify({ ...reopened, status: 'closed', close_reason: 'stale' }) + '\n',
      ledger: appendOutcome(reopenLedger, staleClose, { ref: issue.id }) });
    assert.throws(() => check(replay, reopen), /precondition|conflict|stale/);
    const [titleIntent] = prepareQueue(JSON.stringify({ intent_id: 'concurrent-title', op: 'update', ref: issue.id, title: 'Concurrent' }),
      [issue], emptyLedger(), { base, actor });
    const concurrent = { ...issue, title: 'Concurrent' };
    const concurrentLedger = appendOutcome(emptyLedger(), titleIntent, { ref: issue.id });
    const remoteTitle = repo.commitCandidate({ base, snapshot: JSON.stringify(concurrent) + '\n', ledger: concurrentLedger });
    assert.doesNotThrow(() => check(remoteTitle));
    const [localNotes] = prepareQueue(JSON.stringify({ intent_id: 'local-notes', op: 'update', ref: issue.id, notes: 'Local' }),
      [issue], emptyLedger(), { base, actor });
    const rebased = repo.commitCandidate({ base: remoteTitle, snapshot: JSON.stringify({ ...concurrent, notes: 'Local' }) + '\n',
      ledger: appendOutcome(concurrentLedger, localNotes, { ref: issue.id }) });
    assert.doesNotThrow(() => check(rebased, remoteTitle));
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
