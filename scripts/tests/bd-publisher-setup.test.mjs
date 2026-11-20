import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { preparePublisherControl, installPublisherControl, assertPublisherIdentityAndAuth } from '../bd-publisher-setup.mjs';
import { ManagedGit, ZERO } from '../lib/bd-managed-git.mjs';
import { emptyLedger } from '../lib/bd-managed-contract.mjs';
import * as gitEnvironment from '../lib/bd-git-environment.mjs';

const { cleanGitEnvironment } = gitEnvironment;
// До og-4py функции нет: тест не должен падать на импорте (RED по поведению).
const disposeNetworkGitEnvironment = () => gitEnvironment.disposeNetworkGitEnvironment?.();

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
const files = ['scripts/bd-apply-intents.sh', 'scripts/bd-publisher-setup.mjs', 'scripts/bd-sync-export.sh', 'scripts/bd-wt.sh',
  'scripts/lib/bd-env.sh',
  'scripts/lib/bd-publisher-push-guard.mjs', 'scripts/lib/bd-managed-cli.mjs', 'scripts/lib/bd-managed-contract.mjs',
  'scripts/lib/bd-managed-entry.mjs', 'scripts/lib/bd-managed-git.mjs', 'scripts/lib/bd-managed-journal.mjs',
  'scripts/lib/bd-managed-project.mjs', 'scripts/lib/bd-managed-transaction.mjs', 'scripts/lib/bd-snapshot.mjs'];
files.push('scripts/lib/bd-git-environment.mjs');

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
    for (const name of ['scripts/bd-read.sh', 'scripts/lib/bd-read-engine.mjs', 'scripts/lib/bd-managed-read-check.mjs']) {
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
    const identityPlan = path.join(root, 'missing-identity-plan.json');
    // Пустой источник пользовательского config (seam og-4py): без identity setup останавливается.
    const emptyReader = path.join(root, 'empty-user-config');
    fs.writeFileSync(emptyReader, '');
    const withUserConfig = (extra, action) => {
      const prior = process.env;
      process.env = { ...Object.fromEntries(Object.entries(prior).filter(([name]) => name !== 'OVERGATE_GIT_USER_CONFIG_FILE')), ...extra };
      disposeNetworkGitEnvironment();
      try { return action(); } finally { process.env = prior; disposeNetworkGitEnvironment(); }
    };
    withUserConfig({ OVERGATE_GIT_USER_CONFIG_FILE: emptyReader }, () => assert.throws(
      () => preparePublisherControl({ ...options, output: identityPlan }), /identity|user\.name|user\.email/,
      'publisher needs Git identity (user config or service) before setup'));
    assert.equal(fs.existsSync(identityPlan), false);
    git(publisher, 'config', '--local', 'user.name', 'fixture');
    git(publisher, 'config', '--local', 'user.email', 'fixture@example.invalid');
    const trusted = git(publisher, 'rev-parse', 'HEAD');
    const spoof = path.join(root, 'spoof.git');
    git(root, 'clone', '-q', '--bare', remote, spoof);
    const qaAttacker = path.join(root, 'qa-attacker.git');
    git(root, 'clone', '-q', '--bare', remote, qaAttacker);
    const exactQaOverride = { GIT_CONFIG_COUNT: '2', GIT_CONFIG_KEY_0: 'remote.origin.url', GIT_CONFIG_VALUE_0: qaAttacker,
      GIT_CONFIG_KEY_1: 'remote.origin.pushurl', GIT_CONFIG_VALUE_1: qaAttacker };
    const override = { ...process.env, GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: `url.${spoof}.insteadOf`, GIT_CONFIG_VALUE_0: remote };
    const prior = process.env;
    process.env = override;
    try {
      assert.equal(preparePublisherControl({ ...options, output: path.join(root, 'spoof-plan.json') }).origin.fetch, remote,
        'setup must ignore inherited origin override');
    } finally { process.env = prior; }
    process.env = { ...prior, ...exactQaOverride };
    try {
      const checked = preparePublisherControl({ ...options, output: path.join(root, 'qa-plan.json') });
      assert.deepEqual(checked.origin, { fetch: remote, push: [remote] }, 'setup must ignore exact QA fetch/push spoof');
    } finally { process.env = prior; }
    assert.equal(git(root, '--git-dir', qaAttacker, 'branch', '--list', 'beads-backup'), '', 'no attacker task publication during setup');
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
    const httpsOrigin = { push: ['https://example.invalid/project.git'] };
    withUserConfig({ OVERGATE_GIT_USER_CONFIG_FILE: emptyReader }, () => assert.throws(
      () => assertPublisherIdentityAndAuth(publisher, httpsOrigin), /HTTPS authentication unavailable/,
      'isolated HOME with empty user config source has no HTTPS helper'));
    const credentialHelper = path.join(root, 'fixture-credential-helper.sh');
    const credentialLog = path.join(root, 'credential-helper.log');
    fs.writeFileSync(credentialHelper, `#!/bin/sh\nprintf '%s\\n' "$1" >> '${credentialLog}'\nif [ "$1" = get ]; then printf 'username=fixture\\npassword=synthetic\\n'; fi\n`, { mode: 0o700 });
    // og-4py: helper из пользовательского global config (fixture HOME) достаточен без repo-local настройки.
    const fixtureHome = path.join(root, 'fixture-home');
    fs.mkdirSync(fixtureHome);
    fs.writeFileSync(path.join(fixtureHome, '.gitconfig'), `[credential]\n\thelper = ${credentialHelper}\n`);
    withUserConfig({ HOME: fixtureHome, XDG_CONFIG_HOME: path.join(fixtureHome, '.config') },
      () => assert.doesNotThrow(() => assertPublisherIdentityAndAuth(publisher, httpsOrigin), 'user global helper passes preflight'));
    git(publisher, 'config', '--local', 'credential.helper', credentialHelper);
    withUserConfig({ OVERGATE_GIT_USER_CONFIG_FILE: emptyReader },
      () => assert.doesNotThrow(() => assertPublisherIdentityAndAuth(publisher, httpsOrigin), 'repo-local helper still passes'));
    const credentialGlobal = path.join(root, 'credential-global-spoof');
    fs.writeFileSync(credentialGlobal, '[credential]\n\thelper = !printf "username=wrong\\npassword=wrong\\n"\n');
    const credentials = execFileSync('git', ['credential', 'fill'], { cwd: publisher, encoding: 'utf8',
      input: 'protocol=https\nhost=fixture.invalid\n\n', env: cleanGitEnvironment({ ...process.env, GIT_CONFIG_GLOBAL: credentialGlobal }) });
    assert.match(credentials, /username=fixture\npassword=synthetic/);
    assert.match(fs.readFileSync(credentialLog, 'utf8'), /get/);
    git(root, '--git-dir', spoof, 'update-ref', 'refs/heads/beads-backup', trusted);
    const injected = [
      { GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: `url.${spoof}.insteadOf`, GIT_CONFIG_VALUE_0: remote },
      { GIT_CONFIG_PARAMETERS: `'url.${spoof}.insteadOf=${remote}'` },
    ];
    const globalConfig = path.join(root, 'global-spoof');
    fs.writeFileSync(globalConfig, `[url "${spoof}"]\n\tinsteadOf = ${remote}\n`);
    injected.push({ GIT_CONFIG_GLOBAL: globalConfig });
    for (const override of injected) {
      const priorEnv = process.env;
      process.env = { ...priorEnv, ...override };
      try {
        assert.equal(new ManagedGit({ cwd: publisher }).call(['remote', 'get-url', 'origin']).trim(), remote,
          'managed git must use the tracked local origin');
        const shell = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher,
          encoding: 'utf8', env: process.env });
        assert.equal(shell.status, 0, shell.stderr);
        assert.equal(JSON.parse(shell.stdout).R, ZERO);
      } finally { process.env = priorEnv; }
    }
    assert.equal(new ManagedGit({ cwd: publisher }).readPublished().R, ZERO);
    assert.equal(fs.existsSync(path.join(primary, '.git', 'hooks', 'pre-push')), true);
    assert.equal(fs.existsSync(path.join(publisher, '.git', 'hooks', 'pre-push')), true);
    const trustedHelper = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher, encoding: 'utf8' });
    assert.equal(trustedHelper.status, 0, trustedHelper.stderr);
    assert.equal(JSON.parse(trustedHelper.stdout).R, ZERO);
    const untrackedModule = path.join(publisher, 'scripts/lib/bd-managed-untracked.mjs');
    fs.writeFileSync(untrackedModule, 'export const injected = true;\n');
    const untrackedHelper = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher, encoding: 'utf8' });
    assert.notEqual(untrackedHelper.status, 0);
    assert.match(untrackedHelper.stderr, /tracked publisher tooling closure incomplete/);
    fs.unlinkSync(untrackedModule);
    fs.appendFileSync(path.join(publisher, 'scripts/lib/bd-managed-entry.mjs'), '\n// staged fixture drift\n');
    git(publisher, 'add', 'scripts/lib/bd-managed-entry.mjs');
    const stagedHelper = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher, encoding: 'utf8' });
    assert.notEqual(stagedHelper.status, 0);
    assert.match(stagedHelper.stderr, /publisher tooling changed|tooling изменён/);
    git(publisher, 'reset', '--hard', 'HEAD');
    fs.appendFileSync(path.join(publisher, 'scripts/lib/bd-git-environment.mjs'), '\n// untrusted Git environment override\n');
    const dirtyEnvironment = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: publisher, encoding: 'utf8' });
    assert.notEqual(dirtyEnvironment.status, 0, 'dirty imported Git sanitizer must stop before Node');
    assert.match(dirtyEnvironment.stderr, /publisher tooling changed|tooling изменён/);
    git(publisher, 'reset', '--hard', 'HEAD');
    assert.throws(() => installPublisherControl(output, { qualifyCli: () => true, readIssuePrefix: () => 'wrong' }), /issue prefix changed/);
    assert.throws(() => installPublisherControl(output, { qualifyCli: () => false, readIssuePrefix: () => 'big-heroes' }), /fingerprint is not approved/);
    const oldWriter = spawnSync('git', ['push', 'origin', `${trusted}:refs/heads/beads-backup`], { cwd: primary, encoding: 'utf8' });
    assert.notEqual(oldWriter.status, 0);
    assert.match(oldWriter.stderr, /retired checkout cannot publish/);
    assert.equal(git(primary, 'ls-remote', '--heads', 'origin', 'refs/heads/beads-backup'), '');
    const activated = new ManagedGit({ cwd: publisher }).commitCandidate({ base: ZERO, snapshot: '', ledger: emptyLedger() });
    process.env = { ...process.env, ...exactQaOverride };
    try { new ManagedGit({ cwd: publisher }).pushCandidate(activated); }
    finally { for (const name of Object.keys(exactQaOverride)) delete process.env[name]; }
    assert.equal(git(primary, 'ls-remote', '--heads', 'origin', 'refs/heads/beads-backup').split('\t')[0], activated,
      'installed managed hook loads its complete trusted runtime and permits empty activation');
    assert.equal(git(root, '--git-dir', spoof, 'rev-parse', 'refs/heads/beads-backup'), trusted,
      'spoofed origin must not receive managed candidate');
    assert.equal(git(root, '--git-dir', qaAttacker, 'branch', '--list', 'beads-backup'), '',
      'exact QA spoofed fetch/push origin must not receive managed candidate');
    const peerRead = spawnSync('bash', ['scripts/bd-read.sh', 'list', '--json'], { cwd: primary, encoding: 'utf8',
      env: { ...process.env, ...exactQaOverride } });
    assert.equal(peerRead.status, 0, peerRead.stderr);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
