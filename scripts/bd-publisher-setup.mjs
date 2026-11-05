// Prepare записывает только пакет вне checkout; install меняет только Git control двух
// отдельных checkout с общим origin после сверки trusted main и qualified CLI.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { canonical } from './lib/bd-managed-contract.mjs';
import { qualifyBinary } from './lib/bd-managed-cli.mjs';
import { cleanGitEnvironment, cleanBeadsEnvironment } from './lib/bd-git-environment.mjs';

const sha256 = value => createHash('sha256').update(value).digest('hex');
function fileSha256(name) {
  const hash = createHash('sha256'), fd = fs.openSync(name, 'r'), buffer = Buffer.allocUnsafe(1024 * 1024);
  try { for (let count; (count = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0;) hash.update(buffer.subarray(0, count)); }
  finally { fs.closeSync(fd); }
  return hash.digest('hex');
}
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const SOURCE_FILES = Object.freeze([
  'scripts/bd-apply-intents.sh', 'scripts/bd-publisher-setup.mjs', 'scripts/bd-sync-export.sh', 'scripts/bd-wt.sh', 'scripts/lib/bd-env.sh',
  'scripts/lib/bd-publisher-push-guard.mjs', 'scripts/lib/bd-managed-entry.mjs', 'scripts/lib/bd-managed-cli.mjs',
  'scripts/lib/bd-managed-contract.mjs', 'scripts/lib/bd-managed-journal.mjs', 'scripts/lib/bd-managed-transaction.mjs',
  'scripts/lib/bd-managed-git.mjs', 'scripts/lib/bd-managed-project.mjs', 'scripts/lib/bd-snapshot.mjs',
  'scripts/lib/bd-git-environment.mjs',
]);
const RUNTIME_FILES = ['bd-publisher-push-guard.mjs', 'bd-managed-cli.mjs', 'bd-managed-git.mjs', 'bd-managed-contract.mjs',
  'bd-managed-journal.mjs', 'bd-managed-project.mjs', 'bd-snapshot.mjs', 'bd-git-environment.mjs'];
const REGISTRATION_KEYS = ['overgate.beadsPublisher', 'overgate.beadsCli', 'overgate.beadsPrefix'];
const CONTROL_CONFIG_KEYS = [...REGISTRATION_KEYS, 'core.hooksPath'];

function git(cwd, args, { encoding = 'utf8', input } = {}) {
  return execFileSync('git', args, { cwd, encoding, input, timeout: 15000, maxBuffer: 32 * 1024 * 1024,
    env: cleanGitEnvironment(), stdio: ['pipe', 'pipe', 'pipe'] });
}
function optionalGit(cwd, args) {
  try { return git(cwd, args).trim(); } catch (error) { if (error.status === 1) return null; throw error; }
}
function inside(child, parent) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function fileState(target) {
  if (!fs.existsSync(target)) return null;
  const stat = fs.statSync(target);
  requireThat(stat.isFile(), `expected regular file: ${target}`);
  return { sha256: sha256(fs.readFileSync(target)), mode: stat.mode & 0o777 };
}
function originState(root) {
  const fetch = git(root, ['remote', 'get-url', 'origin']).trim();
  const push = git(root, ['remote', 'get-url', '--push', '--all', 'origin']).trim().split(/\r?\n/).filter(Boolean);
  requireThat(fetch && push.length > 0, 'origin must have fetch and push destinations');
  return { fetch, push };
}
function localConfigValues(root, key) {
  try {
    const raw = git(root, ['config', '--local', '--null', '--get-all', key], { encoding: 'buffer' }).toString('utf8').split('\0');
    if (raw.at(-1) === '') raw.pop();
    return raw;
  } catch (error) { if (error.status === 1) return []; throw error; }
}
export function assertPublisherIdentityAndAuth(root, origin) {
  const localName = localConfigValues(root, 'user.name'), localEmail = localConfigValues(root, 'user.email');
  const localIdentity = localName.length === 1 && localName[0].trim() && localEmail.length === 1 && localEmail[0].trim();
  const serviceIdentity = ['GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL']
    .every(name => typeof process.env[name] === 'string' && process.env[name].trim());
  requireThat(localIdentity || serviceIdentity,
    'publisher Git identity unavailable under isolated config; set repo-local user.name/user.email or explicit service author/committer identity');
  for (const identity of ['GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT']) {
    try { requireThat(git(root, ['var', identity]).trim(), `publisher ${identity} unavailable`); }
    catch { throw new Error('publisher Git identity unavailable under isolated config; set repo-local user.name/user.email or explicit service author/committer identity'); }
  }
  const helpers = localConfigValues(root, 'credential.helper').filter(Boolean);
  for (const destination of origin.push) {
    if (/^https:\/\//i.test(destination)) {
      requireThat(helpers.length > 0, 'publisher HTTPS authentication unavailable under isolated config; configure a trusted repo-local credential.helper or use SSH agent origin');
    } else if (/^(ssh:\/\/|[^/\s]+@[^/:\s]+:)/i.test(destination)) {
      requireThat(typeof process.env.SSH_AUTH_SOCK === 'string' && process.env.SSH_AUTH_SOCK.length > 0,
        'publisher SSH authentication unavailable; start SSH agent or configure trusted repo-local HTTPS credential.helper');
    } else requireThat(path.isAbsolute(destination) || destination.startsWith('file://'),
      'publisher push origin transport unsupported under isolated config');
  }
}
function hookLayout(info, configuredHooksPath) {
  const sourceCandidate = configuredHooksPath === null ? path.join(info.gitDir, 'hooks')
    : path.isAbsolute(configuredHooksPath) ? path.resolve(configuredHooksPath) : path.resolve(info.root, configuredHooksPath);
  requireThat(fs.existsSync(sourceCandidate) && fs.statSync(sourceCandidate).isDirectory(), `${info.label} configured hooks directory must exist`);
  const sourceHooksDir = fs.realpathSync(sourceCandidate);
  requireThat(inside(sourceHooksDir, info.gitDir) || inside(sourceHooksDir, info.root), `${info.label} hooksPath must stay inside the standalone repository root`);
  const transitionHooksPath = !inside(sourceHooksDir, info.gitDir);
  const managedHooksDir = transitionHooksPath ? path.join(info.gitDir, 'overgate-bd-publisher-hooks') : sourceHooksDir;
  return { sourceHooksDir, sourceHookPath: path.join(sourceHooksDir, 'pre-push'), managedHooksDir,
    hookPath: path.join(managedHooksDir, 'pre-push'), transitionHooksPath };
}
function repo(root, label) {
  const resolved = fs.realpathSync(path.resolve(root));
  requireThat(git(resolved, ['rev-parse', '--is-bare-repository']).trim() === 'false', `${label} must be non-bare`);
  const top = fs.realpathSync(git(resolved, ['rev-parse', '--show-toplevel']).trim());
  const gitDir = fs.realpathSync(git(resolved, ['rev-parse', '--path-format=absolute', '--git-dir']).trim());
  const common = fs.realpathSync(git(resolved, ['rev-parse', '--path-format=absolute', '--git-common-dir']).trim());
  requireThat(top === resolved && gitDir === common, `${label} must be a canonical standalone root`);
  const configPath = path.resolve(resolved, git(resolved, ['rev-parse', '--git-path', 'config']).trim());
  requireThat(inside(configPath, gitDir), `${label} local config path is unexpected`);
  const controlDir = path.join(gitDir, 'overgate-bd-publisher-control');
  const hooksPathValues = localConfigValues(resolved, 'core.hooksPath');
  requireThat(hooksPathValues.length <= 1, `${label} has duplicate local core.hooksPath values`);
  const configuredHooksPath = hooksPathValues[0] ?? null;
  const base = { label, root: resolved, gitDir, configPath, controlDir,
    savedOriginal: path.join(controlDir, 'saved-pre-push'), origin: originState(resolved), configuredHooksPath };
  const layout = hookLayout(base, configuredHooksPath);
  const effectiveHook = path.resolve(resolved, git(resolved, ['rev-parse', '--git-path', 'hooks/pre-push']).trim());
  const effectiveDirectory = fs.realpathSync(path.dirname(effectiveHook));
  const effectiveCanonicalHook = path.join(effectiveDirectory, path.basename(effectiveHook));
  requireThat(effectiveCanonicalHook === layout.sourceHookPath,
    `${label} effective hooksPath differs from the repository-local hook layout; inherited core.hooksPath is unsupported`);
  return { ...base, ...layout };
}
function configEntries(info) {
  const records = git(info.root, ['config', '--local', '--null', '--list'], { encoding: 'buffer' }).toString('utf8').split('\0');
  if (records.at(-1) === '') records.pop();
  return records.map(record => {
    const separator = record.indexOf('\n');
    requireThat(separator > 0, `${info.label} local config framing is unexpected`);
    return [record.slice(0, separator).toLowerCase(), record.slice(separator + 1)];
  });
}
function configState(info) {
  const entries = configEntries(info);
  const owned = Object.fromEntries(CONTROL_CONFIG_KEYS.map(key => [key, entries.filter(([name]) => name === key.toLowerCase()).map(([, value]) => value)]));
  const foreign = entries.filter(([name]) => !CONTROL_CONFIG_KEYS.some(key => name === key.toLowerCase())).sort((a, b) => canonical(a).localeCompare(canonical(b)));
  return { owned, foreignSha256: sha256(Buffer.from(canonical(foreign))) };
}
function state(info) {
  return {
    head: git(info.root, ['rev-parse', 'HEAD']).trim(),
    indexSha256: sha256(git(info.root, ['ls-files', '-s', '-z'], { encoding: 'buffer' })),
    statusSha256: sha256(git(info.root, ['status', '--porcelain=v1', '-z'], { encoding: 'buffer' })),
    hook: fileState(info.sourceHookPath), configSha256: sha256(fs.readFileSync(info.configPath)),
    hooksPath: optionalGit(info.root, ['config', '--local', '--get', 'core.hooksPath']), registration: configState(info),
  };
}
export function isHookActive(mode, platform = process.platform) {
  return platform === 'win32' || (mode & 0o111) !== 0;
}
function sourceInventory(root) {
  const result = {};
  const visit = (directory, prefix = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const target = path.join(directory, entry.name);
      requireThat(!entry.name.startsWith('.env'), `hook source inventory refuses protected .env* entry: ${relative}`);
      const stat = fs.lstatSync(target);
      requireThat(!entry.isSymbolicLink(), `hook source symlink is unsupported: ${target}`);
      if (entry.isDirectory()) { result[relative] = { type: 'directory', mode: stat.mode & 0o777 }; visit(target, relative); }
      else {
        requireThat(entry.isFile(), `hook source entry must be a regular file: ${target}`);
        result[relative] = { type: 'file', mode: stat.mode & 0o777, sha256: fileSha256(target) };
      }
    }
  };
  visit(root);
  return result;
}
function trustedMain(info) {
  requireThat(git(info.root, ['symbolic-ref', '--quiet', '--short', 'HEAD']).trim() === 'main', `${info.label} requires exact main branch`);
  const head = git(info.root, ['rev-parse', 'HEAD']).trim();
  const remote = git(info.root, ['ls-remote', '--exit-code', '--heads', 'origin', 'refs/heads/main']).trim();
  requireThat(remote === `${head}\trefs/heads/main`, `${info.label} must be exact trusted origin/main`);
  return head;
}
function sourcePins(publisher) {
  return Object.fromEntries(SOURCE_FILES.map(name => {
    let raw;
    try { raw = git(publisher.root, ['show', `HEAD:${name}`], { encoding: 'buffer' }); }
    catch { throw new Error(`publisher source missing from trusted main: ${name}`); }
    return [name, sha256(raw)];
  }));
}
function assertQualified(cli, qualifyCli) {
  const hash = fileSha256(cli), qualified = qualifyCli(cli);
  requireThat(qualified === hash || qualified === true, 'qualified CLI fingerprint is not approved');
  return hash;
}
function issuePrefix(primary, cli, readIssuePrefix) {
  const prefix = readIssuePrefix ? readIssuePrefix(primary.root, cli)
    : JSON.parse(execFileSync(cli, ['--readonly', 'config', 'list', '--json'], { cwd: primary.root, encoding: 'utf8', timeout: 30000,
      maxBuffer: 1024 * 1024, env: cleanBeadsEnvironment(), stdio: ['ignore', 'pipe', 'pipe'] })).issue_prefix;
  requireThat(typeof prefix === 'string' && /^[A-Za-z][A-Za-z0-9-]*$/.test(prefix), 'qualified CLI issue prefix invalid');
  return prefix;
}
function headFile(publisher, name) {
  try { return git(publisher.root, ['show', `HEAD:scripts/lib/${name}`], { encoding: 'buffer' }); }
  catch { throw new Error(`publisher committed runtime missing: scripts/lib/${name}`); }
}
function artifact(root, relative, bytes, mode = 0o444) {
  const target = path.join(root, ...relative.split('/'));
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, bytes, { mode });
  fs.chmodSync(target, mode);
  return { path: target, sha256: sha256(bytes), mode: fileState(target).mode };
}
function shell(value) { return `'${value.replaceAll('\\', '/').replaceAll("'", `'"'"'`)}'`; }
function wrapper({ controlDir, node, configHash, originalCommand }) {
  const normalized = controlDir.replaceAll('\\', '/');
  const guard = `${normalized}/bd-publisher-push-guard.mjs`, config = `${normalized}/guard-config.json`, saved = `${normalized}/saved-pre-push`;
  return Buffer.from(`#!/bin/sh\ninput=$(mktemp ${shell(`${normalized}/pre-push-input.XXXXXX`)}) || exit 1\ntrap 'rm -f "$input"' EXIT HUP INT TERM\ncat > "$input" || exit 1\n${shell(node)} ${shell(guard)} --config ${shell(config)} --config-sha256 ${shell(configHash)} --input "$input" || exit $?\n${originalCommand ? `${shell(originalCommand)} "$@" < "$input"\nexit $?` : 'exit 0'}\n`);
}
function forwardingHook(original) { return Buffer.from(`#!/bin/sh\nexec ${shell(original)} "$@"\n`); }
function guardConfig(info, mode, publisher, publisherHead, pins, prefix) {
  return Buffer.from(`${JSON.stringify({ version: 1, mode, repositoryRoot: info.root,
    publisherRoot: publisher.root, expectedPublisherHead: publisherHead, sourcePins: pins, projectPrefix: prefix }, null, 2)}\n`);
}
function ownership(planId, target) { return Buffer.from(`${JSON.stringify({ version: 1, planId, target }, null, 2)}\n`); }
function planIdentity(value) { return sha256(Buffer.from(canonical(value))); }
function assertConfigAvailable(primary, publisherRoot, qualifiedCli, prefix) {
  const current = configState(primary).owned;
  const expected = { 'overgate.beadsPublisher': publisherRoot, 'overgate.beadsCli': qualifiedCli, 'overgate.beadsPrefix': prefix };
  for (const [key, value] of Object.entries(expected))
    requireThat(current[key].length === 0 || (current[key].length === 1 && current[key][0] === value), `local config collision: ${key}`);
}
const sameOrigin = (left, right) => canonical(left) === canonical(right);

export function preparePublisherControl({ primaryRoot, publisherRoot, qualifiedCli, output, qualifyCli = qualifyBinary, readIssuePrefix }) {
  requireThat(primaryRoot && publisherRoot && qualifiedCli && output, 'prepare requires primaryRoot, publisherRoot, qualifiedCli and output');
  const primary = repo(primaryRoot, 'primary'), publisher = repo(publisherRoot, 'publisher');
  requireThat(primary.root !== publisher.root && primary.gitDir !== publisher.gitDir && sameOrigin(primary.origin, publisher.origin),
    'primary and publisher must be distinct standalone roots with the same fetch/push origin destinations');
  assertPublisherIdentityAndAuth(publisher.root, publisher.origin);
  trustedMain(primary); trustedMain(publisher);
  requireThat(git(publisher.root, ['status', '--porcelain=v1', '-z'], { encoding: 'buffer' }).length === 0, 'publisher must be clean');
  const cli = fs.realpathSync(path.resolve(qualifiedCli)), cliHash = assertQualified(cli, qualifyCli);
  const prefix = issuePrefix(primary, cli, readIssuePrefix), pins = sourcePins(publisher);
  assertConfigAvailable(primary, publisher.root, cli, prefix);
  assertConfigAvailable(publisher, publisher.root, cli, prefix);
  requireThat(!fs.existsSync(primary.controlDir) && !fs.existsSync(publisher.controlDir), 'publisher control collision: existing state is not owned by this plan');
  const outputPath = path.resolve(output), artifactsRoot = `${outputPath}.artifacts`;
  requireThat(!inside(outputPath, primary.root) && !inside(outputPath, publisher.root)
    && !inside(artifactsRoot, primary.root) && !inside(artifactsRoot, publisher.root), 'prepare output must be outside both target roots');
  requireThat(!fs.existsSync(outputPath) && !fs.existsSync(artifactsRoot), 'prepare output collision');
  fs.mkdirSync(artifactsRoot, { recursive: true });
  const publisherHead = git(publisher.root, ['rev-parse', 'HEAD']).trim(), nodeExec = fs.realpathSync(process.execPath);
  const runtime = {};
  for (const name of RUNTIME_FILES) runtime[name] = artifact(artifactsRoot, `runtime/${name}`, headFile(publisher, name));
  const makeTarget = (info, mode) => {
    const current = state(info);
    const config = artifact(artifactsRoot, `${mode}/guard-config.json`, guardConfig(info, mode, publisher, publisherHead, pins, prefix));
    const originalActive = current.hook !== null && isHookActive(current.hook.mode);
    const originalCommand = originalActive ? (info.transitionHooksPath ? info.sourceHookPath : info.savedOriginal) : null;
    const hook = artifact(artifactsRoot, `${mode}/pre-push`, wrapper({ controlDir: info.controlDir,
      node: nodeExec, configHash: config.sha256, originalCommand }), 0o755);
    const original = current.hook ? artifact(artifactsRoot, `${mode}/saved-pre-push`, fs.readFileSync(info.sourceHookPath), current.hook.mode) : null;
    const hookSourceInventory = info.transitionHooksPath ? sourceInventory(info.sourceHooksDir) : null;
    const forwarders = {};
    if (info.transitionHooksPath) {
      for (const [name, entry] of Object.entries(hookSourceInventory)) {
        if (name !== 'pre-push' && !name.includes('/') && entry.type === 'file' && isHookActive(entry.mode))
          forwarders[name] = artifact(artifactsRoot, `${mode}/forwarders/${name}`, forwardingHook(path.join(info.sourceHooksDir, name)), 0o755);
      }
    }
    return { mode, root: info.root, gitDir: info.gitDir, configPath: info.configPath,
      sourceHooksDir: info.sourceHooksDir, sourceHookPath: info.sourceHookPath, managedHooksDir: info.managedHooksDir,
      transitionHooksPath: info.transitionHooksPath, hookPath: info.hookPath, controlDir: info.controlDir,
      savedOriginal: info.savedOriginal, originalActive, sourceInventory: hookSourceInventory,
      expected: current, artifacts: { hook, config, original, forwarders } };
  };
  const body = { version: 1, preparedAt: new Date().toISOString(), output: outputPath, artifactsRoot, nodeExec,
    qualifiedCli: cli, qualifiedCliSha256: cliHash, publisherHead, origin: publisher.origin, sourcePins: pins,
    runtime, targets: { primary: makeTarget(primary, 'retired'), publisher: makeTarget(publisher, 'managed') },
    registration: { publisher: publisher.root, cli, prefix }, rollback: 'No automatic rollback. Saved originals are exposed; after protocol activation legacy publication must not be restored.' };
  const plan = { ...body, planId: planIdentity(body) };
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(plan, null, 2)}\n`, { mode: 0o444 });
  return plan;
}

function verifyArtifact(item) {
  requireThat(item && fs.existsSync(item.path), `prepared artifact missing: ${item?.path}`);
  const actual = fileState(item.path);
  requireThat(actual.sha256 === item.sha256 && actual.mode === item.mode, `prepared artifact collision: ${item.path}`);
}
function requireArtifactPath(item, expected) { requireThat(item?.path === expected, `prepared artifact path mismatch: ${item?.path}`); }
function sameWorkState(actual, expected) {
  return actual.head === expected.head && actual.indexSha256 === expected.indexSha256
    && actual.statusSha256 === expected.statusSha256;
}
function assertTargetBinding(target, actual) {
  for (const name of ['root', 'gitDir', 'configPath', 'controlDir', 'savedOriginal'])
    requireThat(target[name] === actual[name], `${actual.label} serialized ${name} does not match derived Git path`);
  const expectedHooksPath = target.expected.registration.owned['core.hooksPath'];
  requireThat(expectedHooksPath.length <= 1, `${actual.label} captured core.hooksPath is ambiguous`);
  const layout = hookLayout(actual, expectedHooksPath[0] ?? null);
  for (const name of ['sourceHooksDir', 'sourceHookPath', 'managedHooksDir', 'hookPath', 'transitionHooksPath'])
    requireThat(target[name] === layout[name], `${actual.label} serialized ${name} does not match derived hook layout`);
}
function validatePreparedPlan(plan, manifest, primary, publisher) {
  requireThat(plan.output === manifest && plan.artifactsRoot === `${manifest}.artifacts`, 'publisher plan output/artifact root mismatch');
  requireThat(plan.nodeExec === fs.realpathSync(process.execPath), 'Node executable changed since prepare');
  requireThat(canonical(plan.sourcePins) === canonical(sourcePins(publisher)), 'publisher source pins changed in plan');
  requireThat(primary.gitDir !== publisher.gitDir && primary.root !== publisher.root, 'primary and publisher Gitdirs must be distinct');
  assertPublisherIdentityAndAuth(publisher.root, publisher.origin);
  assertTargetBinding(plan.targets.primary, primary); assertTargetBinding(plan.targets.publisher, publisher);
  requireThat(plan.targets.primary.mode === 'retired' && plan.targets.publisher.mode === 'managed', 'publisher target modes are invalid');
  requireThat(plan.registration.publisher === publisher.root && plan.registration.cli === plan.qualifiedCli
    && typeof plan.registration.prefix === 'string', 'publisher registration fields changed');
  requireThat(sameOrigin(primary.origin, publisher.origin) && sameOrigin(publisher.origin, plan.origin), 'origin fetch/push destinations changed since prepare');
  requireThat(canonical(Object.keys(plan.runtime).sort()) === canonical([...RUNTIME_FILES].sort()), 'publisher runtime inventory changed');
  for (const name of RUNTIME_FILES) {
    const item = plan.runtime[name];
    requireArtifactPath(item, path.join(plan.artifactsRoot, 'runtime', name)); verifyArtifact(item);
    requireThat(item.mode === 0o444 && item.sha256 === sha256(headFile(publisher, name)), `runtime does not match committed publisher HEAD: ${name}`);
  }
  for (const [key, actual] of [['primary', primary], ['publisher', publisher]]) {
    const target = plan.targets[key], directory = target.mode;
    requireArtifactPath(target.artifacts.config, path.join(plan.artifactsRoot, directory, 'guard-config.json'));
    requireArtifactPath(target.artifacts.hook, path.join(plan.artifactsRoot, directory, 'pre-push'));
    verifyArtifact(target.artifacts.config); verifyArtifact(target.artifacts.hook);
    const expectedConfig = guardConfig(actual, target.mode, publisher, plan.publisherHead, plan.sourcePins, plan.registration.prefix);
    requireThat(target.artifacts.config.mode === 0o444 && target.artifacts.config.sha256 === sha256(expectedConfig)
      && fs.readFileSync(target.artifacts.config.path).equals(expectedConfig), `${key} guard config is not derived from validated paths`);
    const expectedActive = target.expected.hook !== null && isHookActive(target.expected.hook.mode);
    requireThat(target.originalActive === expectedActive, `${key} original hook activity changed in plan`);
    const originalCommand = expectedActive ? (target.transitionHooksPath ? target.sourceHookPath : target.savedOriginal) : null;
    const expectedHook = wrapper({ controlDir: actual.controlDir, node: plan.nodeExec,
      configHash: target.artifacts.config.sha256, originalCommand });
    const nativeHookMode = process.platform === 'win32' ? 0o666 : 0o755;
    requireThat(target.artifacts.hook.mode === nativeHookMode && target.artifacts.hook.sha256 === sha256(expectedHook)
      && fs.readFileSync(target.artifacts.hook.path).equals(expectedHook), `${key} wrapper is not derived from validated paths`);
    if (target.expected.hook) {
      requireThat(target.artifacts.original !== null, `${key} captured original hook artifact missing`);
      requireArtifactPath(target.artifacts.original, path.join(plan.artifactsRoot, directory, 'saved-pre-push'));
      verifyArtifact(target.artifacts.original);
      requireThat(target.artifacts.original.sha256 === target.expected.hook.sha256
        && target.artifacts.original.mode === target.expected.hook.mode, `${key} original hook bytes/mode do not match captured state`);
    } else requireThat(target.artifacts.original === null, `${key} unexpected original hook artifact`);
    if (target.transitionHooksPath) {
      requireThat(canonical(sourceInventory(target.sourceHooksDir)) === canonical(target.sourceInventory), `${key} source hook inventory changed`);
      const expectedForwarders = {};
      for (const [name, entry] of Object.entries(target.sourceInventory)) {
        if (name !== 'pre-push' && !name.includes('/') && entry.type === 'file' && isHookActive(entry.mode)) expectedForwarders[name] = true;
      }
      requireThat(canonical(Object.keys(target.artifacts.forwarders).sort()) === canonical(Object.keys(expectedForwarders).sort()), `${key} forwarding hook inventory changed`);
      for (const [name, item] of Object.entries(target.artifacts.forwarders)) {
        requireArtifactPath(item, path.join(plan.artifactsRoot, directory, 'forwarders', name)); verifyArtifact(item);
        const expected = forwardingHook(path.join(target.sourceHooksDir, name));
        requireThat(item.mode === nativeHookMode && item.sha256 === sha256(expected)
          && fs.readFileSync(item.path).equals(expected), `${key} forwarding hook is not derived from source: ${name}`);
      }
    } else {
      requireThat(target.sourceInventory === null && Object.keys(target.artifacts.forwarders).length === 0, `${key} unexpected hook overlay artifacts`);
    }
  }
}
function copyExact(source, target, mode) { fs.copyFileSync(source, target); fs.chmodSync(target, mode); }
function expectedControl(plan, key) {
  const target = plan.targets[key];
  const files = new Map(Object.entries(plan.runtime).map(([name, item]) => [name, { sha256: item.sha256, mode: item.mode }]));
  files.set('guard-config.json', { sha256: target.artifacts.config.sha256, mode: target.artifacts.config.mode });
  files.set('control-plan.json', { sha256: sha256(ownership(plan.planId, key)), mode: 0o444 });
  if (target.artifacts.original) files.set('saved-pre-push', { sha256: target.artifacts.original.sha256, mode: target.artifacts.original.mode });
  return files;
}
function inspectControl(plan, key) {
  const target = plan.targets[key];
  if (!fs.existsSync(target.controlDir)) return { exists: false, receipt: false };
  requireThat(fs.statSync(target.controlDir).isDirectory(), `${key} control path collision`);
  const files = expectedControl(plan, key), names = fs.readdirSync(target.controlDir).sort();
  const allowed = [...files.keys(), 'installed.json'].sort();
  requireThat(names.every(name => allowed.includes(name)) && [...files.keys()].every(name => names.includes(name)), `${key} control inventory collision`);
  for (const [name, expected] of files) {
    const actual = fileState(path.join(target.controlDir, name));
    requireThat(actual?.sha256 === expected.sha256 && actual.mode === expected.mode, `${key} control owned hash/mode collision: ${name}`);
  }
  const receiptPath = path.join(target.controlDir, 'installed.json'), hasReceipt = fs.existsSync(receiptPath);
  if (hasReceipt) {
    const expected = ownership(plan.planId, key), actual = fileState(receiptPath);
    requireThat(actual?.sha256 === sha256(expected) && actual.mode === 0o444, `${key} installed receipt collision`);
  }
  return { exists: true, receipt: hasReceipt };
}
function stageControl(plan, key) {
  const target = plan.targets[key];
  if (fs.existsSync(target.controlDir)) return;
  const staging = `${target.controlDir}.stage-${plan.planId}`;
  requireThat(!fs.existsSync(staging), `${key} incomplete control staging collision`);
  fs.mkdirSync(staging);
  for (const [name, item] of Object.entries(plan.runtime)) copyExact(item.path, path.join(staging, name), item.mode);
  copyExact(target.artifacts.config.path, path.join(staging, 'guard-config.json'), target.artifacts.config.mode);
  if (target.artifacts.original) copyExact(target.artifacts.original.path, path.join(staging, 'saved-pre-push'), target.artifacts.original.mode);
  fs.writeFileSync(path.join(staging, 'control-plan.json'), ownership(plan.planId, key), { mode: 0o444 });
  fs.renameSync(staging, target.controlDir);
}
function hookStage(target) {
  if (target.transitionHooksPath) {
    if (!fs.existsSync(target.managedHooksDir)) return 'original';
    requireThat(fs.statSync(target.managedHooksDir).isDirectory(), `${target.mode} managed hooks path collision`);
    const expected = { 'pre-push': target.artifacts.hook, ...target.artifacts.forwarders };
    requireThat(canonical(fs.readdirSync(target.managedHooksDir).sort()) === canonical(Object.keys(expected).sort()), `${target.mode} managed hook inventory collision`);
    for (const [name, item] of Object.entries(expected)) {
      const actual = fileState(path.join(target.managedHooksDir, name));
      requireThat(actual?.sha256 === item.sha256 && actual.mode === item.mode, `${target.mode} managed hook collision: ${name}`);
    }
    return 'ours';
  }
  const actual = fileState(target.hookPath);
  if (canonical(actual) === canonical(target.expected.hook)) return 'original';
  if (actual?.sha256 === target.artifacts.hook.sha256 && actual.mode === target.artifacts.hook.mode) return 'ours';
  throw new Error(`${target.mode} hook collision: neither captured original nor this plan`);
}
function targetConfigStage(info, target, registration = null) {
  const actual = configState(info), expected = target.expected.registration;
  requireThat(actual.foreignSha256 === expected.foreignSha256, `${info.label} local config foreign entries changed`);
  const desired = registration ? { 'overgate.beadsPublisher': [registration.publisher], 'overgate.beadsCli': [registration.cli],
    'overgate.beadsPrefix': [registration.prefix] } : null;
  const result = {};
  for (const key of REGISTRATION_KEYS) {
    if (desired && canonical(actual.owned[key]) === canonical(desired[key])) result[key] = 'ours';
    else if (canonical(actual.owned[key]) === canonical(expected.owned[key])) result[key] = 'original';
    else throw new Error(`${info.label} local config collision: ${key}`);
  }
  const managedHooksPath = [target.managedHooksDir];
  if (target.transitionHooksPath && canonical(actual.owned['core.hooksPath']) === canonical(managedHooksPath)) result['core.hooksPath'] = 'ours';
  else if (canonical(actual.owned['core.hooksPath']) === canonical(expected.owned['core.hooksPath'])) result['core.hooksPath'] = 'original';
  else throw new Error(`${info.label} local config collision: core.hooksPath`);
  if (registration) requireThat(!(result['overgate.beadsCli'] === 'ours' && result['overgate.beadsPublisher'] !== 'ours'), 'primary local config has an invalid partial registration order');
  return result;
}
function installHook(target, planId) {
  if (hookStage(target) === 'ours') return;
  const temporary = `${target.hookPath}.overgate-${planId}.tmp`;
  requireThat(!fs.existsSync(temporary), 'hook staging collision');
  copyExact(target.artifacts.hook.path, temporary, target.artifacts.hook.mode);
  fs.renameSync(temporary, target.hookPath);
}
function stageManagedHooks(target, planId) {
  if (hookStage(target) === 'ours') return;
  const staging = `${target.managedHooksDir}.stage-${planId}`;
  requireThat(!fs.existsSync(staging), `${target.mode} managed hooks staging collision`);
  fs.mkdirSync(staging);
  copyExact(target.artifacts.hook.path, path.join(staging, 'pre-push'), target.artifacts.hook.mode);
  for (const [name, item] of Object.entries(target.artifacts.forwarders)) copyExact(item.path, path.join(staging, name), item.mode);
  fs.renameSync(staging, target.managedHooksDir);
}
function activateTargetHook(info, target, planId, configStage, options, key) {
  if (!target.transitionHooksPath) { installHook(target, planId); return; }
  stageManagedHooks(target, planId);
  if (configStage['core.hooksPath'] !== 'ours') {
    git(info.root, ['config', '--local', '--replace-all', 'core.hooksPath', target.managedHooksDir]);
    failIfRequested(options, `after${key[0].toUpperCase()}${key.slice(1)}HooksPath`);
  }
}
function writeReceipt(plan, key) {
  const target = plan.targets[key], targetPath = path.join(target.controlDir, 'installed.json');
  if (!fs.existsSync(targetPath)) fs.writeFileSync(targetPath, ownership(plan.planId, key), { mode: 0o444 });
}
function failIfRequested(options, point) { if (options.failAt === point) throw new Error(`injected install failure at ${point}`); }

export function installPublisherControl(manifestPath, options = {}) {
  const manifest = path.resolve(manifestPath), plan = JSON.parse(fs.readFileSync(manifest, 'utf8'));
  const { planId, ...body } = plan;
  requireThat(plan.version === 1 && planId === planIdentity(body), 'publisher plan identity mismatch');
  const primary = repo(plan.targets.primary.root, 'primary'), publisher = repo(plan.targets.publisher.root, 'publisher');
  validatePreparedPlan(plan, manifest, primary, publisher);
  requireThat(trustedMain(primary) === plan.targets.primary.expected.head && trustedMain(publisher) === plan.publisherHead,
    'trusted main changed since prepare');
  requireThat(assertQualified(plan.qualifiedCli, options.qualifyCli || qualifyBinary) === plan.qualifiedCliSha256,
    'qualified CLI changed since prepare');
  requireThat(issuePrefix(primary, plan.qualifiedCli, options.readIssuePrefix) === plan.registration.prefix,
    'qualified CLI issue prefix changed since prepare');
  const primaryState = state(primary), publisherState = state(publisher);
  requireThat(sameWorkState(primaryState, plan.targets.primary.expected), 'primary preflight collision: HEAD/index/status changed');
  requireThat(sameWorkState(publisherState, plan.targets.publisher.expected), 'publisher preflight collision: HEAD/index/status changed');
  const controls = { primary: inspectControl(plan, 'primary'), publisher: inspectControl(plan, 'publisher') };
  const hooks = { primary: hookStage(plan.targets.primary), publisher: hookStage(plan.targets.publisher) };
  const configs = { primary: targetConfigStage(primary, plan.targets.primary, plan.registration),
    publisher: targetConfigStage(publisher, plan.targets.publisher, plan.registration) };
  const active = key => hooks[key] === 'ours'
    && (!plan.targets[key].transitionHooksPath || configs[key]['core.hooksPath'] === 'ours');
  if (controls.primary.receipt || controls.publisher.receipt) {
    requireThat(active('primary') && active('publisher')
      && configs.primary['overgate.beadsPublisher'] === 'ours' && configs.primary['overgate.beadsCli'] === 'ours'
      && configs.primary['overgate.beadsPrefix'] === 'ours'
      && configs.publisher['overgate.beadsPublisher'] === 'ours' && configs.publisher['overgate.beadsCli'] === 'ours'
      && configs.publisher['overgate.beadsPrefix'] === 'ours', 'installed receipt has inconsistent owned state');
    if (controls.primary.receipt && controls.publisher.receipt) return plan;
  }
  requireThat(!(configs.publisher['core.hooksPath'] === 'ours' && hooks.publisher !== 'ours'), 'publisher hooksPath points at an incomplete managed overlay');
  requireThat(!(configs.primary['core.hooksPath'] === 'ours' && hooks.primary !== 'ours'), 'primary hooksPath points at an incomplete managed overlay');
  requireThat(!(active('publisher') === false && (configs.primary['overgate.beadsPublisher'] === 'ours' || configs.primary['overgate.beadsCli'] === 'ours' || configs.primary['overgate.beadsPrefix'] === 'ours')),
    'registration cannot precede publisher guard');
  requireThat(!(active('primary') && (configs.primary['overgate.beadsPublisher'] !== 'ours' || configs.primary['overgate.beadsCli'] !== 'ours' || configs.primary['overgate.beadsPrefix'] !== 'ours')),
    'retired primary requires a complete registered route');
  stageControl(plan, 'publisher'); stageControl(plan, 'primary');
  activateTargetHook(publisher, plan.targets.publisher, plan.planId, configs.publisher, options, 'publisher');
  failIfRequested(options, 'afterPublisherHook');
  for (const [key, value] of Object.entries({ 'overgate.beadsPublisher': plan.registration.publisher,
    'overgate.beadsCli': plan.registration.cli, 'overgate.beadsPrefix': plan.registration.prefix })) {
    if (targetConfigStage(publisher, plan.targets.publisher, plan.registration)[key] !== 'ours')
      git(publisher.root, ['config', '--local', '--replace-all', key, value]);
  }
  requireThat(REGISTRATION_KEYS.every(key => targetConfigStage(publisher, plan.targets.publisher, plan.registration)[key] === 'ours'),
    'publisher registration incomplete');
  if (configs.primary['overgate.beadsPublisher'] !== 'ours') {
    git(primary.root, ['config', '--local', '--replace-all', 'overgate.beadsPublisher', plan.registration.publisher]);
    failIfRequested(options, 'afterPublisherConfig');
  }
  const afterPublisherRegistration = targetConfigStage(primary, plan.targets.primary, plan.registration);
  if (afterPublisherRegistration['overgate.beadsCli'] !== 'ours')
    git(primary.root, ['config', '--local', '--replace-all', 'overgate.beadsCli', plan.registration.cli]);
  const afterCliRegistration = targetConfigStage(primary, plan.targets.primary, plan.registration);
  if (afterCliRegistration['overgate.beadsPrefix'] !== 'ours')
    git(primary.root, ['config', '--local', '--replace-all', 'overgate.beadsPrefix', plan.registration.prefix]);
  const beforePrimaryActivation = targetConfigStage(primary, plan.targets.primary, plan.registration);
  activateTargetHook(primary, plan.targets.primary, plan.planId, beforePrimaryActivation, options, 'primary');
  writeReceipt(plan, 'publisher'); failIfRequested(options, 'afterPublisherReceipt');
  writeReceipt(plan, 'primary');
  inspectControl(plan, 'publisher'); inspectControl(plan, 'primary');
  return plan;
}

function parseCli(argv) {
  if (argv[0] === '--install') return { install: argv[1] };
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    requireThat(argv[i].startsWith('--') && argv[i + 1] && argv[i] !== '--enable-approved-repair', 'invalid setup arguments');
    out[argv[i].slice(2)] = argv[++i];
  }
  return out;
}
function assertTrustedHelperPath(root) {
  const publisher = repo(root, 'publisher');
  const expected = path.join(publisher.root, 'scripts', 'bd-publisher-setup.mjs');
  requireThat(fileURLToPath(import.meta.url) === expected, 'trusted publisher helper path required (run target main copy)');
  trustedMain(publisher);
  requireThat(fs.readFileSync(expected).equals(git(publisher.root, ['show', 'HEAD:scripts/bd-publisher-setup.mjs'], { encoding: 'buffer' })),
    'trusted publisher helper bytes differ from main');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = parseCli(process.argv.slice(2));
    const publisherRoot = args.install ? JSON.parse(fs.readFileSync(args.install, 'utf8')).targets.publisher.root : args['publisher-root'];
    assertTrustedHelperPath(publisherRoot);
    const result = args.install ? installPublisherControl(args.install) : preparePublisherControl({
      primaryRoot: args['primary-root'], publisherRoot: args['publisher-root'], qualifiedCli: args['qualified-cli'],
      output: args.output });
    console.log(`${args.install ? 'INSTALL' : 'PREPARE'} plan ${result.planId}`);
  } catch (error) { console.error(`bd-publisher-setup: ${error.message}`); process.exit(1); }
}
