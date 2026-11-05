import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { loadProjectPrefix } from '../lib/bd-managed-project.mjs';
import { materializeFresh } from '../lib/bd-managed-cli.mjs';

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

// Native Windows Beads may spell the same owned temp repo differently and
// report a false redirect. The projection must still reject a real redirect,
// foreign path, or init that returned success without creating local state.
const parent = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-bd-context-')));
const actor = 'agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2';
try {
  const foreign = path.join(parent, 'other-store');
  fs.mkdirSync(path.join(foreign, '.beads'), { recursive: true });
  for (const mode of ['alias', 'foreign', 'redirect', 'traversal', 'missing', 'wrong-prefix']) {
    const directory = path.join(parent, mode);
    fs.mkdirSync(directory);
    let cwd, alias;
    const run = (program, args, options) => {
      if (program === 'git') {
        const output = execFileSync(program, args, { ...options, encoding: 'utf8' });
        cwd = path.join(directory, 'tmp', 'store');
        if (mode === 'alias') {
          if (process.platform === 'win32')
            alias = cwd.replace(/^([A-Za-z]):/, (_, drive) => `${drive === drive.toUpperCase() ? drive.toLowerCase() : drive.toUpperCase()}:`);
          else {
            alias = path.join(parent, 'owned-alias');
            fs.symlinkSync(cwd, alias, 'dir');
          }
          assert.notEqual(alias, cwd);
          assert.equal(fs.realpathSync.native(alias), fs.realpathSync.native(cwd));
        }
        if (mode === 'redirect') fs.writeFileSync(path.join(cwd, '.beads', 'redirect'), '../foreign\n');
        return output;
      }
      if (args.includes('--version')) return 'bd version 1.2.2';
      if (args.includes('--help')) return '--prefix --non-interactive --skip-agents --skip-hooks --all --output --json';
      if (args.includes('context')) {
        const target = mode === 'foreign' ? foreign : alias || cwd;
        return JSON.stringify({ beads_dir: path.join(target, '.beads'), repo_root: target, cwd_repo_root: target,
          is_redirected: mode !== 'missing', is_worktree: false, backend: 'dolt', dolt_mode: 'embedded',
          data_dir: mode === 'traversal' ? '../escape' : 'embeddeddolt' });
      }
      if (args.includes('init')) {
        if (mode !== 'missing') {
          fs.writeFileSync(path.join(cwd, '.beads', 'metadata.json'), JSON.stringify({ backend: 'dolt', dolt_mode: 'embedded',
            dolt_database: 'big_heroes', project_id: 'synthetic-project' }));
          fs.mkdirSync(path.join(cwd, '.beads', 'embeddeddolt'));
        }
        return '';
      }
      if (args.includes('config')) return JSON.stringify({ issue_prefix: mode === 'wrong-prefix' ? 'other' : 'big-heroes' });
      if (args.includes('import')) return '{}';
      if (args.includes('export')) { fs.writeFileSync(args[args.indexOf('--output') + 1], ''); return ''; }
      throw new Error('unexpected fresh CLI call');
    };
    const project = () => materializeFresh({ directory, binary: process.execPath, actor, snapshot: '', run,
      qualify: () => 'fixture-qualified' });
    if (mode === 'alias') assert.equal(project().rows.length, 0);
    else assert.throws(project, mode === 'foreign' ? /context paths/ : mode === 'redirect' ? /redirect/ :
      mode === 'traversal' ? /data_dir outside/ : mode === 'missing' ? /local state/ : /local prefix/);
  }
} finally {
  fs.rmSync(parent, { recursive: true, force: true });
}
