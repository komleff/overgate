// Git transport: frozen objects, retained ledger history, temp index и non-force CAS.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { canonical, emptyLedger, parseLedger, assertLedgerExtension } from './bd-managed-contract.mjs';
import { normalizeSnapshot } from './bd-snapshot.mjs';
import { validateManagedHistory } from './bd-managed-journal.mjs';
import { loadProjectPrefix } from './bd-managed-project.mjs';

export const ZERO = '0'.repeat(40);
const branch = 'beads-backup';
const snapshotPath = '.beads/issues.jsonl', ledgerPath = '.beads/overgate-outcomes-v1.json', protocolPath = '.beads/overgate-managed-v1.json';
const seenRef = 'refs/overgate-bd-managed/last-seen';
const digest = raw => createHash('sha256').update(raw).digest('hex');
const validSha = value => typeof value === 'string' && /^[0-9a-f]{40}$/.test(value);
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };

export class ManagedGit {
  constructor({ cwd, git = 'git', readIssuePrefix }) {
    this.cwd = fs.realpathSync(cwd); this.git = git;
    requireThat(this.call(['rev-parse', '--is-bare-repository']).trim() === 'false', 'managed publisher requires non-bare canonical main checkout');
    const common = this.call(['rev-parse', '--path-format=absolute', '--git-common-dir']).trim();
    const gitDir = this.call(['rev-parse', '--path-format=absolute', '--git-dir']).trim();
    requireThat(common === gitDir, 'managed publisher requires main checkout, not linked worktree');
    this.common = fs.realpathSync(common);
    requireThat(fs.realpathSync(this.call(['rev-parse', '--show-toplevel']).trim()) === this.cwd, 'managed Git context root mismatch');
    this.prefix = loadProjectPrefix(this.cwd, { readIssuePrefix });
  }
  call(args, { input, index } = {}) {
    const env = { ...process.env, MSYS2_ARG_CONV_EXCL: '*' };
    delete env.GIT_INDEX_FILE;
    if (index) env.GIT_INDEX_FILE = index;
    return execFileSync(this.git, args, { cwd: this.cwd, env, input, encoding: 'utf8', timeout: 30000, maxBuffer: 32 * 1024 * 1024, stdio: ['pipe', 'pipe', 'pipe'] });
  }
  optional(commit, file) {
    requireThat(validSha(commit) && commit !== ZERO, 'invalid frozen commit');
    const entry = this.call(['ls-tree', '--full-tree', '--name-only', commit, '--', file]).trim();
    if (!entry) return null;
    requireThat(entry === file, 'unexpected snapshot tree entry');
    return this.call(['show', `${commit}:${file}`]);
  }
  readAt(commit) {
    if (commit === ZERO) return { R: ZERO, snapshot: '', ledger: emptyLedger(), activated: false };
    const snapshot = this.optional(commit, snapshotPath);
    requireThat(snapshot !== null, 'published canonical snapshot missing; no count-based legacy adoption');
    normalizeSnapshot(snapshot, 'published snapshot');
    const rawLedger = this.optional(commit, ledgerPath), rawProtocol = this.optional(commit, protocolPath);
    requireThat((rawLedger === null) === (rawProtocol === null), 'managed ledger/protocol missing or downgraded');
    if (rawLedger === null) return { R: commit, snapshot, ledger: emptyLedger(), activated: false };
    const ledger = parseLedger(rawLedger), protocol = JSON.parse(rawProtocol);
    requireThat(canonical(Object.keys(protocol).sort()) === canonical(['ledger_sha256', 'prefix', 'snapshot_sha256', 'version'])
      && protocol.version === 1 && protocol.prefix === this.prefix && protocol.snapshot_sha256 === digest(snapshot) && protocol.ledger_sha256 === digest(rawLedger), 'managed protocol/hash/prefix mismatch');
    return { R: commit, snapshot, ledger, activated: true };
  }
  readPublished(anchor = null) {
    let seen = null;
    try { this.call(['show-ref', '--verify', '--quiet', seenRef]); seen = this.call(['rev-parse', '--verify', `${seenRef}^{commit}`]).trim(); }
    catch (error) { if (error.status !== 1) throw error; }
    try { this.call(['ls-remote', '--exit-code', '--heads', 'origin', `refs/heads/${branch}`]); }
    catch (error) {
      if (error.status === 2) { requireThat(!anchor && !seen, 'history anchor missing: remote branch absent'); return this.readAt(ZERO); }
      throw new Error(`ls-remote failed (not confirmed missing branch): ${error.message}`);
    }
    this.call(['fetch', '-q', 'origin', `+refs/heads/${branch}:refs/remotes/origin/${branch}`]);
    const R = this.call(['rev-parse', '--verify', `refs/remotes/origin/${branch}^{commit}`]).trim();
    const shallowFile = path.resolve(this.cwd, this.call(['rev-parse', '--git-path', 'shallow']).trim());
    const shallowRaw = fs.existsSync(shallowFile) ? fs.readFileSync(shallowFile, 'utf8') : '';
    const commits = this.call(['rev-list', '--reverse', '--topo-order', R]).trim().split('\n');
    if (anchor) requireThat(commits.includes(anchor), 'required history anchor missing/rewound');
    if (seen) requireThat(commits.includes(seen), 'local managed history anchor missing/rewound');
    // Shallow unrelated code history не мешает Beads. Непроверенная граница
    // внутри требуемого task segment не превращается в доказанный root.
    const required = new Set(seen ? commits.slice(commits.indexOf(seen) + 1) : commits);
    const boundaries = shallowRaw.split(/\s+/).filter(Boolean);
    requireThat(boundaries.every(validSha) && !boundaries.some(sha => required.has(sha)), 'required Beads history/anchor is shallow; use a publisher retaining this segment');
    let start;
    if (seen) {
      requireThat(this.readAt(seen).activated, 'invalid local managed history checkpoint'); start = commits.indexOf(seen);
    } else {
      const additions = new Set(this.call(['log', '--reverse', '--topo-order', '--diff-filter=A', '--format=%H', R, '--', protocolPath]).trim().split('\n').filter(Boolean));
      start = commits.findIndex(sha => additions.has(sha));
    }
    const segment = start < 0 ? [R] : commits.slice(start);
    const history = segment.map(sha => {
      const raw = this.optional(sha, ledgerPath), protocol = this.optional(sha, protocolPath);
      requireThat((raw === null) === (protocol === null), 'managed ledger/protocol downgrade in retained history');
      if (raw !== null) this.readAt(sha);
      return { sha, ledger: raw === null ? null : parseLedger(raw) };
    });
    const checked = validateManagedHistory(history, seen);
    requireThat((fs.existsSync(shallowFile) ? fs.readFileSync(shallowFile, 'utf8') : '') === shallowRaw, 'Git history boundary changed during proof; retry published read');
    const state = { ...this.readAt(R), activation: checked.activation, history: commits };
    if (state.activated && seen !== R) {
      // CAS собственного ref не позволяет конкурентному reader откатить anchor назад.
      try { this.call(['update-ref', seenRef, R, seen || ZERO]); }
      catch { throw new Error('local managed history anchor advanced concurrently; retry published read'); }
    }
    return state;
  }
  commitCandidate({ base, snapshot, ledger }) {
    requireThat(validSha(base), 'candidate base invalid');
    normalizeSnapshot(snapshot, 'candidate snapshot'); parseLedger(canonical(ledger));
    if (base !== ZERO) assertLedgerExtension(this.readAt(base).ledger, ledger);
    const ledgerRaw = canonical(ledger) + '\n';
    const protocolRaw = canonical({ version: 1, prefix: this.prefix, snapshot_sha256: digest(snapshot), ledger_sha256: digest(ledgerRaw) }) + '\n';
    const temporary = fs.mkdtempSync(path.join(this.common, 'overgate-managed-index-')), index = path.join(temporary, 'index');
    try {
      this.call(base === ZERO ? ['read-tree', '--empty'] : ['read-tree', `${base}^{tree}`], { index });
      for (const [file, raw] of [[snapshotPath, snapshot], [ledgerPath, ledgerRaw], [protocolPath, protocolRaw]]) {
        const blob = this.call(['hash-object', '-w', '--stdin'], { input: raw }).trim();
        this.call(['update-index', '--add', '--cacheinfo', `100644,${blob},${file}`], { index });
      }
      const tree = this.call(['write-tree'], { index }).trim();
      return this.call(['commit-tree', tree, ...(base === ZERO ? [] : ['-p', base]), '-m', 'beads-backup: managed CLI transaction']).trim();
    } finally {
      requireThat(path.resolve(temporary).startsWith(this.common + path.sep), 'unsafe temporary index cleanup');
      fs.rmSync(temporary, { recursive: true, force: true });
    }
  }
  pinCandidate(commit, queueHash) {
    requireThat(validSha(commit) && /^[0-9a-f]{64}$/.test(queueHash), 'candidate pin invalid');
    this.call(['update-ref', `refs/overgate-bd-managed/pending/${queueHash}/${commit}`, commit]);
  }
  pushCandidate(commit) {
    requireThat(validSha(commit) && commit !== ZERO, 'candidate push invalid');
    this.call(['push', '--no-follow-tags', 'origin', `${commit}:refs/heads/${branch}`]);
  }
}
