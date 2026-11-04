// Чистый переносимый контракт: CLI и файловая система здесь не вызываются.
import { createHash } from 'node:crypto';

let projectPrefix = null;
export function configureProjectPrefix(prefix) {
  requireThat(typeof prefix === 'string' && /^[A-Za-z][A-Za-z0-9-]*$/.test(prefix), 'verified project prefix invalid');
  if (projectPrefix && projectPrefix !== prefix) throw new Error('project prefix changed in active publisher');
  projectPrefix = prefix;
}
export const getProjectPrefix = () => { requireThat(projectPrefix, 'verified project prefix required'); return projectPrefix; };
export const isRealId = value => typeof value === 'string' && value.startsWith(getProjectPrefix() + '-')
  && /^[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*$/.test(value.slice(getProjectPrefix().length + 1));
const realId = { test: isRealId };
const temporaryId = /^tmp:[A-Za-z0-9._-]{1,64}$/;
const operationId = /^[A-Za-z0-9._:-]{1,64}$/;
const actorId = /^agent-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const fields = {
  create: ['handle', 'title', 'type', 'priority', 'description', 'assignee', 'acceptance', 'labels', 'notes', 'parent', 'external_ref', 'due_at', 'defer_until', 'metadata'],
  update: ['ref', 'title', 'status', 'priority', 'assignee', 'type', 'description', 'design', 'acceptance', 'notes', 'add_labels', 'remove_labels', 'external_ref', 'due_at', 'defer_until', 'metadata'],
  claim: ['ref'], close: ['ref', 'close_reason'], dep_add: ['ref', 'blocked_by', 'dep_type'], dep_remove: ['ref', 'blocked_by'],
  note: ['ref', 'text'], comment: ['ref', 'text'],
};
const common = ['version', 'intent_id', 'actor', 'base', 'op', 'expected', 'payload_hash'];
const strings = ['title', 'description', 'design', 'assignee', 'acceptance', 'notes', 'external_ref', 'close_reason', 'text'];
const aliases = { type: 'issue_type', acceptance: 'acceptance_criteria', add_labels: 'labels', remove_labels: 'labels' };
const dependencyTypes = new Set(['blocks', 'related', 'parent-child', 'discovered-from', 'relates-to']);
// Сохранённые canonical edges шире разрешённых typed authoring operations.
const snapshotDependencyTypes = new Set([...dependencyTypes, 'supersedes']);
const fieldNames = new Set(['title', 'status', 'priority', 'assignee', 'issue_type', 'description', 'design', 'acceptance_criteria', 'notes',
  'external_ref', 'due_at', 'defer_until', 'metadata', 'labels', 'dependencies', 'comments']);
const keysOnly = (value, allowed, label) => {
  requireThat(object(value), `${label}: expected object`);
  for (const key of Object.keys(value)) requireThat(allowed.includes(key), `${label}: unsupported ${key}`);
};

export function canonical(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') { requireThat(Number.isFinite(value), 'non-finite JSON number'); return JSON.stringify(value); }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  requireThat(object(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)), 'unsupported JSON value');
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
}
export const payloadHash = intent => createHash('sha256').update(canonical(Object.fromEntries(Object.entries(intent).filter(([key]) => key !== 'payload_hash')))).digest('hex');
export function timestampIdentity(value) {
  const match = typeof value === 'string' && /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.(\d{1,9}))?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  requireThat(match && Number.isFinite(Date.parse(value)), 'timestamp must be absolute RFC3339');
  const date = new Date(0); date.setUTCFullYear(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  requireThat(date.getUTCFullYear() === Number(match[1]) && date.getUTCMonth() + 1 === Number(match[2]) && date.getUTCDate() === Number(match[3]), 'timestamp calendar date invalid');
  // Date.parse теряет sub-ms precision; fractional identity сохраняет все9digits.
  return String(Date.parse(value)) + ':' + (match[5] || '').padEnd(9, '0');
}
export const emptyLedger = () => ({ version: 1, outcomes: [] });
const issueMap = rows => new Map(rows.filter(row => row._type !== 'memory').map(row => [row.id, row]));
const refs = intent => ['ref', 'blocked_by', 'parent'].filter(key => intent[key] !== undefined).map(key => intent[key]);
const revisions = ledger => {
  const result = new Map();
  for (const outcome of ledger.outcomes) for (const [id, revision] of Object.entries(outcome.revisions)) result.set(id, revision);
  return result;
};
const touchedFields = intent => {
  if (intent.op === 'update') return [...new Set([...fields.update.filter(key => key !== 'ref' && intent[key] !== undefined).map(key => aliases[key] || key),
    ...(Object.hasOwn(intent, 'defer_until') ? ['status'] : [])])];
  if (intent.op === 'claim' || intent.op === 'close') return ['status', 'assignee'];
  if (intent.op === 'dep_add' || intent.op === 'dep_remove') return ['dependencies'];
  if (intent.op === 'note') return ['notes'];
  if (intent.op === 'comment') return ['comments'];
  return [];
};
// Только известные множества сравниваются без порядка. Metadata arrays остаются значимыми.
const fieldValue = (name, value) => ['labels', 'dependencies', 'comments'].includes(name) && Array.isArray(value)
  ? value.map(item => JSON.parse(canonical(item))).sort((a, b) => canonical(a).localeCompare(canonical(b))) : value;
const observedField = (issue, name) => Object.hasOwn(issue, name) ? { present: true, value: fieldValue(name, issue[name]) } : { present: false };
const changesLifecycle = intent => ['create', 'claim', 'close'].includes(intent.op)
  || (intent.op === 'update' && ['status', 'assignee', 'defer_until'].some(key => Object.hasOwn(intent, key)));

export function capturePreconditions(intent, rows, ledger) {
  const issues = issueMap(rows), revision = revisions(ledger), expected = {};
  for (const id of new Set(refs(intent).filter(ref => realId.test(ref)))) {
    requireThat(issues.has(id), `precondition: missing ${id}`);
    const names = id === intent.ref ? touchedFields(intent) : [];
    expected[id] = { exists: true, lifecycle: revision.get(id) || 0, fields: Object.fromEntries(names.map(name => [name, observedField(issues.get(id), name)])) };
  }
  return expected;
}

function validateIntent(intent) {
  requireThat(object(intent), 'intent: expected object');
  requireThat(intent.version === 2, 'intent: unsupported version (legacy input requires explicit adoption)');
  requireThat(operationId.test(intent.intent_id || ''), 'intent_id invalid');
  requireThat(actorId.test(intent.actor || ''), 'actor must be unique logical agent-UUID');
  requireThat(/^[0-9a-f]{40}$/.test(intent.base || ''), 'base must be frozen Git SHA');
  requireThat(Object.hasOwn(fields, intent.op), `unsupported op ${intent.op}`);
  keysOnly(intent, [...common, ...fields[intent.op]], 'intent');
  for (const key of strings) if (Object.hasOwn(intent, key)) {
    requireThat(typeof intent[key] === 'string' && intent[key].length <= 8000, `${key}: expected bounded string`);
    requireThat(!/[\x00-\x08\x0b-\x1f\x7f]/.test(intent[key]), `${key}: forbidden control character`);
  }
  for (const key of ['due_at', 'defer_until']) if (Object.hasOwn(intent, key)) timestampIdentity(intent[key]);
  for (const key of ['labels', 'add_labels', 'remove_labels']) if (Object.hasOwn(intent, key)) requireThat(Array.isArray(intent[key]) && intent[key].every(label => typeof label === 'string' && label.length > 0 && label.length <= 128 && !/[\x00-\x1f\x7f,]/.test(label)) && new Set(intent[key]).size === intent[key].length, `${key}: expected distinct labels`);
  if (Object.hasOwn(intent, 'priority')) requireThat(Number.isInteger(intent.priority) && intent.priority >= 0 && intent.priority <= 4, 'priority invalid');
  if (Object.hasOwn(intent, 'status')) requireThat(['open', 'in_progress', 'blocked', 'deferred', 'closed'].includes(intent.status), 'status invalid');
  if (Object.hasOwn(intent, 'type')) requireThat(['task', 'bug', 'feature', 'chore', 'epic', 'decision'].includes(intent.type), 'type invalid');
  if (Object.hasOwn(intent, 'metadata')) requireThat(object(intent.metadata), 'metadata must be object');
  if (Object.hasOwn(intent, 'dep_type')) requireThat(dependencyTypes.has(intent.dep_type), 'dep_type invalid');
  if (intent.op === 'create') requireThat(temporaryId.test(intent.handle || '') && typeof intent.title === 'string' && intent.title.trim(), 'create needs handle/title');
  else requireThat(realId.test(intent.ref || '') || temporaryId.test(intent.ref || ''), 'ref invalid');
  if (intent.op === 'update') requireThat(touchedFields(intent).length, 'update requires fields');
  if (intent.op === 'close') requireThat(typeof intent.close_reason === 'string' && intent.close_reason.trim().length > 0, 'close_reason required');
  if (['dep_add', 'dep_remove'].includes(intent.op)) requireThat(typeof intent.blocked_by === 'string', 'blocked_by required');
  if (['note', 'comment'].includes(intent.op)) requireThat(typeof intent.text === 'string' && intent.text.trim(), 'text required');
  for (const ref of refs(intent)) requireThat(realId.test(ref) || temporaryId.test(ref), 'ref invalid');
  requireThat(object(intent.expected), 'preconditions required');
  for (const [id, expected] of Object.entries(intent.expected)) {
    requireThat(realId.test(id) && refs(intent).includes(id), `precondition unexpected ref ${id}`);
    keysOnly(expected, ['exists', 'lifecycle', 'fields'], 'precondition');
    requireThat(expected.exists === true && Number.isSafeInteger(expected.lifecycle) && expected.lifecycle >= 0 && object(expected.fields), 'precondition invalid');
    for (const [name, field] of Object.entries(expected.fields)) {
      requireThat(fieldNames.has(name), `precondition unsupported field ${name}`);
      keysOnly(field, ['present', 'value'], 'precondition field');
      requireThat(typeof field.present === 'boolean' && Object.hasOwn(field, 'value') === field.present, 'precondition presence invalid');
    }
  }
  for (const id of refs(intent).filter(ref => realId.test(ref))) {
    requireThat(Object.hasOwn(intent.expected, id), `precondition missing ${id}`);
    if (id === intent.ref) for (const name of touchedFields(intent)) requireThat(Object.hasOwn(intent.expected[id].fields, name), `precondition missing ${id}.${name}`);
  }
  canonical(intent);
  requireThat(intent.payload_hash === payloadHash(intent), 'intent payload hash mismatch');
  return intent;
}

export function prepareQueue(raw, rows, ledger, { base, actor }) {
  parseLedger(canonical(ledger));
  const prepared = raw.split('\n').filter(line => line.trim()).map((line, index) => {
    let input;
    try { input = JSON.parse(line); } catch { throw new Error(`prepare line ${index + 1}: invalid JSON`); }
    requireThat(object(input), 'prepare: expected object');
    for (const key of ['version', 'actor', 'base', 'expected', 'payload_hash']) requireThat(!Object.hasOwn(input, key), `prepare: derived ${key} must not be supplied`);
    const intent = { version: 2, ...input, base, actor };
    intent.expected = capturePreconditions(intent, rows, ledger);
    intent.payload_hash = payloadHash(intent);
    return intent;
  });
  // Полученные однажды preconditions сохраняются в queue; replay не вызывает prepare.
  return validateQueue(prepared.map(canonical).join('\n'));
}

export function validateQueue(raw) {
  const intents = raw.split('\n').filter(line => line.trim()).map((line, index) => {
    try { return validateIntent(JSON.parse(line)); } catch (error) { throw new Error(`queue line ${index + 1}: ${error.message}`); }
  });
  const ids = new Set(), handles = new Set();
  for (const intent of intents) {
    requireThat(intent.base === intents[0].base && intent.actor === intents[0].actor, 'queue base/actor mismatch');
    requireThat(!ids.has(intent.intent_id), 'duplicate intent_id'); ids.add(intent.intent_id);
    for (const ref of refs(intent).filter(ref => temporaryId.test(ref))) requireThat(handles.has(ref), `unbound ref ${ref}`);
    if (intent.op === 'create') { requireThat(!handles.has(intent.handle), 'duplicate handle'); handles.add(intent.handle); }
  }
  return intents;
}

export function parseLedger(raw) {
  try {
    const ledger = JSON.parse(raw);
    keysOnly(ledger, ['version', 'outcomes'], 'ledger');
    requireThat(ledger.version === 1 && Array.isArray(ledger.outcomes), 'ledger version/outcomes invalid');
    const ids = new Set(), revision = new Map();
    for (const outcome of ledger.outcomes) {
      keysOnly(outcome, ['intent', 'payload_hash', 'result', 'revisions'], 'ledger outcome');
      validateIntent(outcome.intent);
      requireThat(!ids.has(outcome.intent.intent_id), 'duplicate ledger operation'); ids.add(outcome.intent.intent_id);
      requireThat(outcome.payload_hash === payloadHash(outcome.intent), 'ledger payload hash mismatch');
      keysOnly(outcome.result, ['ref', 'handles'], 'ledger result');
      requireThat(realId.test(outcome.result.ref || '') && (!realId.test(outcome.intent.ref || '') || outcome.intent.ref === outcome.result.ref), 'ledger result ref invalid');
      if (outcome.intent.op === 'create') {
        requireThat(object(outcome.result.handles) && canonical(outcome.result.handles) === canonical({ [outcome.intent.handle]: outcome.result.ref }), 'ledger result handles invalid');
      } else requireThat(!Object.hasOwn(outcome.result, 'handles'), 'ledger result unexpected handles');
      requireThat(object(outcome.revisions), 'ledger revisions invalid');
      const lifecycleIds = changesLifecycle(outcome.intent) ? [outcome.result.ref] : [];
      requireThat(canonical(Object.keys(outcome.revisions)) === canonical(lifecycleIds), 'ledger lifecycle missing/unexpected revision');
      for (const [id, value] of Object.entries(outcome.revisions)) {
        requireThat(realId.test(id) && Number.isSafeInteger(value) && value === (revision.get(id) || 0) + 1, 'ledger lifecycle discontinuity');
        revision.set(id, value);
      }
    }
    canonical(ledger);
    return ledger;
  } catch (error) { throw new Error(`ledger: ${error.message}`); }
}

export function appendOutcome(ledger, intent, result) {
  parseLedger(canonical(ledger)); validateIntent(intent);
  requireThat(!ledger.outcomes.some(outcome => outcome.intent.intent_id === intent.intent_id), 'duplicate ledger operation');
  const revision = revisions(ledger);
  const lifecycleIds = changesLifecycle(intent) ? [result.ref] : [];
  const outcome = { intent, payload_hash: payloadHash(intent), result,
    revisions: Object.fromEntries(lifecycleIds.map(id => [id, (revision.get(id) || 0) + 1])) };
  return parseLedger(canonical({ version: 1, outcomes: [...ledger.outcomes, outcome] }));
}

export function assertLedgerExtension(before, after) {
  parseLedger(canonical(before)); parseLedger(canonical(after));
  requireThat(after.outcomes.length >= before.outcomes.length && before.outcomes.every((outcome, index) => canonical(outcome) === canonical(after.outcomes[index])), 'ledger loss/downgrade or immutable outcome changed');
}

// tmp namespace — только эта queue; historical creates с тем же handle не относятся к ней.
export function replayHandles(intents, ledger) {
  parseLedger(canonical(ledger));
  const creates = new Map(intents.filter(intent => intent.op === 'create').map(intent => [intent.intent_id, intent]));
  const handles = new Map();
  for (const outcome of ledger.outcomes) {
    const intent = creates.get(outcome.intent.intent_id);
    if (!intent) continue;
    requireThat(outcome.payload_hash === payloadHash(intent), `payload collision ${intent.intent_id}`);
    handles.set(intent.handle, outcome.result.ref);
  }
  return handles;
}

export function planReplay(intents, rows, ledger) {
  parseLedger(canonical(ledger));
  const outcomes = new Map(ledger.outcomes.map(outcome => [outcome.intent.intent_id, outcome]));
  const issues = issueMap(rows), revision = revisions(ledger), pending = [], skipped = [], conflicts = [];
  for (const intent of intents) {
    validateIntent(intent);
    const outcome = outcomes.get(intent.intent_id);
    // Опубликованная операция не повторяется даже после reopen/reassign и утраты local receipt.
    if (outcome) {
      requireThat(outcome.payload_hash === payloadHash(intent), `payload collision ${intent.intent_id}`);
      skipped.push(outcome); continue;
    }
    const start = conflicts.length;
    const conflict = (id, field, expected, actual) => conflicts.push({ intent_id: intent.intent_id, ref: id, field, expected, actual });
    if (intent.op === 'claim' && issues.has(intent.ref)) {
      const issue = issues.get(intent.ref);
      if (issue.assignee && issue.assignee !== intent.actor) conflict(intent.ref, 'assignee', { unassigned_or: intent.actor }, issue.assignee);
      if (!['open', 'in_progress'].includes(issue.status)) conflict(intent.ref, 'status', ['open', 'in_progress'], issue.status ?? null);
    }
    for (const [id, expected] of Object.entries(intent.expected)) {
      const issue = issues.get(id);
      if (!issue) { conflict(id, '$exists', true, false); continue; }
      if ((revision.get(id) || 0) !== expected.lifecycle) conflict(id, '$lifecycle', expected.lifecycle, revision.get(id) || 0);
      for (const [name, field] of Object.entries(expected.fields)) {
        const actual = observedField(issue, name);
        if (canonical(actual) !== canonical(field)) conflict(id, name, field, actual);
      }
    }
    if (conflicts.length === start) pending.push(intent);
  }
  return { pending, skipped, conflicts };
}

export function validateBlockingGraph(rows, intents, handles = new Map()) {
  const issues = issueMap(rows), graph = new Map([...issues.keys()].map(id => [id, new Set()]));
  for (const issue of issues.values()) {
    requireThat(issue.dependencies === undefined ? !issue.dependency_count : Array.isArray(issue.dependencies), 'graph dependencies unavailable');
    for (const edge of issue.dependencies || []) {
      requireThat(object(edge) && snapshotDependencyTypes.has(edge.type), 'graph unsupported edge type');
      requireThat(edge.issue_id === issue.id && graph.has(edge.depends_on_id), `graph missing/invalid ref ${edge.depends_on_id}`);
      if (edge.type === 'blocks') graph.get(issue.id).add(edge.depends_on_id);
    }
  }
  // Проверяется итог batch целиком; удаления могут легально устранить старый путь.
  for (const intent of intents) {
    validateIntent(intent);
    if (intent.op === 'create') { requireThat(!graph.has(intent.handle), 'duplicate graph handle'); graph.set(intent.handle, new Set()); }
    if (!['dep_add', 'dep_remove'].includes(intent.op)) continue;
    const ref = handles.get(intent.ref) || intent.ref, target = handles.get(intent.blocked_by) || intent.blocked_by;
    requireThat(graph.has(ref) && graph.has(target), 'graph missing ref');
    if (intent.op === 'dep_remove') graph.get(ref).delete(target);
    else if ((intent.dep_type || 'blocks') === 'blocks') graph.get(ref).add(target);
  }
  const active = new Set(), done = new Set();
  const visit = id => {
    requireThat(!active.has(id), `blocking cycle at ${id}`);
    if (done.has(id)) return;
    active.add(id);
    for (const target of graph.get(id)) { requireThat(target !== id, `blocking self edge ${id}`); visit(target); }
    active.delete(id); done.add(id);
  };
  for (const id of graph.keys()) visit(id);
}
