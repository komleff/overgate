// Disposable native qualification of the production CLI and publisher route.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { configureProjectPrefix } from '../lib/bd-managed-contract.mjs';
import { materializeFresh, qualifyBinary } from '../lib/bd-managed-cli.mjs';
import { parseSnapshot, assertExactSnapshot } from '../lib/bd-snapshot.mjs';
import { ManagedGit, ZERO } from '../lib/bd-managed-git.mjs';
import { preparePublisherControl, installPublisherControl } from '../bd-publisher-setup.mjs';

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const binary = fs.realpathSync(process.env.BD_BIN || '');
const expectedSha = process.env.BD_EXPECTED_SHA256;
const expectedPlatform = process.env.BD_EXPECTED_PLATFORM;
assert.equal(process.platform, expectedPlatform, 'native platform mismatch');
assert.match(expectedSha || '', /^[0-9a-f]{64}$/);
assert.equal(createHash('sha256').update(fs.readFileSync(binary)).digest('hex'), expectedSha, 'native binary hash mismatch');
assert.match(execFileSync(binary, ['--version'], { encoding: 'utf8' }), /\b1\.2\.2\b/);
assert.throws(() => qualifyBinary(binary, { fingerprint: () => '0'.repeat(64) }), /not qualified/);
assert.equal(qualifyBinary(binary), expectedSha, 'native production CLI must be qualified');

const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-linux-native-proof-')));
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const prefix = 'big-heroes', actor = 'agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2';
const issueId = raw => { const row = JSON.parse(raw); return Array.isArray(row) ? row[0].id : row.id; };
const fresh = name => { const directory = path.join(root, name); fs.mkdirSync(directory); return directory; };
try {
  configureProjectPrefix(prefix);
  const original = materializeFresh({ directory: fresh('full-original'), binary, actor, snapshot: '' });
  const parent = issueId(original.invoke(['create', '--title', 'Native parent', '--type', 'epic', '--priority', '1',
    '--description', 'Description retained', '--design', 'Design retained', '--acceptance', 'Acceptance retained',
    '--notes', 'Notes retained', '--labels', 'alpha,beta', '--metadata', '{"source":"linux-proof"}', '--json']));
  const child = issueId(original.invoke(['create', '--title', 'Native child', '--parent', parent, '--type', 'task', '--json']));
  assert.match(child, new RegExp(`^${parent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\.`), 'nested child ID required');
  original.invoke(['comments', 'add', child, 'Native comment', '--json']);
  original.invoke(['dep', 'add', parent, child, '--type', 'related']);
  original.invoke(['remember', 'Native memory retained', '--key', 'proof-memory']);
  const full = original.exportSnapshot();
  const rows = parseSnapshot(full).map(({ record }) => record);
  const parentRow = rows.find(row => row.id === parent), childRow = rows.find(row => row.id === child);
  assert.equal(parentRow.description, 'Description retained');
  assert.equal(parentRow.design, 'Design retained');
  assert.equal(parentRow.acceptance_criteria, 'Acceptance retained');
  assert.equal(parentRow.notes, 'Notes retained');
  assert.deepEqual(parentRow.labels, ['alpha', 'beta']);
  assert.equal(parentRow.metadata.source, 'linux-proof');
  assert(childRow.comments.some(comment => comment.text === 'Native comment'));
  assert(rows.some(row => row._type === 'memory' && row.key === 'proof-memory'));
  assert(rows.some(row => row.dependencies?.some(edge => edge.type === 'related')));
  const copied = materializeFresh({ directory: fresh('full-copy'), binary, actor, snapshot: full });
  assertExactSnapshot(full, copied.exportSnapshot());

  // Build a trusted project main containing only tracked source helpers, then
  // install the existing setup/guard in two disposable clones.
  const remote = path.join(root, 'remote.git'), seed = path.join(root, 'seed');
  const primary = path.join(root, 'primary'), publisher = path.join(root, 'publisher'), peerRoot = path.join(root, 'peer');
  git(root, 'init', '-q', '--bare', remote); git(root, 'init', '-q', '-b', 'main', seed);
  git(seed, 'config', 'user.name', 'fixture'); git(seed, 'config', 'user.email', 'fixture@example.invalid');
  const tracked = execFileSync('git', ['ls-files', '-z', 'scripts/bd-apply-intents.sh', 'scripts/bd-read.sh', 'scripts/bd-publisher-setup.mjs',
    'scripts/bd-sync-export.sh', 'scripts/bd-wt.sh', 'scripts/lib'], { cwd: source }).toString('utf8').split('\0').filter(Boolean);
  for (const name of tracked) {
    const target = path.join(seed, name); fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(source, name), target);
  }
  git(seed, 'add', '-A'); git(seed, 'commit', '-q', '-m', 'trusted exact source helpers');
  git(seed, 'remote', 'add', 'origin', remote); git(seed, 'push', '-q', 'origin', 'main');
  git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main');
  for (const clone of [primary, publisher, peerRoot]) git(root, 'clone', '-q', remote, clone);
  git(publisher, 'config', '--local', 'user.name', 'Fixture Publisher');
  git(publisher, 'config', '--local', 'user.email', 'fixture-publisher@example.invalid');
  assert.equal(git(publisher, 'config', '--local', '--get', 'user.name'), 'Fixture Publisher');
  const plan = path.join(root, 'setup-plan.json');
  const setup = { primaryRoot: primary, publisherRoot: publisher, qualifiedCli: binary, output: plan,
    readIssuePrefix: () => prefix };
  preparePublisherControl(setup);
  installPublisherControl(plan, { readIssuePrefix: () => prefix });
  const repository = new ManagedGit({ cwd: publisher });
  assert.equal(repository.readPublished().R, ZERO);
  const entry = (...args) => JSON.parse(execFileSync('bash', ['scripts/bd-apply-intents.sh', ...args],
    { cwd: publisher, env: { ...process.env, BD_BIN: binary }, encoding: 'utf8', stdio: ['pipe', 'pipe', 'inherit'] }));
  const preservation = path.join(publisher, '.git', 'overgate-bd-managed', 'preservation');
  fs.mkdirSync(preservation, { recursive: true });
  const manifest = path.join(preservation, 'preservation.json');
  fs.writeFileSync(manifest, JSON.stringify({ version: 1, base: ZERO, actor, outcome: 'verified-absent', artifacts: {} }));
  assert.equal(entry('--bootstrap', manifest).status, 'bootstrapped');
  const input = path.join(root, 'input.jsonl'), prepared = path.join(root, 'prepared.jsonl');
  fs.writeFileSync(input, [
    { intent_id: 'native-create', op: 'create', handle: 'tmp:task', title: 'Linux published task' },
    { intent_id: 'native-claim', op: 'claim', ref: 'tmp:task' },
  ].map(JSON.stringify).join('\n') + '\n');
  assert.equal(entry('--prepare', '--base', ZERO, '--actor', actor, '--output', prepared, input).status, 'prepared');
  const result = entry(prepared);
  assert.equal(result.status, 'published'); assert.match(result.published_sha, /^[0-9a-f]{40}$/);
  assert.equal(result.claims.length, 1); assert.equal(result.claims[0].confirmed, true);
  const taskId = result.claims[0].id; assert.match(taskId, /^big-heroes-[A-Za-z0-9.]+$/);
  git(peerRoot, 'config', '--local', 'overgate.beadsPrefix', prefix);
  fs.mkdirSync(path.join(peerRoot, '.beads'));
  fs.writeFileSync(path.join(peerRoot, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
  const peer = new ManagedGit({ cwd: peerRoot, readIssuePrefix: () => prefix }).readPublished();
  assert.equal(peer.R, result.published_sha);
  const peerRead = JSON.parse(execFileSync('bash', ['scripts/bd-read.sh', 'show', taskId, '--json'],
    { cwd: peerRoot, encoding: 'utf8', stdio: ['pipe', 'pipe', 'inherit'] }));
  assert.equal(peerRead.id, taskId);
  assert.equal(git(peerRoot, 'rev-parse', 'refs/remotes/origin/beads-backup'), result.published_sha);
  const task = parseSnapshot(peer.snapshot).map(({ record }) => record).find(row => row.id === taskId);
  assert.equal(task.status, 'in_progress'); assert.equal(task.assignee, actor);
  assert.equal(peer.ledger.outcomes.length, 2);
  console.log(JSON.stringify({ platform: process.platform, binary_sha256: expectedSha,
    source_sha: git(source, 'rev-parse', 'HEAD'), full_records: rows.length,
    task_id: taskId, published_sha: result.published_sha, peer_sha: peer.R, claim_confirmed: true }));
} finally { fs.rmSync(root, { recursive: true, force: true }); }
