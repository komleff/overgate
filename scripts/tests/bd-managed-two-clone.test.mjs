import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { appendOutcome, configureProjectPrefix, emptyLedger, prepareQueue, planReplay } from '../lib/bd-managed-contract.mjs';
import { ManagedGit, ZERO } from '../lib/bd-managed-git.mjs';
import { runTransaction } from '../lib/bd-managed-transaction.mjs';

const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-managed-two-clone-')));
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const gitInput = (cwd, input, ...args) => execFileSync('git', args, { cwd, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const actor = 'agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2';
try {
  const remote = path.join(root, 'remote.git');
  const first = path.join(root, 'first');
  const second = path.join(root, 'second');
  git(root, 'init', '-q', '--bare', remote);
  git(root, 'clone', '-q', remote, first);
  git(root, 'clone', '-q', remote, second);
  for (const cwd of [first, second]) {
    git(cwd, 'config', 'user.name', 'fixture');
    git(cwd, 'config', 'user.email', 'fixture@example.invalid');
    git(cwd, 'config', '--local', 'overgate.beadsPrefix', 'big-heroes');
    fs.mkdirSync(path.join(cwd, '.beads'));
    fs.writeFileSync(path.join(cwd, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
    fs.writeFileSync(path.join(cwd, '.beads/config.yaml'), '# issue-prefix: "example"\n');
  }
  configureProjectPrefix('big-heroes');
  const project = cwd => new ManagedGit({ cwd, readIssuePrefix: () => 'big-heroes' });
  const publisher = project(first);
  assert.equal(publisher.readPublished().R, ZERO);
  const raw = [
    { intent_id: 'create-one', op: 'create', handle: 'tmp:new', title: 'Fixture task' },
    { intent_id: 'claim-one', op: 'claim', ref: 'tmp:new' },
  ].map(JSON.stringify).join('\n');
  const queue = prepareQueue(raw, [], emptyLedger(), { base: ZERO, actor });
  const directory = path.join(first, '.git', 'overgate-bd-managed');
  const acknowledgement = { version: 1, base: ZERO, actor, outcome: 'verified-absent' };
  const materialize = snapshot => {
    assert.equal(snapshot, '');
    const rows = [];
    return {
      rows: [], actor,
      invoke: args => {
        if (args[0] === 'create') {
          rows.push({ _type: 'issue', id: 'big-heroes-A', title: 'Fixture task', issue_type: 'task', priority: 2, status: 'open', external_ref: 'intent:create-one' });
          return JSON.stringify({ id: 'big-heroes-A' });
        }
        if (args[0] === 'update' && args.includes('--claim')) {
          rows[0].status = 'in_progress'; rows[0].assignee = actor; rows[0].started_at = '2026-11-04T00:00:00Z';
          return JSON.stringify(rows[0]);
        }
        throw new Error(`unexpected CLI call: ${args.join(' ')}`);
      },
      exportSnapshot: () => rows.map(JSON.stringify).join('\n') + '\n',
    };
  };
  const failOnce = Object.create(publisher);
  failOnce.pushCandidate = () => { throw new Error('synthetic transport outage'); };
  assert.throws(() => runTransaction({ repository: failOnce, directory, intents: queue, acknowledgement, materialize }),
    error => error.code === 'PENDING_PUBLICATION' && error.summary.status === 'pending');
  assert.equal(publisher.readPublished().R, ZERO);
  const resumedPublisher = project(first);
  const published = runTransaction({ repository: resumedPublisher, directory, intents: queue, acknowledgement,
    materialize: () => { throw new Error('retry repeated CLI mutations'); } });
  assert.equal(published.status, 'published');
  assert.equal(published.mutations, 0);
  assert.match(published.published_sha, /^[0-9a-f]{40}$/);
  assert.equal(published.outcomes[0].result.ref, 'big-heroes-A');
  assert.deepEqual(published.claims, [{ id: 'big-heroes-A', actor, status: 'in_progress', assignee: actor, confirmed: true }]);
  const peer = project(second).readPublished();
  assert.equal(peer.R, published.published_sha);
  assert.equal(peer.ledger.outcomes.length, 2);
  assert.equal(peer.ledger.outcomes[0].result.ref, 'big-heroes-A');
  assert.equal(JSON.parse(peer.snapshot.trim()).assignee, actor);
  const forgedLoss = publisher.commitCandidate({ base: published.published_sha, snapshot: '', ledger: peer.ledger });
  publisher.pushCandidate(forgedLoss);
  assert.throws(() => project(second).readPublished(), /snapshot|outcome|preserv|postcondition/);
  git(root, '--git-dir', remote, 'update-ref', 'refs/heads/beads-backup', published.published_sha);
  assert.equal(runTransaction({ repository: publisher, directory, intents: queue, acknowledgement, materialize: () => { throw new Error('replay called CLI'); } }).mutations, 0);
  const updateCandidate = (intent_id, title) => {
    const [intent] = prepareQueue(JSON.stringify({ intent_id, op: 'update', ref: 'big-heroes-A', title }),
      [JSON.parse(peer.snapshot.trim())], peer.ledger, { base: published.published_sha, actor });
    return publisher.commitCandidate({ base: published.published_sha,
      snapshot: peer.snapshot.replace('Fixture task', title),
      ledger: appendOutcome(peer.ledger, intent, { ref: 'big-heroes-A' }) });
  };
  const stale = updateCandidate('stale-title', 'stale task');
  const newer = updateCandidate('newer-title', 'newer task');
  publisher.pushCandidate(newer);
  assert.throws(() => publisher.pushCandidate(stale));
  assert.equal(project(second).readPublished().R, newer);
  const changed = JSON.parse(peer.snapshot.trim()); changed.title = 'remote title';
  const competing = prepareQueue(JSON.stringify({ intent_id: 'competing-title', op: 'update', ref: 'big-heroes-A', title: 'local title' }),
    [JSON.parse(peer.snapshot.trim())], peer.ledger, { base: published.published_sha, actor });
  assert.equal(planReplay(competing, [changed], peer.ledger).conflicts[0].field, 'title');
  const unrelated = prepareQueue(JSON.stringify({ intent_id: 'unrelated-notes', op: 'update', ref: 'big-heroes-A', notes: 'local notes' }),
    [JSON.parse(peer.snapshot.trim())], peer.ledger, { base: published.published_sha, actor });
  assert.equal(planReplay(unrelated, [changed], peer.ledger).conflicts.length, 0);
  const staleClose = prepareQueue(JSON.stringify({ intent_id: 'stale-close', op: 'close', ref: 'big-heroes-A', close_reason: 'done' }),
    [JSON.parse(peer.snapshot.trim())], peer.ledger, { base: published.published_sha, actor });
  const reassigned = { ...JSON.parse(peer.snapshot.trim()), status: 'open', assignee: 'agent-other' };
  assert.notEqual(planReplay(staleClose, [reassigned], peer.ledger).conflicts.length, 0);
  git(second, 'config', '--local', 'overgate.beadsPrefix', 'wrong');
  assert.throws(() => project(second), /prefix registration mismatch/);
  git(second, 'config', '--local', 'overgate.beadsPrefix', 'big-heroes');
  assert.throws(() => publisher.commitCandidate({ base: newer, snapshot: '{bad json\n', ledger: peer.ledger }), /invalid|невалидн/);
  const oldBlob = gitInput(first, peer.snapshot, 'hash-object', '-w', '--stdin');
  const oldBeadsTree = gitInput(first, `100644 blob ${oldBlob}\tissues.jsonl\n`, 'mktree');
  const oldTree = gitInput(first, `040000 tree ${oldBeadsTree}\t.beads\n`, 'mktree');
  const downgraded = git(first, 'commit-tree', oldTree, '-p', newer, '-m', 'synthetic old writer');
  git(first, 'push', '-q', 'origin', `${downgraded}:refs/heads/beads-backup`);
  assert.throws(() => project(second).readPublished(), /downgrade|ledger|protocol/);
  console.log(JSON.stringify({ id: published.outcomes[0].result.ref, published_sha: published.published_sha, peer_sha: peer.R, claims: published.claims }));
} finally { fs.rmSync(root, { recursive: true, force: true }); }
