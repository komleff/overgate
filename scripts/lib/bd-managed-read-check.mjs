#!/usr/bin/env node
// Reader проверяет опубликованный managed marker и hashes до показа task state.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { canonical, configureProjectPrefix, parseLedger } from './bd-managed-contract.mjs';
import { normalizeSnapshot } from './bd-snapshot.mjs';

const [ref, snapshotFile] = process.argv.slice(2);
const git = args => execFileSync('git', args, { encoding: 'utf8', timeout: 30000, maxBuffer: 32 * 1024 * 1024,
  stdio: ['ignore', 'pipe', 'pipe'] });
const optional = name => git(['ls-tree', '-r', '--name-only', ref, '--', name]).trim() === name
  ? git(['show', `${ref}:${name}`]) : null;
const sha = value => createHash('sha256').update(value).digest('hex');
try {
  if (!ref || !snapshotFile) throw new Error('managed reader requires ref and snapshot');
  if (git(['rev-parse', '--is-shallow-repository']).trim() === 'true')
    throw new Error('partial history cannot establish managed protocol continuity');
  const snapshot = fs.readFileSync(snapshotFile, 'utf8');
  const protocol = optional('.beads/overgate-managed-v1.json');
  const ledger = optional('.beads/overgate-outcomes-v1.json');
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
} catch (error) {
  console.error(`ERROR: ${error.message} (fail-closed)`);
  process.exit(2);
}
