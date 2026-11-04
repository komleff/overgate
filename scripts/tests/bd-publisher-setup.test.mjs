import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { preparePublisherControl, installPublisherControl } from '../bd-publisher-setup.mjs';
import { ManagedGit, ZERO } from '../lib/bd-managed-git.mjs';

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const files = ['scripts/bd-apply-intents.sh', 'scripts/bd-publisher-setup.mjs', 'scripts/bd-sync-export.sh', 'scripts/bd-wt.sh',
  'scripts/lib/bd-env.sh',
  'scripts/lib/bd-publisher-push-guard.mjs', 'scripts/lib/bd-managed-cli.mjs', 'scripts/lib/bd-managed-contract.mjs',
  'scripts/lib/bd-managed-entry.mjs', 'scripts/lib/bd-managed-git.mjs', 'scripts/lib/bd-managed-journal.mjs',
  'scripts/lib/bd-managed-project.mjs', 'scripts/lib/bd-managed-transaction.mjs', 'scripts/lib/bd-snapshot.mjs'];

test('setup binds generic registration to current trusted main and installed guards', () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-setup-')));
  try {
    const remote = path.join(root, 'remote.git'), seed = path.join(root, 'seed'), primary = path.join(root, 'primary'), publisher = path.join(root, 'publisher');
    git(root, 'init', '-q', '--bare', remote);
    git(root, 'init', '-q', '-b', 'main', seed);
    git(seed, 'config', 'user.name', 'fixture'); git(seed, 'config', 'user.email', 'fixture@example.invalid');
    for (const name of files) {
      const target = path.join(seed, name); fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(path.join(source, name), target);
    }
    git(seed, 'add', '-A'); git(seed, 'commit', '-q', '-m', 'trusted helper');
    git(seed, 'remote', 'add', 'origin', remote); git(seed, 'push', '-q', 'origin', 'main');
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main');
    git(root, 'clone', '-q', remote, primary); git(root, 'clone', '-q', remote, publisher);
    const cli = process.execPath, output = path.join(root, 'publisher-plan.json');
    const options = { primaryRoot: primary, publisherRoot: publisher, qualifiedCli: cli, output,
      qualifyCli: () => true, readIssuePrefix: () => 'big-heroes' };
    const trusted = git(publisher, 'rev-parse', 'HEAD');
    const untrusted = spawnSync(process.execPath, [path.join(source, 'scripts/bd-publisher-setup.mjs'),
      '--primary-root', primary, '--publisher-root', publisher, '--qualified-cli', cli, '--output', output], { encoding: 'utf8' });
    assert.notEqual(untrusted.status, 0);
    assert.match(untrusted.stderr, /trusted publisher helper path/);
    assert.equal(fs.existsSync(output), false);
    fs.writeFileSync(path.join(publisher, 'behind.txt'), 'untrusted\n');
    git(publisher, 'add', 'behind.txt'); git(publisher, 'config', 'user.name', 'fixture'); git(publisher, 'config', 'user.email', 'fixture@example.invalid');
    git(publisher, 'commit', '-q', '-m', 'local ahead');
    assert.throws(() => preparePublisherControl(options), /trusted origin\/main|exact main/);
    git(publisher, 'reset', '--hard', trusted);
    const plan = preparePublisherControl(options);
    assert.equal(plan.publisherHead, trusted);
    assert.equal(plan.registration.prefix, 'big-heroes');
    assert.equal(plan.targets.primary.mode, 'retired');
    assert.equal(plan.targets.publisher.mode, 'managed');
    assert.equal(Object.keys(plan.sourcePins).length, files.length);
    installPublisherControl(output, { qualifyCli: () => true, readIssuePrefix: () => 'big-heroes' });
    assert.equal(git(primary, 'config', '--local', '--get', 'overgate.beadsPublisher'), fs.realpathSync(publisher));
    assert.equal(git(primary, 'config', '--local', '--get', 'overgate.beadsCli'), fs.realpathSync(cli));
    assert.equal(git(primary, 'config', '--local', '--get', 'overgate.beadsPrefix'), 'big-heroes');
    assert.equal(git(publisher, 'config', '--local', '--get', 'overgate.beadsCli'), fs.realpathSync(cli));
    assert.equal(git(publisher, 'config', '--local', '--get', 'overgate.beadsPrefix'), 'big-heroes');
    assert.equal(new ManagedGit({ cwd: publisher }).readPublished().R, ZERO);
    assert.equal(fs.existsSync(path.join(primary, '.git', 'hooks', 'pre-push')), true);
    assert.equal(fs.existsSync(path.join(publisher, '.git', 'hooks', 'pre-push')), true);
    fs.appendFileSync(path.join(publisher, 'scripts/lib/bd-managed-entry.mjs'), '\n// staged fixture drift\n');
    git(publisher, 'add', 'scripts/lib/bd-managed-entry.mjs');
    const stagedHelper = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher, encoding: 'utf8' });
    assert.notEqual(stagedHelper.status, 0);
    assert.match(stagedHelper.stderr, /publisher tooling changed|tooling изменён/);
    git(publisher, 'reset', '--hard', 'HEAD');
    assert.throws(() => installPublisherControl(output, { qualifyCli: () => true, readIssuePrefix: () => 'wrong' }), /issue prefix changed/);
    assert.throws(() => installPublisherControl(output, { qualifyCli: () => false, readIssuePrefix: () => 'big-heroes' }), /fingerprint is not approved/);
    const oldWriter = spawnSync('git', ['push', 'origin', `${trusted}:refs/heads/beads-backup`], { cwd: primary, encoding: 'utf8' });
    assert.notEqual(oldWriter.status, 0);
    assert.match(oldWriter.stderr, /retired checkout cannot publish/);
    assert.equal(git(primary, 'ls-remote', '--heads', 'origin', 'refs/heads/beads-backup'), '');
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
