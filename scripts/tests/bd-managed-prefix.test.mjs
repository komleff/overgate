import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { loadProjectPrefix } from '../lib/bd-managed-project.mjs';

// У Beads issue prefix может содержать дефис, а имя Dolt DB заменяет его на подчёркивание.
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-bd-prefix-'));
try {
  execFileSync('git', ['init', '-q', root]);
  execFileSync('git', ['config', '--local', 'overgate.beadsPrefix', 'big-heroes'], { cwd: root });
  fs.mkdirSync(path.join(root, '.beads'));
  fs.writeFileSync(path.join(root, '.beads/metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded', dolt_database: 'big_heroes' }));
  fs.writeFileSync(path.join(root, '.beads/config.yaml'), '# issue-prefix: "example"\n');
  assert.equal(loadProjectPrefix(root, { readIssuePrefix: () => 'big-heroes' }), 'big-heroes');
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
