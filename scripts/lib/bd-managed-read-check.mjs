#!/usr/bin/env node
// Reader проверяет опубликованный managed marker и hashes до показа task state.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { canonical, configureProjectPrefix, parseLedger } from './bd-managed-contract.mjs';
import { normalizeSnapshot } from './bd-snapshot.mjs';
import { assertAuthorizedSnapshotTransition } from './bd-managed-cli.mjs';
import { cleanGitEnvironment } from './bd-git-environment.mjs';

const [ref, snapshotFile] = process.argv.slice(2);
const git = args => execFileSync('git', args, { encoding: 'utf8', timeout: 30000, maxBuffer: 32 * 1024 * 1024,
  env: cleanGitEnvironment(), stdio: ['ignore', 'pipe', 'pipe'] });
const optional = (oid, name) => git(['ls-tree', '-r', '--name-only', oid, '--', name]).trim() === name
  ? git(['show', `${oid}:${name}`]) : null;
const sha = value => createHash('sha256').update(value).digest('hex');
try {
  if (!ref || !snapshotFile) throw new Error('managed reader requires ref and snapshot');
  if (git(['rev-parse', '--is-shallow-repository']).trim() === 'true')
    throw new Error('partial history cannot establish managed protocol continuity');
  const snapshot = fs.readFileSync(snapshotFile, 'utf8');
  const protocol = optional(ref, '.beads/overgate-managed-v1.json');
  const ledger = optional(ref, '.beads/overgate-outcomes-v1.json');
  if ((protocol === null) !== (ledger === null)) throw new Error('managed protocol/ledger incomplete');
  if (protocol === null) {
    const prior = git(['log', '-1', '--format=%H', ref, '--', '.beads/overgate-managed-v1.json']).trim();
    if (prior) throw new Error('managed protocol downgrade in published history');
    process.exit(0);
  }
  const marker = JSON.parse(protocol);
  if (canonical(Object.keys(marker).sort()) !== canonical(['ledger_sha256', 'prefix', 'snapshot_sha256', 'version'])
    || marker.version !== 1 || typeof marker.prefix !== 'string') throw new Error('managed protocol shape invalid');
  configureProjectPrefix(marker.prefix);
  normalizeSnapshot(snapshot, 'published managed snapshot');
  parseLedger(ledger);
  if (marker.snapshot_sha256 !== sha(snapshot) || marker.ledger_sha256 !== sha(ledger))
    throw new Error('managed protocol hash mismatch');
  const allCommits = git(['rev-list', '--reverse', '--topo-order', ref]).trim().split('\n');
  const additions = new Set(git(['log', '--reverse', '--topo-order', '--diff-filter=A', '--format=%H', ref,
    '--', '.beads/overgate-managed-v1.json']).trim().split('\n').filter(Boolean));
  const start = allCommits.findIndex(oid => additions.has(oid));
  if (start < 0) throw new Error('managed activation marker missing in retained history');
  const prior = start > 0 ? allCommits[start - 1] : null;
  const priorSnapshot = prior ? optional(prior, '.beads/issues.jsonl') : '';
  if (priorSnapshot === null) throw new Error('pre-activation legacy snapshot missing');
  normalizeSnapshot(priorSnapshot, 'pre-activation legacy snapshot');
  if (prior && (optional(prior, '.beads/overgate-managed-v1.json') !== null
    || optional(prior, '.beads/overgate-outcomes-v1.json') !== null))
    throw new Error('pre-activation managed marker/ledger unexpected');
  const commits = allCommits.slice(start);
  let previous = { snapshot: priorSnapshot, ledger: { version: 1, outcomes: [] } };
  for (const [index, oid] of commits.entries()) {
    const parents = git(['rev-list', '--parents', '-n', '1', oid]).trim().split(' ').slice(1);
    const expectedParent = index === 0 ? prior : commits[index - 1];
    if (parents.length !== (expectedParent ? 1 : 0) || (expectedParent && parents[0] !== expectedParent))
      throw new Error('managed history is not a single retained chain');
    const row = optional(oid, '.beads/issues.jsonl');
    if (row === null) throw new Error('published snapshot missing in retained history');
    normalizeSnapshot(row, 'retained snapshot');
    const protocolAt = optional(oid, '.beads/overgate-managed-v1.json');
    const ledgerAt = optional(oid, '.beads/overgate-outcomes-v1.json');
    if ((protocolAt === null) !== (ledgerAt === null)) throw new Error('managed protocol/ledger incomplete in retained history');
    if (protocolAt === null) throw new Error('managed protocol downgrade in retained history');
    const checked = JSON.parse(protocolAt), parsed = parseLedger(ledgerAt);
    if (canonical(Object.keys(checked).sort()) !== canonical(['ledger_sha256', 'prefix', 'snapshot_sha256', 'version'])
      || checked.version !== 1 || checked.prefix !== marker.prefix
      || checked.snapshot_sha256 !== sha(row) || checked.ledger_sha256 !== sha(ledgerAt))
      throw new Error('managed protocol hash/prefix mismatch in retained history');
    assertAuthorizedSnapshotTransition(previous.snapshot, row, previous.ledger, parsed);
    previous = { snapshot: row, ledger: parsed };
  }
  if (previous.snapshot !== snapshot) throw new Error('published snapshot changed during retained history proof');
} catch (error) {
  console.error(`ERROR: ${error.message} (fail-closed)`);
  process.exit(2);
}
