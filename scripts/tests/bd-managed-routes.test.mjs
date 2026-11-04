import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { appendOutcome, configureProjectPrefix, emptyLedger, prepareQueue } from '../lib/bd-managed-contract.mjs';
import { ManagedGit, ZERO } from '../lib/bd-managed-git.mjs';

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const run = (cwd, script, args = [], env = {}) => spawnSync('bash', [path.join(source, 'scripts', script), ...args],
  { cwd, env: { ...process.env, ...env }, encoding: 'utf8' });

test('managed reader/worktree use published snapshot and both legacy sync writers stop', () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-managed-routes-')));
  try {
    const remote = path.join(root, 'remote.git'), main = path.join(root, 'main'), linked = path.join(root, 'linked'), other = path.join(root, 'other');
    git(root, 'init', '-q', '--bare', remote); git(root, 'clone', '-q', remote, main);
    git(main, 'config', 'user.name', 'fixture'); git(main, 'config', 'user.email', 'fixture@example.invalid');
    git(main, 'switch', '-q', '-c', 'main'); fs.writeFileSync(path.join(main, 'README.md'), 'fixture\n');
    git(main, 'add', 'README.md'); git(main, 'commit', '-q', '-m', 'main'); git(main, 'push', '-q', 'origin', 'main');
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main');
    git(main, 'worktree', 'add', '-q', '-b', 'feature', linked);
    git(root, 'clone', '-q', remote, other);
    git(main, 'config', '--local', 'overgate.beadsPublisher', main);
    git(main, 'config', '--local', 'overgate.beadsPrefix', 'big-heroes');
    fs.mkdirSync(path.join(main, '.beads'));
    fs.writeFileSync(path.join(main, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
    configureProjectPrefix('big-heroes');
    const publisher = new ManagedGit({ cwd: main, readIssuePrefix: () => 'big-heroes' });
    const activation = publisher.commitCandidate({ base: ZERO, snapshot: '', ledger: emptyLedger() });
    publisher.pushCandidate(activation);
    const actor = 'agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2';
    const [create] = prepareQueue(JSON.stringify({ intent_id: 'fixture-create', op: 'create', handle: 'tmp:task', title: 'Published task' }),
      [], emptyLedger(), { base: activation, actor });
    const issue = { _type: 'issue', id: 'big-heroes-A', title: 'Published task', status: 'open',
      priority: 2, issue_type: 'task', external_ref: 'intent:fixture-create', dependency_count: 0 };
    const snapshot = JSON.stringify(issue) + '\n';
    const ledger = appendOutcome(emptyLedger(), create, { ref: issue.id, handles: { 'tmp:task': issue.id } });
    const published = publisher.commitCandidate({ base: activation, snapshot, ledger });
    publisher.pushCandidate(published);
    const conversionBin = path.join(root, 'conversion-bin'); fs.mkdirSync(conversionBin);
    const realGit = execFileSync('which', ['git'], { encoding: 'utf8' }).trim();
    const conversionGit = path.join(conversionBin, 'git');
    fs.writeFileSync(conversionGit, `#!/bin/sh
if [ "\${1:-}" = show ]; then case "\${2:-}" in origin/*:*) exit 128;; esac; fi
if [ "\${1:-}" = cat-file ] && [ "\${2:-}" = -e ]; then case "\${3:-}" in refs/remotes/*:*) exit 128;; esac; fi
exec "$OG_TEST_REAL_GIT" "$@"
`); fs.chmodSync(conversionGit, 0o755);
    const conversionEnv = { PATH: `${conversionBin}${path.delimiter}${process.env.PATH}`, OG_TEST_REAL_GIT: realGit };
    const convertedRead = run(linked, 'bd-read.sh', ['ready', '--json'], conversionEnv);
    assert.equal(convertedRead.status, 0, convertedRead.stderr);
    assert.match(convertedRead.stdout, /big-heroes-A/);
    const convertedLegacy = run(other, 'bd-sync-export.sh', [], conversionEnv);
    assert.notEqual(convertedLegacy.status, 0);
    assert.match(convertedLegacy.stderr, /remote managed protocol активен/);
    const stubLog = path.join(root, 'bd-stub.log'), stub = path.join(root, 'bd-stub.sh');
    fs.writeFileSync(stub, `#!/bin/sh\nif [ "$*" = '--readonly config list --json' ]; then printf '%s\\n' '{"issue_prefix":"big-heroes"}'; exit 0; fi\nprintf '%s\\n' "$*" >> '${stubLog}'\nexit 0\n`); fs.chmodSync(stub, 0o755);
    git(main, 'config', '--local', 'overgate.beadsCli', stub);
    const foreignHelper = run(main, 'bd-apply-intents.sh', ['--read-state']);
    assert.notEqual(foreignHelper.status, 0, 'PR-branch helper path cannot execute against trusted target main');
    assert.match(foreignHelper.stderr, /trusted publisher helper path|tracked publisher tooling/);
    const env = { BD_BIN: stub };
    const read = run(linked, 'bd-read.sh', ['ready', '--json']);
    assert.equal(read.status, 0, read.stderr); assert.match(read.stdout, /big-heroes-A/);
    const primaryRead = run(main, 'bd-read.sh', ['ready', '--json']);
    assert.equal(primaryRead.status, 0, primaryRead.stderr); assert.match(primaryRead.stdout, /big-heroes-A/);
    const isolated = run(other, 'bd-read.sh', ['ready', '--json']);
    assert.equal(isolated.status, 0, isolated.stderr); assert.match(isolated.stdout, /big-heroes-A/);
    const viaWorktree = run(linked, 'bd-wt.sh', ['ready', '--json'], env);
    assert.equal(viaWorktree.status, 0, viaWorktree.stderr); assert.match(viaWorktree.stdout, /big-heroes-A/);
    const mutation = run(linked, 'bd-wt.sh', ['update', 'big-heroes-A', '--claim'], env);
    assert.notEqual(mutation.status, 0); assert.match(mutation.stderr, /managed publisher|typed queue/);
    const isolatedMutation = run(other, 'bd-wt.sh', ['update', 'big-heroes-A', '--claim'], env);
    assert.notEqual(isolatedMutation.status, 0); assert.match(isolatedMutation.stderr, /managed|typed queue/);
    const isolatedRead = run(other, 'bd-wt.sh', ['ready', '--json'], env);
    assert.equal(isolatedRead.status, 0, isolatedRead.stderr); assert.match(isolatedRead.stdout, /big-heroes-A/);
    for (const script of ['bd-sync-export.sh', 'bd-sync-restore.sh']) {
      const registered = run(main, script, [], env);
      assert.notEqual(registered.status, 0); assert.match(registered.stderr, /managed publisher|managed protocol/);
      const unregistered = run(other, script, [], env);
      assert.notEqual(unregistered.status, 0); assert.match(unregistered.stderr, /managed publisher|managed protocol/);
    }
    assert.equal(fs.existsSync(stubLog), false, 'legacy bd must never run after managed activation');
    const shallow = path.join(root, 'shallow');
    git(root, 'clone', '-q', '--depth', '1', `file://${remote}`, shallow);
    const partial = run(shallow, 'bd-read.sh', ['ready', '--json']);
    assert.notEqual(partial.status, 0); assert.match(partial.stderr, /partial|shallow|history/);
    const forgedLoss = publisher.commitCandidate({ base: published, snapshot: '', ledger });
    publisher.pushCandidate(forgedLoss);
    const lost = run(linked, 'bd-read.sh', ['ready', '--json']);
    assert.notEqual(lost.status, 0); assert.match(lost.stderr, /snapshot|outcome|postcondition|preserv/);
    git(remote, 'update-ref', 'refs/heads/beads-backup', published);
    const initial = git(main, 'ls-remote', '--heads', 'origin', 'refs/heads/beads-backup').split('\t')[0];
    const index = path.join(root, 'fixture-index');
    const indexed = (args, input) => execFileSync('git', args, { cwd: main, env: { ...process.env, GIT_INDEX_FILE: index },
      input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
    indexed(['read-tree', `${initial}^{tree}`]);
    const changed = indexed(['hash-object', '-w', '--stdin'], snapshot.replace('Published task', 'Changed without protocol hash'));
    indexed(['update-index', '--add', '--cacheinfo', `100644,${changed},.beads/issues.jsonl`]);
    const corruptTree = indexed(['write-tree']);
    const corrupt = git(main, 'commit-tree', corruptTree, '-p', initial, '-m', 'corrupt managed snapshot');
    git(main, 'push', '-q', 'origin', `${corrupt}:refs/heads/beads-backup`);
    const invalid = run(linked, 'bd-read.sh', ['ready', '--json']);
    assert.notEqual(invalid.status, 0); assert.match(invalid.stderr, /protocol|hash|managed/);
    indexed(['read-tree', `${corrupt}^{tree}`]);
    indexed(['update-index', '--force-remove', '--', '.beads/overgate-managed-v1.json', '.beads/overgate-outcomes-v1.json']);
    const downgraded = git(main, 'commit-tree', indexed(['write-tree']), '-p', corrupt, '-m', 'old writer downgrade');
    git(main, 'push', '-q', 'origin', `${downgraded}:refs/heads/beads-backup`);
    const downgradedRead = run(linked, 'bd-read.sh', ['ready', '--json']);
    assert.notEqual(downgradedRead.status, 0); assert.match(downgradedRead.stderr, /downgrade/);
    const downgradedExport = run(other, 'bd-sync-export.sh', [], env);
    assert.notEqual(downgradedExport.status, 0); assert.match(downgradedExport.stderr, /managed|downgrade/);
    assert.equal(fs.existsSync(stubLog), false);
    git(other, 'remote', 'set-url', 'origin', path.join(root, 'missing.git'));
    const unknownRemoteMutation = run(other, 'bd-wt.sh', ['update', 'big-heroes-A', '--claim'], env);
    assert.notEqual(unknownRemoteMutation.status, 0); assert.match(unknownRemoteMutation.stderr, /remote|unknown|недоступен/);
    assert.equal(fs.existsSync(stubLog), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
