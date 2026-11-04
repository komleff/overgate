// Узкий pre-push gate: retired checkout не публикует Beads, managed publisher
// принимает только точного CAS-потомка с сохранённым protocol/ledger.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { ManagedGit } from './bd-managed-git.mjs';
import { assertLedgerExtension } from './bd-managed-contract.mjs';

const ZERO = '0'.repeat(40);
const BEADS_REF = 'refs/heads/beads-backup';
const SNAPSHOT = '.beads/issues.jsonl';
const MANAGED_PATHS = new Set([SNAPSHOT, '.beads/overgate-outcomes-v1.json', '.beads/overgate-managed-v1.json']);
const oidPattern = /^[0-9a-f]{40}$/;
const sha256 = value => createHash('sha256').update(value).digest('hex');
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const GIT_ENVIRONMENT = ['GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_NAMESPACE'];

function git(cwd, args, { encoding = 'utf8' } = {}) {
  const environment = { ...process.env, MSYS2_ARG_CONV_EXCL: '*' };
  for (const name of GIT_ENVIRONMENT) delete environment[name];
  return execFileSync('git', args, { cwd, encoding, timeout: 15000, maxBuffer: 32 * 1024 * 1024,
    env: environment, stdio: ['ignore', 'pipe', 'pipe'] });
}

function withCleanGitEnvironment(action) {
  const saved = new Map(GIT_ENVIRONMENT.map(name => [name, process.env[name]]));
  for (const name of GIT_ENVIRONMENT) delete process.env[name];
  try { return action(); }
  finally {
    for (const [name, value] of saved) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

export function parsePrePushInput(input) {
  requireThat(Buffer.isBuffer(input), 'pre-push input must be bytes');
  if (input.length === 0) return [];
  requireThat(input.at(-1) === 0x0a && !input.includes(0x00) && !input.includes(0x0d), 'malformed pre-push input framing');
  let raw;
  try { raw = new TextDecoder('utf-8', { fatal: true }).decode(input); }
  catch { throw new Error('malformed pre-push input encoding'); }
  return raw.slice(0, -1).split('\n').map((line, index) => {
    const match = /^(\S+) ([0-9a-f]{40}) (refs\/\S+) ([0-9a-f]{40})$/.exec(line);
    requireThat(match, `malformed pre-push record ${index + 1}`);
    return { localRef: match[1], localOid: match[2], remoteRef: match[3], remoteOid: match[4] };
  });
}

function commitParents(repositoryRoot, oid, label) {
  requireThat(oidPattern.test(oid) && oid !== ZERO, `${label} object id invalid`);
  try { requireThat(git(repositoryRoot, ['cat-file', '-t', oid]).trim() === 'commit', `${label} is not a commit`); }
  catch { throw new Error(`unknown ${label} object`); }
  const raw = git(repositoryRoot, ['cat-file', '-p', oid]);
  return raw.split('\n').filter(line => line.startsWith('parent ')).map(line => line.slice(7));
}

function requireSoleParent(repositoryRoot, candidate, remote) {
  const parents = commitParents(repositoryRoot, candidate, 'candidate');
  requireThat(parents.length === 1 && parents[0] === remote, 'candidate sole parent must equal negotiated remote OID');
}

function tree(repositoryRoot, oid) {
  const raw = git(repositoryRoot, ['ls-tree', '-r', '-z', '--full-tree', oid], { encoding: 'buffer' });
  const result = new Map();
  for (const record of raw.subarray(0, Math.max(0, raw.length - 1)).toString('utf8').split('\0').filter(Boolean)) {
    const match = /^(\d+) (\S+) ([0-9a-f]+)\t(.+)$/.exec(record);
    requireThat(match, 'unexpected Git tree record');
    result.set(match[4], `${match[1]} ${match[2]} ${match[3]}`);
  }
  return result;
}

function changedPaths(repositoryRoot, before, after) {
  const raw = git(repositoryRoot, ['diff-tree', '--no-commit-id', '--name-only', '-r', '-z', before, after], { encoding: 'buffer' });
  return raw.toString('utf8').split('\0').filter(Boolean);
}

function validateManaged(repositoryRoot, record, readIssuePrefix) {
  if (record.remoteOid === ZERO) requireThat(commitParents(repositoryRoot, record.localOid, 'candidate').length === 0, 'initial candidate must be root commit');
  else requireSoleParent(repositoryRoot, record.localOid, record.remoteOid);
  const changes = record.remoteOid === ZERO ? [...tree(repositoryRoot, record.localOid).keys()] : changedPaths(repositoryRoot, record.remoteOid, record.localOid);
  requireThat(changes.every(name => MANAGED_PATHS.has(name)), 'managed candidate changed a path outside the protocol snapshot/ledger set');
  const candidateTree = tree(repositoryRoot, record.localOid);
  for (const name of MANAGED_PATHS) requireThat(candidateTree.get(name)?.startsWith('100644 blob '), `managed candidate ${name} missing or mode invalid`);
  const repository = new ManagedGit({ cwd: repositoryRoot, readIssuePrefix });
  const current = repository.readAt(record.remoteOid), candidate = repository.readAt(record.localOid);
  requireThat(candidate.activated, 'managed candidate must activate/preserve protocol; raw snapshot push denied');
  assertLedgerExtension(current.ledger, candidate.ledger);
}

function routeDiagnostic(repositoryRoot) {
  const get = key => {
    try { return git(repositoryRoot, ['config', '--local', '--get', key]).trim(); }
    catch { return '<not registered>'; }
  };
  return `use registered publisher ${get('overgate.beadsPublisher')} with explicit CLI ${get('overgate.beadsCli')} and scripts/bd-apply-intents.sh`;
}

export function guardPush({ config, input, readIssuePrefix }) {
  return withCleanGitEnvironment(() => {
    requireThat(config?.version === 1 && ['retired', 'managed'].includes(config.mode), 'invalid publisher guard config');
    const repositoryRoot = fs.realpathSync(config.repositoryRoot);
    for (const record of parsePrePushInput(input)) {
      if (record.remoteRef !== BEADS_REF) continue;
      requireThat(record.localOid !== ZERO, 'beads-backup branch deletion denied');
      if (record.remoteOid !== ZERO) {
        try { commitParents(repositoryRoot, record.remoteOid, 'negotiated remote'); }
        catch { throw new Error('unknown negotiated remote object; retry through the existing CAS helper'); }
      }
      if (config.mode === 'managed') validateManaged(repositoryRoot, record, readIssuePrefix);
      else throw new Error(`retired checkout cannot publish beads-backup; ${routeDiagnostic(repositoryRoot)}`);
    }
    return input;
  });
}

function cliArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 2) {
    requireThat(['--config', '--config-sha256', '--input'].includes(argv[i]) && argv[i + 1], 'usage: guard --config FILE --config-sha256 SHA --input FILE');
    result[argv[i].slice(2)] = argv[i + 1];
  }
  requireThat(result.config && /^[0-9a-f]{64}$/.test(result['config-sha256'] || '') && result.input, 'guard arguments incomplete');
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = cliArgs(process.argv.slice(2));
    const configRaw = fs.readFileSync(args.config);
    requireThat(sha256(configRaw) === args['config-sha256'], 'guard config owned hash mismatch');
    const config = JSON.parse(configRaw);
    requireThat(config.sourcePins && typeof config.sourcePins === 'object', 'installed guard source pins missing');
    guardPush({ config, input: fs.readFileSync(args.input) });
  } catch (error) {
    console.error(`OverGate Beads pre-push denied: ${error.message}`);
    process.exit(1);
  }
}
