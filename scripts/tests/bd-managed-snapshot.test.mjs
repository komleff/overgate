import assert from 'node:assert/strict';
import { configureProjectPrefix } from '../lib/bd-managed-contract.mjs';
import { assertExactSnapshot, normalizeSnapshot } from '../lib/bd-snapshot.mjs';

configureProjectPrefix('big-heroes');
const issue = { _type: 'issue', id: 'big-heroes-A', title: 'Keep every field', status: 'open', priority: 2,
  issue_type: 'task', labels: ['z', 'a'], metadata: { source: 'fixture' },
  comments: [{ id: 'c1', issue_id: 'big-heroes-A', author: 'agent-a', text: 'evidence', created_at: '2026-11-04T00:00:00Z' }],
  comment_count: 1, dependencies: [{ issue_id: 'big-heroes-A', depends_on_id: 'big-heroes-B', type: 'blocks' }],
  dependency_count: 1 };
const memory = { _type: 'memory', key: 'fixture', value: 'retained' };
const expected = [issue, memory].map(JSON.stringify).join('\n') + '\n';
const reordered = [memory, { ...issue, labels: ['a', 'z'] }].map(JSON.stringify).join('\n') + '\n';
assert.equal(normalizeSnapshot(expected), normalizeSnapshot(reordered));
assertExactSnapshot(expected, reordered);
assert.throws(() => assertExactSnapshot(expected, JSON.stringify({ ...issue, comments: [], comment_count: 0 }) + '\n' + JSON.stringify(memory) + '\n'),
  /full-content roundtrip mismatch/);
assert.throws(() => assertExactSnapshot(expected, JSON.stringify({ ...issue, dependencies: [], dependency_count: 0 }) + '\n' + JSON.stringify(memory) + '\n'),
  /full-content roundtrip mismatch/);
assert.throws(() => normalizeSnapshot(JSON.stringify({ ...issue, future_field: 'unqualified' }) + '\n'), /unsupported field/);
assert.equal(normalizeSnapshot(''), '[]');
for (const malformed of ['\n', ' \n\t\n', expected + '\n']) {
  assert.throws(() => normalizeSnapshot(malformed), /empty|blank|строка/);
  assert.throws(() => assertExactSnapshot(malformed, ''), /empty|blank|строка/);
}
