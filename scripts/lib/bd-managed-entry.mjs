#!/usr/bin/env node
// Existing helper entrypoint: typed data preparation, bootstrap и managed publication.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { randomUUID } from 'node:crypto';
import { canonical, prepareQueue, validateQueue, planReplay, replayHandles, validateBlockingGraph } from './bd-managed-contract.mjs';
import { parseSnapshot } from './bd-snapshot.mjs';
import { ManagedGit, ZERO } from './bd-managed-git.mjs';
import { materializeFresh } from './bd-managed-cli.mjs';
import { acquireManagedLock, readJournal, verifyPreservation, assertBootstrapQueue, resolveConflict } from './bd-managed-journal.mjs';
import { runTransaction } from './bd-managed-transaction.mjs';

const requireThat = (value, message) => { if (!value) throw new Error(message); };
const exists = file => { try { fs.lstatSync(file); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; } };
function regular(file, extension) {
  const absolute = path.resolve(file);
  requireThat(absolute.endsWith(extension) && !path.basename(absolute).startsWith('.env'), `expected ${extension} artifact`);
  const stat = fs.lstatSync(absolute);
  requireThat(stat.isFile() && !stat.isSymbolicLink() && fs.realpathSync(absolute) === absolute, 'artifact must be regular canonical file');
  return fs.readFileSync(absolute, 'utf8');
}
function writeJSON(file, value) {
  const temporary = file + '.' + randomUUID() + '.tmp', fd = fs.openSync(temporary, 'wx', 0o600);
  try { fs.writeFileSync(fd, canonical(value) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  try { fs.renameSync(temporary, file); } finally { if (exists(temporary)) fs.unlinkSync(temporary); }
}
function resolveBinary(name) {
  const candidates = path.isAbsolute(name) || name.includes('/') || name.includes('\\') ? [path.resolve(name)]
    : (process.env.PATH || '').split(path.delimiter).flatMap(directory => [path.join(directory, name), ...(process.platform === 'win32' ? [path.join(directory, name + '.exe')] : [])]);
  for (const candidate of candidates) {
    try { fs.accessSync(candidate, fs.constants.X_OK); if (fs.statSync(candidate).isFile()) return fs.realpathSync(candidate); } catch {}
  }
  throw new Error(`qualified CLI unavailable: ${name}; retain prepared queue for an authorized publisher`);
}
function parseArgs(args) {
  const result = { mode: 'apply', dry: false };
  const mode = next => { requireThat(result.mode === 'apply', 'only one operation mode allowed'); result.mode = next; };
  for (let i = 0; i < args.length; i++) {
    const item = args[i], value = () => { requireThat(i + 1 < args.length, `${item} requires value`); return args[++i]; };
    if (item === '--prepare') mode('prepare');
    else if (item === '--bootstrap') { mode('bootstrap'); result.manifest = value(); }
    else if (item === '--retry') mode('retry');
    else if (item === '--read-state') mode('read');
    else if (item === '--resolve') { mode('resolve'); result.resolve = value(); }
    else if (item === '--dry-run') result.dry = true;
    else if (['--base', '--actor', '--output'].includes(item)) { const key = item.slice(2); requireThat(!result[key], `duplicate ${item}`); result[key] = value(); }
    else if (item.startsWith('-')) throw new Error(`unknown flag ${item}; managed transactions cannot bypass snapshot integrity/publication`);
    else { requireThat(!result.queue, 'at most one queue path'); result.queue = item; }
  }
  requireThat(result.mode === 'prepare' || !result.base && !result.actor && !result.output, 'prepare-only option');
  requireThat(!['bootstrap', 'retry', 'read'].includes(result.mode) || !result.queue && !result.dry, 'unexpected queue/dry-run');
  return result;
}

export function runEntry(args) {
  const options = parseArgs(args), repository = new ManagedGit({ cwd: process.cwd() });
  if (options.mode === 'read') {
    const state = repository.readPublished();
    return { status: 'validated', R: state.R, records: parseSnapshot(state.snapshot).length, managed: state.activated, legacy_store: 'untouched' };
  }
  requireThat(process.env.BD_APPLY_SKIP_SYNC_CHECK !== '1', 'skip-sync is unsupported: managed transactions require frozen published state');
  requireThat(!exists(path.join(repository.common, 'bd-apply.lock.d')), 'legacy/unknown apply lock preserved; finish the existing publisher before managed activation');
  const control = path.join(repository.common, 'overgate-bd-managed'), preservation = path.join(control, 'preservation'), ackFile = path.join(control, 'bootstrap.json');
  let release;
  try { release = acquireManagedLock(control); } catch (error) { error.exitCode = 4; throw error; }
  const roots = [], temporaryParent = fs.realpathSync(os.tmpdir());
  try {
    const state = repository.readPublished();
    if (options.mode === 'bootstrap') {
      requireThat(path.resolve(options.manifest) === path.join(preservation, 'preservation.json'), 'bootstrap manifest must be known .git/overgate-bd-managed/preservation/preservation.json');
      const raw = regular(options.manifest, '.json');
      const legacyPresent = ['dolt', 'embeddeddolt', 'redirect', 'dolt-server.pid', 'dolt-server.port'].some(name => exists(path.join(repository.cwd, '.beads', name)));
      const queues = path.join(repository.cwd, '.bd-intents'), receipts = path.join(repository.common, 'bd-receipts');
      const pendingPresent = exists(receipts) && fs.readdirSync(receipts).length > 0 || exists(queues) && fs.readdirSync(queues).some(name => name.endsWith('.jsonl'));
      const context = { base: state.R, snapshot: state.snapshot, legacyPresent, pendingPresent };
      const evidence = verifyPreservation(preservation, raw, context);
      writeJSON(ackFile, { version: 1, manifest: JSON.parse(raw), evidence, context: { legacyPresent, pendingPresent } });
      return { status: 'bootstrapped', base: state.R, actor: evidence.actor, outcome: evidence.outcome, legacy_store: 'untouched' };
    }
    if (options.mode === 'prepare') {
      requireThat(options.base && options.actor && options.output && options.queue && !options.dry, 'prepare requires --base --actor --output and typed input path');
      requireThat(options.base === ZERO ? state.R === ZERO : state.history?.includes(options.base), 'prepare base must be explicit frozen published history commit');
      const frozen = repository.readAt(options.base), rows = parseSnapshot(frozen.snapshot).map(({ record }) => record);
      const intents = prepareQueue(regular(options.queue, '.jsonl'), rows, frozen.ledger, options);
      requireThat(intents.length, 'prepare requires nonempty typed input');
      const output = path.resolve(options.output);
      requireThat(output.endsWith('.jsonl') && !path.basename(output).startsWith('.env') && fs.realpathSync(path.dirname(output)) === path.dirname(output), 'output must be own canonical .jsonl path');
      const fd = fs.openSync(output, 'wx', 0o600);
      try { fs.writeFileSync(fd, intents.map(canonical).join('\n') + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      return { status: 'prepared', base: options.base, actor: options.actor, output, operations: intents.length, payload_hashes: intents.map(intent => intent.payload_hash) };
    }
    requireThat(exists(ackFile), 'managed bootstrap required: preserve legacy/pending artifacts under .git/overgate-bd-managed/preservation, then --bootstrap preservation.json; legacy DB stays untouched');
    const saved = JSON.parse(regular(ackFile, '.json'));
    requireThat(saved.version === 1 && saved.context && saved.evidence, 'bootstrap acknowledgement invalid');
    const frozen = repository.readAt(saved.evidence.base);
    const acknowledgement = verifyPreservation(preservation, canonical(saved.manifest), { base: saved.evidence.base, snapshot: frozen.snapshot, ...saved.context });
    requireThat(canonical(acknowledgement) === canonical(saved.evidence), 'bootstrap evidence changed');
    let intents;
    if (options.mode === 'retry') {
      const active = readJournal(control); requireThat(active, 'no managed pending publication; raw legacy bd export is unsupported, use prepare/apply'); intents = active.queue;
    } else {
      if (!options.queue) {
        const directory = path.join(repository.cwd, '.bd-intents'), names = exists(directory) ? fs.readdirSync(directory).filter(name => name.endsWith('.v2.jsonl')) : [];
        requireThat(names.length === 1, 'specify one prepared .v2.jsonl queue explicitly; legacy inputs require --prepare/adoption');
        options.queue = path.join(directory, names[0]);
      }
      intents = validateQueue(regular(options.queue, '.jsonl'));
    }
    requireThat(intents.length, 'nonempty prepared queue required');
    if (options.mode === 'resolve' && !options.dry) {
      const previous = readJournal(control);
      requireThat(previous, 'terminal conflict journal required');
      assertBootstrapQueue(acknowledgement, previous.queue, state.ledger, control);
      resolveConflict(control, intents, options.resolve);
    }
    assertBootstrapQueue(acknowledgement, intents, state.ledger, control);
    if (options.dry) {
      const rows = parseSnapshot(state.snapshot).map(({ record }) => record), plan = planReplay(intents, rows, state.ledger);
      requireThat(!plan.conflicts.length, 'dry-run precondition conflict');
      validateBlockingGraph(rows, plan.pending, replayHandles(intents, state.ledger));
      return { status: 'validated', R: state.R, pending: plan.pending.length, already_published: plan.skipped.length };
    }
    const materialize = (snapshot, actor) => {
      const root = fs.mkdtempSync(path.join(temporaryParent, 'overgate-bd-managed-')); roots.push(root);
      try { return materializeFresh({ directory: root, binary: resolveBinary(process.env.BD_BIN || 'bd'), actor, snapshot }); }
      catch (error) { error.exitCode = 3; throw error; }
    };
    return runTransaction({ repository, directory: control, intents, acknowledgement, materialize });
  } finally {
    for (const root of roots) {
      requireThat(path.resolve(root).startsWith(temporaryParent + path.sep) && fs.realpathSync(root) === root, 'unsafe fresh root cleanup');
      fs.rmSync(root, { recursive: true, force: true });
    }
    release();
  }
}

try { console.log(JSON.stringify(runEntry(process.argv.slice(2)))); }
catch (error) {
  if (error.summary) console.log(JSON.stringify(error.summary));
  console.error(`ERROR: ${error.message}`);
  if (error.conflicts) console.error(JSON.stringify({ conflicts: error.conflicts }));
  process.exit(error.exitCode || (error.code === 'PENDING_PUBLICATION' ? 7 : error.code === 'PRECONDITION_CONFLICT' ? 8 : 2));
}
