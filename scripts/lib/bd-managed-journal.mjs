// Journal — восстановление незавершённой публикации, не источник task state.
// Локальный lock canonical main обязан удерживать вызывающий helper.
import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { hostname } from 'node:os';
import { canonical, validateQueue, emptyLedger, parseLedger, assertLedgerExtension } from './bd-managed-contract.mjs';
import { assertExactSnapshot } from './bd-snapshot.mjs';

const sha = value => typeof value === 'string' && /^[0-9a-f]{40}$/.test(value);
const hash = value => createHash('sha256').update(canonical(value)).digest('hex');
const requireThat = (value, reason) => { if (!value) throw new Error(`journal: ${reason}`); };
const activeFile = directory => path.join(directory, 'active.json');
function canonicalDirectory(directory, create = false) {
  const absolute = path.resolve(directory);
  let ancestor = absolute;
  while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
  requireThat(fs.realpathSync(ancestor) === ancestor, 'symlink/noncanonical ancestor');
  if (create) fs.mkdirSync(absolute, { recursive: true, mode: 0o700 });
  if (fs.existsSync(absolute)) requireThat(fs.realpathSync(absolute) === absolute && fs.lstatSync(absolute).isDirectory(), 'noncanonical directory');
  return absolute;
}
function validateJournal(value) {
  requireThat(value && typeof value === 'object' && !Array.isArray(value), 'expected object');
  const allowed = ['version', 'phase', 'queue', 'queue_hash', 'base', 'current_base', 'candidate', 'attempts', 'conflicts', 'conflict_base', 'published', 'resolutions'];
  for (const key of Object.keys(value)) requireThat(allowed.includes(key), `unsupported ${key}`);
  requireThat(value.version === 1 && ['prepared', 'pending', 'conflict', 'published'].includes(value.phase), 'unsupported phase/version');
  requireThat(Array.isArray(value.queue) && value.queue.length > 0, 'nonempty queue required');
  validateQueue(value.queue.map(canonical).join('\n'));
  requireThat(value.queue_hash === hash(value.queue), 'queue hash mismatch');
  requireThat(sha(value.base) && value.base === value.queue[0].base && sha(value.current_base), 'base invalid');
  requireThat(value.candidate === null || sha(value.candidate), 'candidate invalid');
  requireThat(value.phase !== 'pending' || sha(value.candidate), 'pending candidate required');
  requireThat(Number.isSafeInteger(value.attempts) && value.attempts >= 0 && value.attempts <= 2, 'attempt limit exceeded');
  requireThat(value.conflicts === undefined || Array.isArray(value.conflicts), 'conflicts invalid');
  requireThat(value.conflict_base === undefined || sha(value.conflict_base), 'conflict base invalid');
  requireThat(value.phase !== 'published' || sha(value.published), 'published SHA required');
  if (value.resolutions !== undefined) {
    requireThat(Array.isArray(value.resolutions) && value.resolutions.length > 0, 'resolution lineage invalid');
    for (const item of value.resolutions) {
      requireThat(item && Object.keys(item).sort().join(',') === 'archive,archive_hash,queue,queue_hash', 'resolution record invalid');
      requireThat(/^[0-9a-f]{64}-[0-9a-f-]{36}\.json$/.test(item.archive) && /^[0-9a-f]{64}$/.test(item.archive_hash), 'resolution archive invalid');
      requireThat(Array.isArray(item.queue) && item.queue.length > 0 && hash(item.queue) === item.queue_hash, 'resolution queue hash invalid');
      validateQueue(item.queue.map(canonical).join('\n'));
    }
  }
  return value;
}
export function readJournal(directory) {
  const root = canonicalDirectory(directory), file = activeFile(root);
  try {
    const stat = fs.lstatSync(file);
    requireThat(stat.isFile() && !stat.isSymbolicLink(), 'active file is not regular');
    return validateJournal(JSON.parse(fs.readFileSync(file, 'utf8')));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw new Error(`journal: ${error.message}`);
  }
}
export function saveJournal(directory, value) {
  validateJournal(value);
  const root = canonicalDirectory(directory, true), previous = readJournal(root);
  if (previous && previous.phase !== 'published') {
    requireThat(previous.queue_hash === value.queue_hash && canonical(previous.queue) === canonical(value.queue), 'pending queue cannot be replaced');
    requireThat(value.attempts >= previous.attempts, 'attempt count cannot decrease');
    requireThat(previous.base === value.base, 'original base cannot change');
    requireThat(canonical(previous.resolutions || []) === canonical(value.resolutions || []), 'resolution lineage cannot change');
    requireThat(!previous.candidate || value.candidate, 'pending candidate cannot be discarded');
  }
  return writeActive(root, value);
}
function writeActive(root, value) {
  const temporary = path.join(root, `active.${randomUUID()}.tmp`);
  let fd;
  try {
    fd = fs.openSync(temporary, 'wx', 0o600);
    fs.writeFileSync(fd, canonical(value) + '\n'); fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined;
    fs.renameSync(temporary, activeFile(root));
    // Windows не предоставляет fsync directory; file fsync и atomic rename остаются.
    let dirFd;
    try { dirFd = fs.openSync(root, 'r'); fs.fsyncSync(dirFd); }
    catch (error) { if (process.platform !== 'win32' || !['EINVAL', 'EPERM', 'EISDIR', 'EACCES'].includes(error.code)) throw error; }
    finally { if (dirFd !== undefined) fs.closeSync(dirFd); }
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  return value;
}
export function openJournal(directory, intents) {
  validateQueue(intents.map(canonical).join('\n'));
  requireThat(intents.length, 'nonempty queue required');
  const previous = readJournal(directory), queueHash = hash(intents);
  if (previous && previous.queue_hash === queueHash) return previous;
  requireThat(!previous || previous.phase === 'published', 'pending publication/conflict: finish existing queue first');
  return saveJournal(directory, { version: 1, phase: 'prepared', queue: intents, queue_hash: queueHash,
    base: intents[0].base, current_base: intents[0].base, candidate: null, attempts: 0,
    ...(previous?.resolutions ? { resolutions: previous.resolutions } : {}) });
}

export function resolveConflict(directory, intents, expectedHash) {
  validateQueue(intents.map(canonical).join('\n'));
  const previous = readJournal(directory);
  requireThat(previous?.phase === 'conflict', 'only terminal conflict may be explicitly resolved');
  requireThat(previous.queue_hash === expectedHash, 'conflict queue hash mismatch');
  const oldIds = new Set(previous.queue.map(intent => intent.intent_id));
  requireThat(intents.length && intents.every(intent => !oldIds.has(intent.intent_id)), 'resolution requires new op IDs');
  // R мог продвинуться после конфликта: новый frozen base проверит apply/replay,
  // а исходный conflict_base остаётся в неизменяемом архиве.
  const root = canonicalDirectory(directory), archive = canonicalDirectory(path.join(root, 'conflicts'), true);
  const file = path.join(archive, `${previous.queue_hash}-${randomUUID()}.json`), fd = fs.openSync(file, 'wx', 0o600);
  try { fs.writeFileSync(fd, canonical(previous) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  const next = { version: 1, phase: 'prepared', queue: intents, queue_hash: hash(intents), base: intents[0].base,
    current_base: intents[0].base, candidate: null, attempts: 0,
    resolutions: [...(previous.resolutions || []), { archive: path.basename(file), archive_hash: hash(previous), queue: intents, queue_hash: hash(intents) }] };
  validateJournal(next);
  return writeActive(root, next);
}

// Старый one-file writer может сделать FF, удалив ledger. Проверяем цепочку,
// а не только наличие файла на tip; anchor сохраняется после первого managed чтения.
export function validateManagedHistory(history, anchor = null) {
  requireThat(Array.isArray(history) && history.length > 0, 'history unavailable');
  if (anchor) requireThat(history.some(commit => commit.sha === anchor), 'history anchor missing/rewound');
  let ledger = emptyLedger(), activated = false, activation = null;
  const seen = new Set();
  for (const commit of history) {
    requireThat(sha(commit.sha) && !seen.has(commit.sha), 'invalid/duplicate history commit'); seen.add(commit.sha);
    if (commit.ledger === null) {
      requireThat(!activated, 'managed ledger downgrade/loss in retained history');
      continue;
    }
    const next = parseLedger(canonical(commit.ledger));
    assertLedgerExtension(ledger, next);
    if (!activated) activation = commit.sha;
    activated = true; ledger = next;
  }
  return { ledger, activated, activation, tip: history.at(-1).sha };
}

const preservationNames = { legacy_snapshot: 'legacy-snapshot.jsonl', pending_queue: 'pending-queue.jsonl', adoption_queue: 'adoption-queue.jsonl' };
export function verifyPreservation(directory, rawManifest, { base, snapshot, legacyPresent, pendingPresent }) {
  let manifest;
  try { manifest = JSON.parse(rawManifest); } catch { throw new Error('bootstrap: invalid manifest JSON'); }
  requireThat(manifest && typeof manifest === 'object' && !Array.isArray(manifest), 'bootstrap manifest object required');
  for (const key of Object.keys(manifest)) requireThat(['version', 'base', 'actor', 'outcome', 'artifacts'].includes(key), `bootstrap unsupported ${key}`);
  requireThat(manifest.version === 1 && manifest.base === base && sha(base), 'bootstrap frozen base mismatch');
  requireThat(/^agent-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(manifest.actor || ''), 'bootstrap actor invalid');
  requireThat(['verified-clean', 'verified-absent', 'pending-retained'].includes(manifest.outcome), 'bootstrap outcome invalid');
  requireThat(typeof legacyPresent === 'boolean' && typeof pendingPresent === 'boolean', 'bootstrap actual legacy/pending context unknown');
  requireThat(manifest.artifacts && typeof manifest.artifacts === 'object' && !Array.isArray(manifest.artifacts), 'bootstrap artifacts required');
  const root = canonicalDirectory(directory), contents = {};
  for (const [kind, item] of Object.entries(manifest.artifacts)) {
    requireThat(Object.hasOwn(preservationNames, kind) && item && typeof item === 'object' && !Array.isArray(item), 'bootstrap artifact kind invalid');
    requireThat(Object.keys(item).length === 2 && item.name === preservationNames[kind] && /^[0-9a-f]{64}$/.test(item.sha256 || ''), 'bootstrap artifact name/hash invalid');
    const file = path.join(root, item.name), stat = fs.lstatSync(file);
    requireThat(stat.isFile() && !stat.isSymbolicLink() && fs.realpathSync(file) === file, 'bootstrap artifact must be own regular canonical file');
    const bytes = fs.readFileSync(file);
    requireThat(createHash('sha256').update(bytes).digest('hex') === item.sha256, 'bootstrap artifact hash mismatch');
    contents[kind] = bytes.toString('utf8');
  }
  let adoption = [];
  if (manifest.outcome === 'verified-absent') {
    requireThat(!legacyPresent && !pendingPresent && Object.keys(contents).length === 0, 'bootstrap absent claim contradicts actual context');
  } else {
    requireThat(Object.hasOwn(contents, 'legacy_snapshot'), 'bootstrap legacy snapshot artifact required');
    if (manifest.outcome === 'verified-clean') {
      requireThat(!pendingPresent && Object.keys(contents).length === 1, 'bootstrap pending work cannot be declared clean');
      assertExactSnapshot(snapshot, contents.legacy_snapshot);
    } else {
      requireThat(Object.hasOwn(contents, 'pending_queue') && Object.hasOwn(contents, 'adoption_queue'), 'bootstrap pending/adoption artifacts required');
      adoption = validateQueue(contents.adoption_queue);
      requireThat(adoption.length && adoption.every(intent => intent.base === base && intent.actor === manifest.actor), 'bootstrap adoption base/actor invalid');
    }
  }
  return { version: 1, base, actor: manifest.actor, outcome: manifest.outcome, artifacts: manifest.artifacts,
    manifest_hash: hash(manifest), adoption_hash: adoption.length ? hash(adoption) : null,
    adoption: adoption.map(intent => ({ intent_id: intent.intent_id, payload_hash: intent.payload_hash })) };
}

export function assertBootstrapQueue(acknowledgement, intents, ledger, directory) {
  requireThat(acknowledgement?.version === 1 && sha(acknowledgement.base), 'bootstrap acknowledgement required');
  parseLedger(canonical(ledger));
  if (acknowledgement.outcome !== 'pending-retained') {
    requireThat(['verified-clean', 'verified-absent'].includes(acknowledgement.outcome), 'bootstrap outcome invalid');
    return;
  }
  const outcomes = new Map(ledger.outcomes.map(outcome => [outcome.intent.intent_id, outcome.payload_hash]));
  const complete = queue => queue.every(intent => outcomes.get(intent.intent_id) === intent.payload_hash);
  requireThat(acknowledgement.adoption?.length, 'bootstrap adoption evidence required');
  if (complete(acknowledgement.adoption) || hash(intents) === acknowledgement.adoption_hash) return;
  // Explicit --resolve сохраняет terminal journal/candidate. Проверяем всю цепочку
  // до оригинальной adoption queue, а не считаем любой новый journal разрешением.
  const lineage = directory ? readJournal(directory)?.resolutions || [] : [];
  let predecessor = null;
  for (let index = 0; index < lineage.length; index++) {
    const item = lineage[index], file = path.join(canonicalDirectory(directory), 'conflicts', item.archive);
    const stat = fs.lstatSync(file);
    requireThat(stat.isFile() && !stat.isSymbolicLink() && fs.realpathSync(file) === file, 'adoption resolution archive must be own regular file');
    const previous = validateJournal(JSON.parse(fs.readFileSync(file, 'utf8')));
    requireThat(hash(previous) === item.archive_hash && previous.phase === 'conflict'
      && canonical(previous.resolutions || []) === canonical(lineage.slice(0, index)), 'adoption resolution lineage mismatch');
    // Более ранние resolutions могли предшествовать этому explicit bootstrap.
    if (predecessor === null && previous.queue_hash !== acknowledgement.adoption_hash) continue;
    requireThat(previous.queue_hash === (predecessor || acknowledgement.adoption_hash), 'adoption resolution lineage mismatch');
    const oldIds = new Set(previous.queue.map(intent => intent.intent_id));
    requireThat(item.queue.every(intent => !oldIds.has(intent.intent_id)), 'adoption resolution requires new op IDs');
    if (complete(item.queue)) return; // Adoption завершена; поздние unrelated conflicts её не открывают снова.
    predecessor = item.queue_hash;
  }
  const replacement = lineage.at(-1);
  requireThat(predecessor && replacement && (hash(intents) === replacement.queue_hash || complete(replacement.queue)),
    'bootstrap: publish retained adoption queue first; on conflict preserve it and explicitly prepare reviewed resolution');
}

// Preinitialized record + hardlink: EEXIST никогда не заменяет unknown empty dir.
export function acquireManagedLock(directory) {
  const root = canonicalDirectory(directory, true), file = path.join(root, 'transaction.lock'), reclaim = file + '.reclaim';
  const owner = { version: 1, host: hostname(), pid: process.pid, nonce: randomUUID() };
  const staging = path.join(root, `.owner-${owner.nonce}.json`), fd = fs.openSync(staging, 'wx', 0o600);
  try { fs.writeFileSync(fd, canonical(owner)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  const readOwner = target => {
    const stat = fs.lstatSync(target);
    requireThat(stat.isFile() && !stat.isSymbolicLink(), 'unknown lock preserved (not regular owner record)');
    const value = JSON.parse(fs.readFileSync(target, 'utf8'));
    requireThat(value.version === 1 && value.host === hostname() && Number.isInteger(value.pid) && value.pid > 0 && typeof value.nonce === 'string', 'unknown/foreign lock preserved');
    return value;
  };
  const dead = previous => {
    try { process.kill(previous.pid, 0); return false; }
    catch (error) { return error.code === 'ESRCH'; }
  };
  let claimed = false, acquired = false;
  try {
    requireThat(!fs.existsSync(reclaim), 'local lock recovery already active/interrupted; owner metadata retained');
    try { fs.linkSync(staging, file); acquired = true; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const previous = readOwner(file);
      requireThat(dead(previous), 'another managed transaction is active (PID alive/EPERM is not ESRCH)');
      fs.linkSync(staging, reclaim); claimed = true;
      requireThat(canonical(readOwner(file)) === canonical(previous) && dead(previous), 'lock owner changed during recovery');
      fs.unlinkSync(file);
      fs.linkSync(staging, file); acquired = true;
    }
  } finally {
    if (claimed && canonical(readOwner(reclaim)) === canonical(owner)) fs.unlinkSync(reclaim);
    fs.unlinkSync(staging);
  }
  requireThat(acquired, 'managed lock unavailable');
  return () => { requireThat(canonical(readOwner(file)) === canonical(owner), 'lock owner changed; preserved'); fs.unlinkSync(file); };
}
