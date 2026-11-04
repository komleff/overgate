// Один строгий разбор для readers и publisher: повреждение нельзя принять за пустой снимок.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { canonical, isRealId } from './bd-managed-contract.mjs';

export function parseSnapshot(raw, label = 'snapshot') {
  const records = [], identities = new Set();
  const nonempty = (value) => typeof value === 'string' && value.trim().length > 0;
  if (raw === '') return records;
  const lines = raw.split(/\n/);
  lines.forEach((line, i) => {
    if (i === lines.length - 1 && line === '' && raw.endsWith('\n')) return;
    const invalid = (reason) => { throw new Error(`${label}: строка ${i + 1} — ${reason} (fail-closed)`); };
    if (!line.trim()) invalid('пустая строка в непустом snapshot');
    let record;
    try { record = JSON.parse(line); } catch { invalid('невалидный JSON'); }
    if (!record || typeof record !== 'object' || Array.isArray(record)) invalid('ожидалась запись-объект');
    let identity;
    if (record._type === 'memory') {
      // Canonical bd использует key/value; прежние fixtures — id/content.
      if ('key' in record && !nonempty(record.key)) invalid('невалидный memory key');
      if ('id' in record && !nonempty(record.id)) invalid('невалидный memory id');
      if ('key' in record && 'id' in record && record.key !== record.id) invalid('неоднозначные memory key/id');
      if (!nonempty(record.key ?? record.id)) invalid('у memory нет key/id');
      identity = `memory:${record.key ?? record.id}`;
    } else {
      if ('_type' in record && record._type !== 'issue') invalid(`неподдерживаемый тип записи ${JSON.stringify(record._type)}`);
      if (!nonempty(record.id)) invalid('у задачи нет строкового id');
      if (!isRealId(record.id)) invalid('id не соответствует verified project prefix');
      identity = `issue:${record.id}`;
    }
    if (identities.has(identity)) invalid(`повторный идентификатор ${identity}`);
    identities.add(identity);
    records.push({ identity, record });
  });
  return records;
}

export const readSnapshot = (path, label = path) => parseSnapshot(readFileSync(path, 'utf8'), label);

const issueFields = new Set(['_type', 'id', 'title', 'description', 'design', 'acceptance_criteria', 'notes', 'status', 'priority', 'issue_type',
  'assignee', 'owner', 'created_at', 'created_by', 'updated_at', 'started_at', 'closed_at', 'close_reason', 'due_at', 'defer_until',
  'external_ref', 'estimated_minutes', 'await_id', 'spec_id', 'metadata', 'labels', 'dependencies', 'comments', 'dependency_count', 'dependent_count', 'comment_count']);
const commentFields = new Set(['id', 'issue_id', 'author', 'text', 'created_at']);
const dependencyFields = new Set(['issue_id', 'depends_on_id', 'type', 'created_at', 'created_by', 'metadata']);
const knownKeys = (value, keys, label) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}: expected object`);
  for (const key of Object.keys(value)) if (!keys.has(key)) throw new Error(`${label}: unsupported field ${key}`);
};

export function normalizeSnapshot(raw, label = 'snapshot') {
  const normalized = parseSnapshot(raw, label).map(({ identity, record }) => {
    const row = JSON.parse(canonical(record));
    if (row._type === 'memory') {
      knownKeys(row, new Set(['_type', 'key', 'value', 'id', 'content']), `${label} ${identity}`);
      if (typeof (row.value ?? row.content) !== 'string') throw new Error(`${label} ${identity}: unsupported memory value`);
    } else {
      knownKeys(row, issueFields, `${label} ${identity}`);
      // Подтверждённые untyped/typed issue отличаются только известным discriminator.
      row._type = 'issue';
      for (const name of ['labels', 'comments', 'dependencies']) {
        if (row[name] === undefined) continue;
        if (!Array.isArray(row[name])) throw new Error(`${label} ${identity}: ${name} must be array`);
        if (name === 'comments') for (const item of row[name]) knownKeys(item, commentFields, `${label} ${identity} comments`);
        if (name === 'dependencies') for (const item of row[name]) knownKeys(item, dependencyFields, `${label} ${identity} dependencies`);
        row[name].sort((a, b) => canonical(a).localeCompare(canonical(b)));
      }
      // Count без bodies/relations не является полным переносимым snapshot.
      if (row.comment_count > 0 && !row.comments) throw new Error(`${label} ${identity}: comments unavailable`);
      if (row.dependency_count > 0 && !row.dependencies) throw new Error(`${label} ${identity}: dependencies unavailable`);
      if (row.comment_count !== undefined && row.comments && row.comment_count !== row.comments.length) throw new Error(`${label} ${identity}: comments count mismatch`);
    }
    return { identity, row };
  }).sort((a, b) => a.identity.localeCompare(b.identity));
  return canonical(normalized);
}

export function assertExactSnapshot(expected, actual) {
  const left = normalizeSnapshot(expected, 'expected snapshot'), right = normalizeSnapshot(actual, 'actual snapshot');
  if (left !== right) {
    const before = new Map(JSON.parse(left).map(({ identity, row }) => [identity, canonical(row)]));
    const after = new Map(JSON.parse(right).map(({ identity, row }) => [identity, canonical(row)]));
    const changed = [...new Set([...before.keys(), ...after.keys()])].filter(id => before.get(id) !== after.get(id));
    throw new Error(`snapshot full-content roundtrip mismatch: ${changed.slice(0, 5).join(', ')} (${changed.length} records)`);
  }
}

// Проверка целостности выполняется и при разрешённом shrink; CLI не меняет файлы.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const local = readSnapshot(process.argv[2]);
    const remote = process.argv[3] ? readSnapshot(process.argv[3]) : [];
    const identities = new Set(local.map(({ identity }) => identity));
    process.stdout.write(String(remote.filter(({ identity }) => !identities.has(identity)).length));
  } catch (error) {
    console.error(`ERROR: ${error.message}`);
    process.exit(2);
  }
}
