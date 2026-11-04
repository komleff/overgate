// Префикс берётся из действующего Beads store и закреплён в local publisher registration.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { configureProjectPrefix } from './bd-managed-contract.mjs';

function readIssuePrefix(root) {
  let binary;
  try { binary = execFileSync('git', ['config', '--local', '--get', 'overgate.beadsCli'], { cwd: root, encoding: 'utf8' }).trim(); }
  catch { throw new Error('qualified Beads CLI registration missing'); }
  if (!path.isAbsolute(binary)) throw new Error('qualified Beads CLI path must be absolute');
  const stat = fs.lstatSync(binary);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('qualified Beads CLI must be a regular file');
  const raw = execFileSync(binary, ['--readonly', 'config', 'list', '--json'], { cwd: root, encoding: 'utf8', timeout: 30000,
    maxBuffer: 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  return JSON.parse(raw).issue_prefix;
}

export function loadProjectPrefix(root, { readIssuePrefix: readPrefix = readIssuePrefix } = {}) {
  const beadsRoot = path.join(root, '.beads');
  if (fs.lstatSync(beadsRoot).isSymbolicLink()) throw new Error('project Beads directory symlink denied');
  const metadataFile = path.join(beadsRoot, 'metadata.json');
  const metadataStat = fs.lstatSync(metadataFile);
  if (!metadataStat.isFile() || metadataStat.isSymbolicLink()) throw new Error('project Beads metadata must be a regular file');
  const metadata = JSON.parse(fs.readFileSync(metadataFile, 'utf8'));
  if (metadata.backend !== 'dolt' || !['embedded', 'server'].includes(metadata.dolt_mode)
    || typeof metadata.dolt_database !== 'string' || !/^[A-Za-z][A-Za-z0-9_]*$/.test(metadata.dolt_database))
    throw new Error('project Beads metadata invalid');
  const prefix = readPrefix(root);
  if (typeof prefix !== 'string' || !/^[A-Za-z][A-Za-z0-9-]*$/.test(prefix)) throw new Error('project Beads issue prefix invalid');
  const configFile = path.join(beadsRoot, 'config.yaml');
  if (fs.existsSync(configFile)) {
    const stat = fs.lstatSync(configFile);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('project Beads config must be a regular file');
    const lines = fs.readFileSync(configFile, 'utf8').split(/\r?\n/).filter(line => /^\s*issue-prefix\s*:/.test(line));
    if (lines.length > 1) throw new Error('project Beads config has duplicate issue-prefix');
    if (lines.length === 1 && lines[0].replace(/^\s*issue-prefix\s*:\s*/, '').trim().replace(/^['"]|['"]$/g, '') !== prefix)
      throw new Error('project Beads config/metadata prefix mismatch');
  }
  let pinned;
  try { pinned = execFileSync('git', ['config', '--local', '--get', 'overgate.beadsPrefix'], { cwd: root, encoding: 'utf8' }).trim(); }
  catch { throw new Error('publisher prefix registration missing'); }
  if (pinned !== prefix) throw new Error('publisher prefix registration mismatch');
  configureProjectPrefix(prefix);
  return prefix;
}
