// Owned fresh store — disposable CLI projection. Legacy workspace не открывается.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { parseSnapshot, normalizeSnapshot, assertExactSnapshot } from './bd-snapshot.mjs';
import { cleanGitEnvironment } from './bd-git-environment.mjs';
import { canonical, validateQueue, planReplay, replayHandles, validateBlockingGraph, appendOutcome, assertLedgerExtension, timestampIdentity, getProjectPrefix, isRealId } from './bd-managed-contract.mjs';

const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const defaultRun = (binary, args, options) => execFileSync(binary, args, { ...options, encoding: 'utf8', maxBuffer: 2 * 1024 * 1024 });
// Actual qualified builds; новая версия/платформа требует disposable proof.
const qualifiedBuilds = new Map([
  ['cd6827a3b3ec5b212131337201df1e623e028bce15065903fb70291e0ac4a355', 'darwin'],
  ['b1f3609fea1d9f0f19b2ed49098b3628acfa6ca115aa28b01a1ee178c3a214de', 'win32'],
  ['54fc0e0581ce4c5487a5b242f0a4f34af1ef09cf056e164a1af63a6ec7aa1e0e', 'linux'],
]);
function streamFingerprint(binary) {
  const hash = createHash('sha256'), buffer = Buffer.alloc(1024 * 1024), started = Date.now(), fd = fs.openSync(binary, 'r');
  try {
    let size;
    while ((size = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      requireThat(Date.now() - started <= 30000, 'CLI fingerprint deadline exceeded'); hash.update(buffer.subarray(0, size));
    }
    return hash.digest('hex');
  } finally { fs.closeSync(fd); }
}
export function qualifyBinary(binary, { fingerprint = streamFingerprint, platform = process.platform } = {}) {
  requireThat(['darwin', 'win32', 'linux'].includes(platform), 'native writer platform not qualified: retain queue and use an available qualified publisher/disposable qualification');
  requireThat(fs.realpathSync(binary) === path.resolve(binary) && fs.statSync(binary).isFile(), 'CLI fingerprint requires resolved regular binary');
  const digest = fingerprint(binary);
  requireThat(qualifiedBuilds.get(digest) === platform, `CLI fingerprint not qualified (${digest}); retain queue for an available qualified publisher or disposable qualification`);
  return digest;
}
const childEnvironment = (cwd, temporary) => {
  const env = cleanGitEnvironment();
  // Не наследуем endpoint/redirect/autopush и чужой Git index/context. HOME не меняется.
  for (const key of Object.keys(env)) if (/^(BEADS_|DOLT_|BD_|OTEL_)/.test(key)) delete env[key];
  return { ...env, BEADS_DIR: path.join(cwd, '.beads'), DOLT_ROOT_PATH: path.join(cwd, 'dolt-global'), DOLT_METRICS_DISABLED: '1', BD_DISABLE_METRICS: '1',
    TMPDIR: temporary, TMP: temporary, TEMP: temporary, GIT_CONFIG_GLOBAL: process.platform === 'win32' ? 'NUL' : '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_TERMINAL_PROMPT: '0' };
};

export function materializeFresh({ directory, binary, actor, snapshot, run = defaultRun, git = 'git', qualify = qualifyBinary }) {
  normalizeSnapshot(snapshot, 'frozen R');
  requireThat(/^agent-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(actor || ''), 'fresh actor invalid');
  const root = path.resolve(directory);
  requireThat(fs.realpathSync(root) === root && fs.lstatSync(root).isDirectory() && fs.readdirSync(root).length === 0, 'fresh root must be empty owned canonical directory');
  const executable = fs.realpathSync(binary);
  requireThat(fs.statSync(executable).isFile(), 'BD_BIN must be regular executable');
  const temporary = path.join(root, 'tmp'), cwd = path.join(temporary, 'store'), evidence = path.join(root, 'evidence');
  for (const dir of [temporary, cwd, evidence, path.join(cwd, '.beads'), path.join(cwd, 'dolt-global'), path.join(root, 'empty-hooks'), path.join(root, 'empty-template')]) fs.mkdirSync(dir, { mode: 0o700 });
  fs.writeFileSync(path.join(cwd, '.beads/config.yaml'), `issue-prefix: ${getProjectPrefix()}\n`, { flag: 'wx', mode: 0o600 });
  const env = childEnvironment(cwd, temporary);
  const invoke = (args, timeout = 30000) => run(executable, ['--db', path.join(cwd, '.beads/dolt'), '--actor', actor, ...args], { cwd, env, timeout });
  const version = run(executable, ['--version'], { cwd, env, timeout: 30000 });
  requireThat(/\b1\.2\.2(?:\s|\(|$)/.test(version), 'BD_BIN is not a qualified fresh-store CLI (qualified capability:1.2.2); preserve queue and use qualified publisher');
  const binarySha256 = qualify(executable);
  for (const [command, flags] of [['init', ['--prefix', '--non-interactive', '--skip-agents', '--skip-hooks']], ['export', ['--all', '--output']], ['import', ['--json']]]) {
    const help = invoke([command, '--help']);
    for (const flag of flags) requireThat(help.includes(flag), `qualified CLI lacks ${command} ${flag}`);
  }
  run(git, ['-c', 'init.defaultBranch=managed-projection', '-c', `core.hooksPath=${path.join(root, 'empty-hooks')}`, 'init', '--template=' + path.join(root, 'empty-template'), '-q', '.'], { cwd, env, timeout: 30000 });
  const context = () => {
    const info = JSON.parse(invoke(['--readonly', 'context', '--json']));
    requireThat(!info.error && info.beads_dir === path.join(cwd, '.beads') && info.repo_root === cwd && info.cwd_repo_root === cwd,
      'fresh context paths do not match owned root');
    requireThat(info.is_redirected === false && info.is_worktree === false && info.backend === 'dolt' && info.dolt_mode === 'embedded', 'fresh context must be standalone embedded');
    requireThat(!info.server_host && !info.server_port && !info.proxied_dir && !info.sync_remote && !info.sync_git_remote, 'fresh context has unexpected endpoint/remote');
    if (info.data_dir) {
      const data = path.resolve(info.beads_dir, info.data_dir);
      requireThat(data.startsWith(info.beads_dir + path.sep), 'fresh context data_dir outside owned beads root');
      let ancestor = data;
      while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
      const canonical = path.resolve(fs.realpathSync(ancestor), path.relative(ancestor, data));
      requireThat(canonical.startsWith(info.beads_dir + path.sep), 'fresh context data_dir symlink outside owned root');
    }
    return info;
  };
  context();
  run(executable, ['--actor', actor, 'init', '--prefix', getProjectPrefix(), '--non-interactive', '--skip-agents', '--skip-hooks'], { cwd, env, timeout: 180000 });
  context();
  const frozenFile = path.join(evidence, 'frozen.jsonl'); fs.writeFileSync(frozenFile, snapshot, { flag: 'wx', mode: 0o600 });
  invoke(['import', frozenFile, '--json']);
  let exportIndex = 0;
  const exportSnapshot = () => {
    const file = path.join(evidence, `export-${++exportIndex}.jsonl`);
    invoke(['export', '--all', '--output', file]);
    requireThat(fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink(), 'CLI export is not own regular file');
    const raw = fs.readFileSync(file, 'utf8'); normalizeSnapshot(raw, 'fresh export'); return raw;
  };
  const roundtrip = exportSnapshot(); assertExactSnapshot(snapshot, roundtrip);
  return { cwd, root, actor, version: version.trim(), binarySha256, invoke, exportSnapshot, rows: parseSnapshot(roundtrip).map(({ record }) => record) };
}

const updateFlags = { title: '--title', description: '--description', design: '--design', acceptance: '--acceptance', notes: '--notes',
  priority: '--priority', assignee: '--assignee', status: '--status', type: '--type', external_ref: '--external-ref', due_at: '--due', defer_until: '--defer', metadata: '--metadata', add_labels: '--add-label', remove_labels: '--remove-label' };
const snapshotNames = { type: 'issue_type', acceptance: 'acceptance_criteria' };
const markerText = intent => `${intent.text}\n\n[intent:${intent.intent_id}]`;
const issueRows = rows => new Map(rows.filter(row => row._type !== 'memory').map(row => [row.id, row]));
const edgeKey = edge => canonical([edge.issue_id, edge.depends_on_id, edge.type]);
const normalizedValue = (field, value) => ['labels', 'dependencies', 'comments'].includes(field) && Array.isArray(value)
  ? [...value].sort((a, b) => canonical(a).localeCompare(canonical(b))) : value;
const equalValue = (field, left, right) => {
  if (left === undefined || right === undefined) return left === right;
  if (['due_at', 'defer_until'].includes(field) && typeof left === 'string' && typeof right === 'string') return timestampIdentity(left) === timestampIdentity(right);
  return canonical(normalizedValue(field, left)) === canonical(normalizedValue(field, right));
};

function verifyBatch(beforeRows, afterRaw, intents, handles, actor) {
  normalizeSnapshot(afterRaw, 'postcondition snapshot');
  const afterRows = parseSnapshot(afterRaw).map(({ record }) => record), before = issueRows(beforeRows), after = issueRows(afterRows);
  const desired = new Map(), allowed = new Map(), commentAdds = new Map(), graphChanges = new Map();
  const resolve = ref => handles.get(ref) || ref;
  const allow = (id, ...names) => { if (!allowed.has(id)) allowed.set(id, new Set()); for (const name of names) allowed.get(id).add(name); };
  const expect = (id, name, value) => { if (!desired.has(id)) desired.set(id, new Map()); desired.get(id).set(name, value); allow(id, name, 'updated_at'); };
  const original = (id, name) => desired.get(id)?.has(name) ? desired.get(id).get(name) : before.get(id)?.[name];
  const changeGraph = (id, target, type, remove = false) => {
    if (!graphChanges.has(id)) graphChanges.set(id, new Map((before.get(id)?.dependencies || []).map(edge => [edgeKey(edge), edge])));
    const edges = graphChanges.get(id);
    if (remove) for (const [key, edge] of edges) { if (edge.depends_on_id === target) edges.delete(key); }
    else {
      const edge = { issue_id: id, depends_on_id: target, type }, key = edgeKey(edge);
      if (!edges.has(key)) edges.set(key, null);
    }
    allow(id, 'dependencies', 'dependency_count', 'updated_at'); allow(target, 'dependent_count');
  };
  for (const intent of intents) {
    const id = intent.op === 'create' ? handles.get(intent.handle) : resolve(intent.ref);
    requireThat(after.has(id), `postcondition missing ${id}`);
    if (intent.op === 'create') {
      requireThat(!before.has(id), `postcondition create reused existing ${id}`);
      expect(id, 'title', intent.title); expect(id, 'issue_type', intent.type || 'task'); expect(id, 'priority', intent.priority ?? 2);
      expect(id, 'status', Object.hasOwn(intent, 'defer_until') ? 'deferred' : 'open');
      expect(id, 'external_ref', intent.external_ref || `intent:${intent.intent_id}`);
      if (intent.parent) changeGraph(id, resolve(intent.parent), 'parent-child');
    }
    if (['create', 'update'].includes(intent.op)) {
      for (const [key] of Object.entries(updateFlags)) {
        if (!Object.hasOwn(intent, key)) continue;
        if (key === 'add_labels' || key === 'remove_labels') continue;
        expect(id, snapshotNames[key] || key, intent[key]);
      }
      let labels = original(id, 'labels') || [];
      if (intent.op === 'create' && intent.labels) { labels = intent.labels; expect(id, 'labels', labels); }
      if (intent.add_labels || intent.remove_labels) expect(id, 'labels', [...new Set([...labels.filter(label => !(intent.remove_labels || []).includes(label)), ...(intent.add_labels || [])])]);
      if (Object.hasOwn(intent, 'defer_until')) expect(id, 'status', 'deferred');
      if (Object.hasOwn(intent, 'status')) allow(id, 'started_at', 'closed_at', 'close_reason');
    } else if (intent.op === 'claim') {
      expect(id, 'status', 'in_progress'); expect(id, 'assignee', actor); allow(id, 'started_at');
    } else if (intent.op === 'close') {
      expect(id, 'status', 'closed'); expect(id, 'close_reason', intent.close_reason); allow(id, 'closed_at');
    } else if (intent.op === 'note') {
      const notes = original(id, 'notes') || '';
      expect(id, 'notes', (notes ? notes + '\n\n' : '') + markerText(intent));
    } else if (intent.op === 'comment') {
      if (!commentAdds.has(id)) commentAdds.set(id, []);
      commentAdds.get(id).push(markerText(intent)); allow(id, 'comments', 'comment_count', 'updated_at');
    } else if (intent.op === 'dep_add') changeGraph(id, resolve(intent.blocked_by), intent.dep_type || 'blocks');
    else if (intent.op === 'dep_remove') changeGraph(id, resolve(intent.blocked_by), null, true);
  }
  for (const [id, expected] of desired) for (const [name, value] of expected) requireThat(equalValue(name, after.get(id)[name], value), `postcondition ${id}.${name} differs`);
  for (const [id, texts] of commentAdds) {
    const previous = before.get(id)?.comments || [], current = after.get(id).comments || [];
    requireThat(previous.every(comment => current.some(candidate => canonical(candidate) === canonical(comment))), `postcondition ${id}: original comments changed`);
    const added = current.filter(comment => !previous.some(candidate => canonical(candidate) === canonical(comment)));
    requireThat(added.length === texts.length && texts.every(text => added.filter(comment => comment.text === text && comment.author === actor && comment.id && comment.created_at && comment.issue_id === id).length === 1), `postcondition ${id}: comments marker/identity differs`);
  }
  for (const [id, expected] of graphChanges) {
    const current = after.get(id).dependencies || [], actual = new Map(current.map(edge => [edgeKey(edge), edge]));
    requireThat(actual.size === current.length && actual.size === expected.size, `postcondition ${id}: graph size differs`);
    for (const [key, edge] of expected) requireThat(actual.has(key) && (!edge || canonical(edge) === canonical(actual.get(key))), `postcondition ${id}: typed edge changed`);
  }
  for (const [id, old] of before) {
    const current = after.get(id); requireThat(current, `postcondition snapshot dropped ${id}`);
    for (const name of new Set([...Object.keys(old), ...Object.keys(current)])) {
      if (name === '_type' || allowed.get(id)?.has(name)) continue;
      requireThat(Object.hasOwn(old, name) === Object.hasOwn(current, name) && (!Object.hasOwn(old, name) || equalValue(name, old[name], current[name])), `postcondition untouched ${id}.${name} changed`);
    }
  }
  const newIds = new Set(intents.filter(intent => intent.op === 'create').map(intent => handles.get(intent.handle)));
  for (const id of after.keys()) requireThat(before.has(id) || newIds.has(id), `postcondition unexpected issue ${id}`);
  const memories = rows => canonical(rows.filter(row => row._type === 'memory').sort((a, b) => canonical(a).localeCompare(canonical(b))));
  requireThat(memories(beforeRows) === memories(afterRows), 'postcondition snapshot memories changed');
  validateBlockingGraph(afterRows, []);
}

// Та же проверка postcondition действует на Git candidate и peer readback:
// marker/hash и append-only ledger сами по себе не доказывают сохранность задач.
export function assertAuthorizedSnapshotTransition(before, after, beforeLedger, afterLedger) {
  assertLedgerExtension(beforeLedger, afterLedger);
  normalizeSnapshot(before, 'previous snapshot');
  normalizeSnapshot(after, 'candidate snapshot');
  const additions = afterLedger.outcomes.slice(beforeLedger.outcomes.length);
  if (!additions.length) {
    requireThat(after === before, 'snapshot changed without authorized outcome');
    return;
  }
  const intents = validateQueue(additions.map(outcome => canonical(outcome.intent)).join('\n'));
  const beforeRows = parseSnapshot(before).map(({ record }) => record);
  const replay = planReplay(intents, beforeRows, beforeLedger);
  requireThat(!replay.conflicts.length && !replay.skipped.length && replay.pending.length === intents.length,
    `snapshot outcome precondition conflict against prior published state: ${canonical(replay.conflicts)}`);
  const handles = new Map(additions.filter(outcome => outcome.intent.op === 'create')
    .map(outcome => [outcome.intent.handle, outcome.result.ref]));
  for (const outcome of additions) {
    const expected = outcome.intent.op === 'create' ? handles.get(outcome.intent.handle)
      : handles.get(outcome.intent.ref) || outcome.intent.ref;
    requireThat(outcome.result.ref === expected, 'outcome result ref differs from authorized intent');
  }
  verifyBatch(beforeRows, after, intents, handles, intents[0].actor);
}

export function executeBatch(store, intents, ledger) {
  validateQueue(intents.map(canonical).join('\n'));
  const plan = planReplay(intents, store.rows, ledger);
  requireThat(!plan.conflicts.length, 'batch precondition conflict');
  const handles = replayHandles(intents, ledger);
  validateBlockingGraph(store.rows, plan.pending, handles);
  const resolve = ref => { const id = handles.get(ref) || ref; requireThat(isRealId(id), `unresolved real ref ${ref}`); return id; };
  const update = (id, intent) => {
    const args = ['update', id];
    for (const [key, flag] of Object.entries(updateFlags)) if (Object.hasOwn(intent, key)) args.push(flag,
      key === 'metadata' ? canonical(intent[key]) : Array.isArray(intent[key]) ? intent[key].join(',') : String(intent[key]));
    if (args.length > 2) store.invoke(args);
  };
  const results = [];
  for (const intent of plan.pending) {
    let id;
    if (intent.op === 'create') {
      const args = ['create', '--title', intent.title, '--type', intent.type || 'task', '--priority', String(intent.priority ?? 2), '--json'];
      if (intent.parent) args.push('--parent', resolve(intent.parent));
      args.push('--external-ref', intent.external_ref || `intent:${intent.intent_id}`);
      const response = JSON.parse(store.invoke(args)); id = Array.isArray(response) ? response[0]?.id : response.id;
      requireThat(isRealId(id), 'CLI create did not return real ID');
      handles.set(intent.handle, id);
      const { title, type, priority, external_ref, ...remaining } = intent;
      if (intent.labels) remaining.add_labels = intent.labels;
      update(id, remaining);
    } else {
      id = resolve(intent.ref);
      if (intent.op === 'update') update(id, intent);
      else if (intent.op === 'claim') store.invoke(['update', id, '--claim', '--json']);
      else if (intent.op === 'close') store.invoke(['close', id, '--reason', intent.close_reason, '--json']);
      else if (intent.op === 'note') {
        const response = JSON.parse(store.invoke(['--readonly', 'show', id, '--json'])), row = Array.isArray(response) ? response[0] : response;
        requireThat(row?.id === id, 'CLI note readback ID mismatch');
        update(id, { notes: (row.notes ? row.notes + '\n\n' : '') + markerText(intent) });
      } else if (intent.op === 'comment') store.invoke(['comments', 'add', id, markerText(intent), '--json']);
      else if (intent.op === 'dep_add') store.invoke(['dep', 'add', id, resolve(intent.blocked_by), '--type', intent.dep_type || 'blocks']);
      else if (intent.op === 'dep_remove') store.invoke(['dep', 'remove', id, resolve(intent.blocked_by)]);
    }
    results.push({ intent, result: intent.op === 'create' ? { ref: id, handles: { [intent.handle]: id } } : { ref: id } });
  }
  const snapshot = store.exportSnapshot(); verifyBatch(store.rows, snapshot, plan.pending, handles, store.actor);
  let nextLedger = ledger;
  for (const { intent, result } of results) nextLedger = appendOutcome(nextLedger, intent, result);
  return { snapshot, ledger: nextLedger, handles: Object.fromEntries(handles), mutations: results.length };
}
