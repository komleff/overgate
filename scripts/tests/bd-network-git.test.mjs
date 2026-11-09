// og-4py (ADR §3.39): сетевые вызовы Beads получают перенос allowlist пользовательского Git
// config; прочие вызовы остаются в чистой изоляции. Shell, mjs и python проверяются на одной
// фикстуре. Живой credential не используется: только fixture-helper и маркеры.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync, spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as gitEnvironment from '../lib/bd-git-environment.mjs';

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const python = path.join(source, '.claude/tools/run-python.sh');
const installerPath = path.join(source, 'scripts/install-overgate.py');
const activationPath = path.join(source, 'scripts/bd-activate.py');
const moduleUrl = pathToFileURL(path.join(source, 'scripts/lib/bd-git-environment.mjs')).href;
const OVERRIDE = 'OVERGATE_GIT_USER_CONFIG_FILE';
const SECRET = 'SECRET-TOKEN-og4py';
const ALLOW = '^(credential\\..+|user\\.name|user\\.email)$';
const realGit = execFileSync('sh', ['-c', 'command -v git'], { encoding: 'utf8' }).trim();
const temporaryRoots = [];
const tmp = name => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), `og-net-${name}-`)));
  temporaryRoots.push(directory);
  return directory;
};
test.after(() => { for (const directory of temporaryRoots) fs.rmSync(directory, { recursive: true, force: true }); });

const emptyHome = tmp('empty-home');
// Окружение маршрута без caller GIT_* и без пользовательского config разработчика.
function baseEnv(extra = {}) {
  const env = {};
  for (const [name, value] of Object.entries(process.env)) if (!name.startsWith('GIT_') && name !== OVERRIDE) env[name] = value;
  return { ...env, HOME: emptyHome, XDG_CONFIG_HOME: path.join(emptyHome, '.config'), ...extra };
}
const fixtureEnv = baseEnv({ GIT_CONFIG_NOSYSTEM: '1' });
// Явная identity для коммитов подготовки фикстур: пустой HOME, а на Linux runner git не
// выводит имя из GECOS. Только для этого вызова, repo-local config не меняется.
const FIXTURE_IDENTITY = ['-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid'];
const git = (cwd, ...args) => execFileSync('git', args, { cwd, env: fixtureEnv, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();

let overrideCount = 0;
function overrideFile(directory, entries) {
  const file = path.join(directory, `override-${overrideCount++}`);
  fs.writeFileSync(file, Buffer.concat(entries.map(([scope, key, value]) => Buffer.from(`${scope}\0${key}${value === null ? '' : '\n' + value}\0`, 'utf8'))));
  return file;
}
// Prefix для ManagedGit без CLI: закреплённая регистрация и publisher control.
function registerPrefix(root) {
  const real = fs.realpathSync(root), control = path.join(real, '.git', 'overgate-bd-publisher-control');
  git(real, 'config', '--local', 'overgate.beadsPrefix', 'og');
  fs.mkdirSync(control, { recursive: true });
  fs.writeFileSync(path.join(control, 'guard-config.json'), JSON.stringify({ version: 1, mode: 'managed', repositoryRoot: real, publisherRoot: real, projectPrefix: 'og' }));
  fs.writeFileSync(path.join(control, 'installed.json'), '{}\n');
}
function repository(name, origin = 'https://example.invalid/project.git') {
  const root = path.join(tmp(name), 'repo');
  git(path.dirname(root), 'init', '-q', '-b', 'main', root);
  if (origin) git(root, 'remote', 'add', 'origin', origin);
  return root;
}

// Перенос в окружение сетевого вызова: `git config --global -z --list` под network env.
const PY_CARRIED = `
import importlib.util,sys
spec=importlib.util.spec_from_file_location('installer',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
try:sys.stdout.write(m.net_git(sys.argv[2],'config','--global','-z','--list').decode('utf-8'))
except m.InstallError as error:sys.stderr.write('STOP: '+str(error)+'\\n');sys.exit(1)
`;
const MJS_CARRIED = `
import { execFileSync } from 'node:child_process';
const [url, root] = process.argv.slice(1);
const { networkGitEnvironment } = await import(url);
try { process.stdout.write(execFileSync('git', ['config', '--global', '-z', '--list'], { cwd: root, env: networkGitEnvironment(root) }).toString('utf8')); }
catch (error) { process.stderr.write('ERROR: ' + error.message + '\\n'); process.exit(1); }
`;
const SHELL_CARRIED = '. "$1/scripts/lib/bd-env.sh"; bd_env_sanitize_git; bd_env_network_git "$2" config --global -z --list';
function carriedVia(language, root, env) {
  if (language === 'shell') return spawnSync('bash', ['-c', SHELL_CARRIED, '_', source, root], { cwd: root, env, encoding: 'utf8' });
  if (language === 'python') return spawnSync(python, ['-I', '-c', PY_CARRIED, installerPath, root], { cwd: root, env, encoding: 'utf8' });
  return spawnSync(process.execPath, ['--input-type=module', '-e', MJS_CARRIED, moduleUrl, root], { cwd: root, env, encoding: 'utf8' });
}
const LANGUAGES = ['shell', 'mjs', 'python'];
const records = raw => raw.split('\0').filter(Boolean);

test('step 1 inventory: every network Git call goes through the network environment; others stay isolated', () => {
  const read = name => fs.readFileSync(path.join(source, name), 'utf8');
  const shellRoutes = ['scripts/bd-sync-common.sh', 'scripts/bd-sync-export.sh', 'scripts/bd-sync-restore.sh', 'scripts/bd-read.sh',
    'scripts/bd-apply-intents.sh', 'scripts/bd-wt.sh', 'scripts/lib/bd-env.sh'];
  const expectedShell = { 'scripts/bd-sync-common.sh': 2, 'scripts/bd-sync-export.sh': 5, 'scripts/bd-sync-restore.sh': 1,
    'scripts/bd-apply-intents.sh': 1, 'scripts/bd-wt.sh': 2, 'scripts/lib/bd-env.sh': 3 };
  for (const name of shellRoutes) {
    const code = read(name).split('\n').filter(line => !/^\s*#/.test(line)).join('\n');
    assert.doesNotMatch(code, /(^|[\s;|&(`$])git(\s+-C\s+\S+)?\s+(ls-remote|fetch|push|commit-tree)\b/m, `${name}: direct network git call`);
    const calls = (code.match(/bd_env_network_git\s+"[^"]+"\s+(ls-remote|fetch|push|commit-tree)\b/g) || []).length;
    assert.equal(calls, expectedShell[name] ?? 0, `${name}: network call inventory`);
  }
  assert.match(read('scripts/bd-read.sh'), /bd_env_fetch_backup/);
  const bootstrap = read('scripts/bd-bootstrap.sh');
  assert.doesNotMatch(bootstrap, /call\('git','(ls-remote|fetch|push)'/, 'bootstrap inline Python network call without network env');
  assert.equal((bootstrap.match(/net\('(ls-remote|fetch)'/g) || []).length, 7, 'bootstrap network call inventory');
  const managed = read('scripts/lib/bd-managed-git.mjs');
  for (const command of ['ls-remote', 'fetch', 'push', 'commit-tree']) {
    const lines = managed.split('\n').filter(line => line.includes(`'${command}'`) && line.includes('this.call('));
    assert.ok(lines.length > 0 && lines.every(line => /network: true/.test(line)), `ManagedGit ${command} must use network env`);
  }
  const setup = read('scripts/bd-publisher-setup.mjs');
  assert.ok(setup.split('\n').filter(line => line.includes("'ls-remote'")).every(line => /networkGit\(/.test(line)), 'publisher setup ls-remote');
  for (const name of ['scripts/install-overgate.py', 'scripts/bd-activate.py', 'scripts/bd-upgrade-fence.py', 'scripts/bd-upgrade-preserve.py']) {
    const lines = read(name).split('\n').filter(line => /'(ls-remote|fetch|push)'/.test(line) && !/^\s*#/.test(line) && !line.includes('_PROBES') && !line.includes("'push-dry-run'"));
    for (const line of lines) assert.match(line, /net_git\(|network_git_environment\(|prompt_env/, `${name}: ${line.trim()}`);
  }
  for (const name of ['scripts/lib/bd-managed-cli.mjs', 'scripts/lib/bd-managed-project.mjs', 'scripts/lib/bd-managed-read-check.mjs', 'scripts/lib/bd-publisher-push-guard.mjs'])
    assert.doesNotMatch(read(name), /networkGitEnvironment/, `${name} must keep pure isolation`);
  assert.match(read('scripts/lib/bd-env.sh'), /bd_env_sanitize_git\(\) \{[\s\S]*?GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0\n\}/, 'pure isolation unchanged');
});

test('reader framing: valid, empty, broken and non-UTF-8 input; values never in errors (mjs)', () => {
  const { parseUserGitConfig } = gitEnvironment;
  assert.equal(typeof parseUserGitConfig, 'function');
  assert.deepEqual(parseUserGitConfig(Buffer.alloc(0)), []);
  assert.deepEqual(parseUserGitConfig(Buffer.from('unknown\0credential.helper\nosxkeychain\0global\0credential.usehttppath\0')),
    [{ scope: 'unknown', key: 'credential.helper', value: 'osxkeychain' }, { scope: 'global', key: 'credential.usehttppath', value: null }]);
  for (const raw of [`global\0credential.helper\n${SECRET}`, `global\0credential.helper\n${SECRET}\0global\0`, `bogus\0credential.helper\n${SECRET}\0`,
    `global\0\n${SECRET}\0`]) {
    assert.throws(() => parseUserGitConfig(Buffer.from(raw)), error => /fail-closed/.test(error.message) && !error.message.includes(SECRET));
  }
  assert.throws(() => parseUserGitConfig(Buffer.from([0x67, 0x6c, 0x6f, 0x62, 0x61, 0x6c, 0, 0x6b, 0x2e, 0x6b, 0x0a, 0xff, 0])), /encoding|framing/);
});

test('B-02/B-03/B-04/B-05: fixture HOME/XDG carry only the allowlist with git order, includes and identical result in shell/mjs/python', () => {
  const work = tmp('home');
  const home = path.join(work, 'home'), xdg = path.join(work, 'xdg');
  fs.mkdirSync(path.join(xdg, 'git'), { recursive: true }); fs.mkdirSync(home);
  const root = repository('home-repo');
  git(root, 'config', '--local', 'user.name', 'Local Name');
  fs.writeFileSync(path.join(xdg, 'git/config'), '[credential "https://xdg.example"]\n\thelper = "!xdg-helper \\"arg; #x\\""\n');
  fs.writeFileSync(path.join(home, 'included.inc'), '[credential "https://included.example"]\n\thelper = !included-helper\n');
  fs.writeFileSync(path.join(home, 'gitdir.inc'), '[credential "https://gitdir.example"]\n\thelper = !gitdir-helper\n');
  fs.writeFileSync(path.join(home, 'hasconfig.inc'), '[credential "https://hasconfig.example"]\n\thelper = !hasconfig-helper\n');
  fs.writeFileSync(path.join(home, '.gitconfig'), [
    '[credential "https://github.com"]', '\thelper =', '\thelper = !fixture-gh auth git-credential',
    '[credential]', '\tuseHttpPath = true',
    '[user]', '\tname = Global Fixture', '\temail = global@example.invalid',
    '[url "file:///evil"]', '\tinsteadOf = https://example.invalid/',
    '[alias]', '\tpwn = !echo pwned', '[core]', '\thooksPath = /evil/hooks',
    '[include]', '\tpath = included.inc',
    `[includeIf "gitdir:${root}/"]`, '\tpath = gitdir.inc',
    '[includeIf "hasconfig:remote.*.url:https://example.invalid/**"]', '\tpath = hasconfig.inc', ''].join('\n'));
  const spoof = path.join(work, 'spoof-global');
  fs.writeFileSync(spoof, '[credential]\n\thelper = !spoof-helper\n[url "file:///spoof"]\n\tinsteadOf = https://example.invalid/\n');
  // Оракул — сам git: тот же HOME/XDG, без caller GIT_*.
  const oracleRaw = execFileSync('git', ['config', '--show-scope', '--includes', '-z', '--get-regexp', ALLOW],
    { cwd: root, env: baseEnv({ HOME: home, XDG_CONFIG_HOME: xdg }) });
  const fields = records(oracleRaw.toString('utf8'));
  const expected = [];
  for (let index = 0; index < fields.length; index += 2) if (['system', 'global', 'unknown'].includes(fields[index])) expected.push(fields[index + 1]);
  for (const helper of ['!fixture-gh auth git-credential', '!included-helper', '!gitdir-helper', '!hasconfig-helper', '!xdg-helper "arg; #x"'])
    assert.ok(expected.some(item => item.endsWith('\n' + helper)), `oracle fixture lacks ${helper}`);
  const env = baseEnv({ HOME: home, XDG_CONFIG_HOME: xdg, GIT_CONFIG_GLOBAL: spoof, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_COUNT: '1',
    GIT_CONFIG_KEY_0: 'credential.helper', GIT_CONFIG_VALUE_0: '!count-spoof' });
  const outputs = {};
  for (const language of LANGUAGES) {
    const run = carriedVia(language, root, env);
    assert.equal(run.status, 0, `${language}: ${run.stderr}`);
    outputs[language] = run.stdout;
    assert.deepEqual(records(run.stdout), expected, `${language}: carried entries equal git order (system/unknown/global)`);
    assert.doesNotMatch(run.stdout, /spoof|pwned|evil|hookspath|insteadof|include\.path|includeif/i, `${language}: only allowlist carried`);
  }
  assert.equal(outputs.shell, outputs.mjs, 'B-05 shell/mjs parity');
  assert.equal(outputs.python, outputs.mjs, 'B-05 python/mjs parity');
  const network = gitEnvironment.networkGitEnvironment(root, env);
  try {
    const read = (...args) => spawnSync('git', args, { cwd: root, env: network, encoding: 'utf8' });
    assert.equal(read('config', '--get', 'user.name').stdout.trim(), 'Local Name', 'local identity wins');
    assert.equal(read('config', '--get', 'user.email').stdout.trim(), 'global@example.invalid', 'global identity carried');
    assert.equal(read('config', '--get-regexp', '^(url|alias|core\\.hookspath|include)').stdout, '', 'B-03 no rewrite/alias/hooks');
    assert.equal(read('remote', 'get-url', 'origin').stdout.trim(), 'https://example.invalid/project.git', 'origin only from local config');
  } finally { gitEnvironment.disposeNetworkGitEnvironment(); }
});

test('B-09/seam: override with system/unknown scope survives inherited GIT_CONFIG_NOSYSTEM; empty source is valid; broken framing fails closed', () => {
  const work = tmp('seam'), root = repository('seam-repo');
  const override = overrideFile(work, [['unknown', 'credential.helper', 'osxkeychain-fixture'], ['system', 'credential.helper', 'manager-fixture'],
    ['local', 'credential.helper', 'local-dropped'], ['command', 'credential.helper', 'command-dropped'], ['global', 'url.file:///evil.insteadof', 'x'],
    ['global', 'user.email', 'seam@example.invalid'], ['global', 'credential.usehttppath', null],
    ['global', 'credential.https://a b.example/"q"\\.helper', '!x "q" \\ ; # \ttab\nline']]);
  const env = baseEnv({ [OVERRIDE]: override, GIT_CONFIG_NOSYSTEM: '1' });
  for (const language of LANGUAGES) {
    const run = carriedVia(language, root, env);
    assert.equal(run.status, 0, `${language}: ${run.stderr}`);
    assert.deepEqual(records(run.stdout), ['credential.helper\nosxkeychain-fixture', 'credential.helper\nmanager-fixture', 'user.email\nseam@example.invalid',
      'credential.usehttppath', 'credential.https://a b.example/"q"\\.helper\n!x "q" \\ ; # \ttab\nline'], language);
  }
  const empty = overrideFile(work, []);
  for (const language of LANGUAGES) {
    const run = carriedVia(language, root, baseEnv({ [OVERRIDE]: empty }));
    assert.equal(run.status, 0, `${language}: ${run.stderr}`);
    assert.equal(run.stdout, '', `${language}: empty source carries nothing`);
  }
  const broken = [path.join(work, 'missing-override'), (() => { const file = path.join(work, 'broken'); fs.writeFileSync(file, `global\0credential.helper\n${SECRET}`); return file; })(),
    (() => { const file = path.join(work, 'scope'); fs.writeFileSync(file, `galaxy\0credential.helper\n${SECRET}\0`); return file; })()];
  for (const file of broken) for (const language of LANGUAGES) {
    const run = carriedVia(language, root, baseEnv({ [OVERRIDE]: file }));
    assert.notEqual(run.status, 0, `${language}: ${file} must fail closed`);
    assert.match(run.stderr, /fail-closed/, `${language}: diagnostic`);
    assert.ok(!run.stderr.includes(SECRET) && !run.stdout.includes(SECRET), `${language}: value leaked`);
  }
});

test('B-04 order: interleaved sections keep git helper order and reset after transfer (credential fill in shell/mjs/python env)', () => {
  const work = tmp('order'), root = repository('order-repo', null), log = path.join(work, 'helpers.log');
  const marker = name => `!echo ${name} >> '${log}'`;
  const global = path.join(work, 'global');
  fs.writeFileSync(global, `[credential]\n\thelper = ${marker('A')}\n[credential "https://github.com"]\n\thelper =\n[credential]\n\thelper = ${marker('B')}\n`);
  const override = overrideFile(work, [['unknown', 'credential.helper', marker('A')], ['global', 'credential.https://github.com.helper', ''],
    ['global', 'credential.helper', marker('B')]]);
  const fill = (language, url) => {
    const input = `url=${url}\n\n`, env = baseEnv({ [OVERRIDE]: override, SSH_ASKPASS: '' });
    fs.writeFileSync(log, '');
    if (language === 'git') spawnSync('git', ['credential', 'fill'], { cwd: root, input, encoding: 'utf8',
      env: baseEnv({ GIT_CONFIG_GLOBAL: global, GIT_CONFIG_NOSYSTEM: '1', GIT_TERMINAL_PROMPT: '0', SSH_ASKPASS: '' }) });
    else if (language === 'shell') spawnSync('bash', ['-c', '. "$1/scripts/lib/bd-env.sh"; bd_env_sanitize_git; bd_env_network_git "$2" credential fill', '_', source, root], { cwd: root, input, env, encoding: 'utf8' });
    else if (language === 'python') spawnSync(python, ['-I', '-c', `import importlib.util,subprocess,sys
spec=importlib.util.spec_from_file_location('i',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
subprocess.run(['git','credential','fill'],cwd=sys.argv[2],input=sys.stdin.buffer.read(),env=m.network_git_environment(sys.argv[2]))`, installerPath, root], { cwd: root, input, env, encoding: 'utf8' });
    else spawnSync(process.execPath, ['--input-type=module', '-e', `import { spawnSync } from 'node:child_process'; import fs from 'node:fs';
const { networkGitEnvironment } = await import(process.argv[1]);
spawnSync('git', ['credential', 'fill'], { cwd: process.argv[2], input: fs.readFileSync(0), env: networkGitEnvironment(process.argv[2]) });`, moduleUrl, root], { cwd: root, input, env, encoding: 'utf8' });
    return fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).map(line => line.split(' ')[0]);
  };
  for (const url of ['https://github.com/o/r.git', 'https://gitlab.com/g/p.git']) {
    const expected = fill('git', url);
    assert.deepEqual(expected, url.includes('github') ? ['B'] : ['A', 'B'], 'oracle fixture');
    for (const language of LANGUAGES) assert.deepEqual(fill(language, url), expected, `${language} ${url}`);
  }
});

test('B-04: Git without --show-scope fails closed with a version diagnostic', () => {
  const work = tmp('old-git'), root = repository('old-git-repo'), bin = path.join(work, 'bin');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'git'), `#!/bin/sh\nfor a in "$@"; do [ "$a" = --show-scope ] && { echo "error: unknown option" >&2; exit 129; }; done\nexec '${realGit}' "$@"\n`, { mode: 0o755 });
  for (const language of LANGUAGES) {
    const run = carriedVia(language, root, baseEnv({ PATH: `${bin}${path.delimiter}${process.env.PATH}` }));
    assert.notEqual(run.status, 0, language);
    assert.match(run.stderr, /2\.26/, `${language}: version diagnostic`);
  }
});

// Матрица конфигов для url-match: оракул — `git credential fill` с fixture-helper.
function credentialMatrix(work) {
  const log = path.join(work, 'helpers.log');
  const marker = name => `!echo ${name} >> '${log}'`;
  const configs = {
    rules: ['[credential]', `\thelper = ${marker('SYS')}`, '\tuseHttpPath = true',
      '[credential "https://github.com"]', '\thelper =', `\thelper = ${marker('GH')}`,
      '[credential "https://*.example.com"]', `\thelper = ${marker('WILD')}`,
      '[credential "https://user@gitlab.com"]', `\thelper = ${marker('USERGL')}`,
      '[credential "https://gitlab.com/group"]', `\thelper = ${marker('PATHGL')}`,
      '[credential "github.com"]', `\thelper = ${marker('PARTIAL')}`,
      '[credential "https://example.org:8443"]', `\thelper = ${marker('PORT')}`],
    operator: ['[credential]', `\thelper = ${marker('KEYCHAIN')}`, '[credential "https://github.com"]', '\thelper =', `\thelper = ${marker('GHCLI')}`],
    resetOnly: ['[credential "https://example.com"]', '\thelper ='],
  };
  const urls = ['https://github.com/o/r.git', 'https://a.example.com/x', 'https://a.b.example.com/x', 'https://example.com/x',
    'https://user@gitlab.com/group/p.git', 'https://gitlab.com/group/p.git', 'https://gitlab.com/groupx/p.git', 'https://other@gitlab.com/group',
    'https://GitHub.com:443/o/r', 'http://github.com/o', 'https://example.org:8443/r', 'https://example.org/r', 'https://x@github.com/o/r.git'];
  return { log, configs, urls };
}

test('B-04 url-match: mjs and python helper lists equal `git credential fill` with fixture helpers', () => {
  const work = tmp('oracle'), root = repository('oracle-repo', null);
  const { log, configs, urls } = credentialMatrix(work);
  const cases = [];
  for (const [name, lines] of Object.entries(configs)) {
    const file = path.join(work, `${name}.gitconfig`); fs.writeFileSync(file, lines.join('\n') + '\n');
    const env = baseEnv({ GIT_CONFIG_GLOBAL: file, GIT_CONFIG_NOSYSTEM: '1', GIT_TERMINAL_PROMPT: '0', SSH_ASKPASS: '' });
    const entries = records(execFileSync('git', ['config', '-z', '--get-regexp', '^credential\\.'], { cwd: root, env }).toString('utf8'))
      .map(record => { const at = record.indexOf('\n'); return at < 0 ? [record, null] : [record.slice(0, at), record.slice(at + 1)]; });
    for (const url of name === 'rules' ? urls : ['https://github.com/o/r.git', 'https://gitlab.com/g/p.git', 'https://example.com/x']) {
      fs.writeFileSync(log, '');
      spawnSync('git', ['credential', 'fill'], { cwd: root, env, input: `url=${url}\n\n`, encoding: 'utf8', timeout: 30000 });
      const oracle = fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).map(line => line.split(' ')[0]);
      cases.push({ name, url, entries, oracle });
    }
  }
  assert.ok(cases.some(item => item.oracle.length === 0) && cases.some(item => item.oracle.length > 1), 'matrix covers empty and multi-helper results');
  const markers = list => list.map(value => value.split(' ')[1]);
  for (const item of cases) {
    const mjs = gitEnvironment.credentialHelpersFromEntries(item.entries.map(([key, value]) => ({ key, value })), item.url);
    assert.deepEqual(markers(mjs), item.oracle, `mjs ${item.name} ${item.url}`);
  }
  const script = `
import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('installer',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cases=json.loads(sys.stdin.read())
print(json.dumps([m.credential_helpers_from_entries([tuple(e) for e in c['entries']],c['url']) for c in cases]))
`;
  const run = spawnSync(python, ['-I', '-c', script, installerPath], { input: JSON.stringify(cases), encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  JSON.parse(run.stdout).forEach((list, index) => assert.deepEqual(markers(list), cases[index].oracle, `python ${cases[index].name} ${cases[index].url}`));
});

test('step 3 preflight: operator config passes; reset-only and missing identity keep previous fail-closed messages (mjs, python)', async () => {
  const work = tmp('preflight'), root = repository('preflight-repo');
  const { assertPublisherIdentityAndAuth } = await import(pathToFileURL(path.join(source, 'scripts/bd-publisher-setup.mjs')).href);
  const operator = overrideFile(work, [['unknown', 'credential.helper', 'osxkeychain'], ['global', 'credential.https://github.com.helper', ''],
    ['global', 'credential.https://github.com.helper', '!/opt/homebrew/bin/gh auth git-credential'],
    ['global', 'user.name', 'Operator'], ['global', 'user.email', 'operator@example.invalid']]);
  const resetOnly = overrideFile(work, [['global', 'credential.https://example.com.helper', ''],
    ['global', 'user.name', 'Operator'], ['global', 'user.email', 'operator@example.invalid']]);
  const noIdentity = overrideFile(work, [['unknown', 'credential.helper', 'osxkeychain']]);
  const scenarios = [
    { file: operator, push: ['https://github.com/komleff/overgate.git', 'https://gitlab.com/x/y.git'], expect: null },
    { file: resetOnly, push: ['https://example.com/x/y.git'], expect: /HTTPS authentication unavailable/ },
    { file: noIdentity, push: ['https://github.com/o/r.git'], expect: /identity/ },
  ];
  const prior = process.env;
  for (const scenario of scenarios) {
    process.env = baseEnv({ [OVERRIDE]: scenario.file, GIT_CONFIG_NOSYSTEM: '1' });
    try {
      gitEnvironment.disposeNetworkGitEnvironment();
      if (scenario.expect) assert.throws(() => assertPublisherIdentityAndAuth(root, { push: scenario.push }), scenario.expect);
      else assert.doesNotThrow(() => assertPublisherIdentityAndAuth(root, { push: scenario.push }));
    } finally { process.env = prior; gitEnvironment.disposeNetworkGitEnvironment(); }
    const script = `
import importlib.util,sys
spec=importlib.util.spec_from_file_location('activation',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
try:m.publisher_identity_auth(m.Path(sys.argv[2]),sys.argv[3])
except (m.ActivationError,m.installer.InstallError) as error:print('STOP: '+str(error));sys.exit(1)
print('OK')
`;
    const run = spawnSync(python, ['-I', '-c', script, activationPath, root, scenario.push.join('\n')],
      { env: baseEnv({ [OVERRIDE]: scenario.file, GIT_CONFIG_NOSYSTEM: '1' }), encoding: 'utf8' });
    if (scenario.expect) { assert.equal(run.status, 1, run.stdout + run.stderr); assert.match(run.stdout, scenario.expect); }
    else assert.equal(run.status, 0, run.stdout + run.stderr);
  }
});

function waitLine(child) {
  return new Promise((resolve, reject) => {
    let buffer = '';
    child.stdout.on('data', chunk => { buffer += chunk; const at = buffer.indexOf('\n'); if (at >= 0) resolve(buffer.slice(0, at)); });
    child.on('exit', code => reject(new Error(`child exited ${code} before ready: ${buffer}`)));
  });
}
const exited = child => new Promise(resolve => child.on('exit', (code, signal) => resolve({ code, signal })));
const netDirectories = directory => fs.readdirSync(directory).filter(name => name.startsWith('overgate-git-net'));

test('B-07 lifecycle (mjs, python): lazy, private, removed after success, error, SIGINT and SIGTERM', async () => {
  const root = repository('life-repo'), work = tmp('life');
  const override = overrideFile(work, [['global', 'credential.helper', `!${SECRET}`]]);
  const mjs = path.join(work, 'child.mjs'), py = path.join(work, 'child.py');
  fs.writeFileSync(mjs, `
import fs from 'node:fs'; import path from 'node:path';
const [mode, root] = process.argv.slice(2);
const { networkGitEnvironment } = await import(${JSON.stringify(moduleUrl)});
const before = fs.readdirSync(process.env.TMPDIR).filter(name => name.startsWith('overgate-git-net')).length;
const file = networkGitEnvironment(root).GIT_CONFIG_GLOBAL;
console.log(JSON.stringify({ before, file, directoryMode: fs.statSync(path.dirname(file)).mode & 0o777, fileMode: fs.statSync(file).mode & 0o777 }));
if (mode === 'error') throw new Error('route failure');
if (mode === 'wait') setInterval(() => {}, 1000);
if (mode === 'child-signal') {
  // Сетевой child убит Ctrl-C группы: процесс завершается сразу, не продолжая синхронный маршрут.
  const { spawnSync } = await import('node:child_process');
  const { exitOnNetworkSignal } = await import(${JSON.stringify(moduleUrl)});
  exitOnNetworkSignal({ signal: spawnSync('sh', ['-c', 'kill -INT $$']).signal });
  console.log('CONTINUED-AFTER-SIGNAL');
}
`);
  fs.writeFileSync(py, `
import importlib.util,json,os,sys,time
spec=importlib.util.spec_from_file_location('installer',${JSON.stringify(installerPath)});m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
mode,root=sys.argv[1:3]
before=len([n for n in os.listdir(os.environ['TMPDIR']) if n.startswith('overgate-git-net')])
file=m.network_git_environment(root)['GIT_CONFIG_GLOBAL']
print(json.dumps({'before':before,'file':file,'directoryMode':os.stat(os.path.dirname(file)).st_mode&0o777,'fileMode':os.stat(file).st_mode&0o777}),flush=True)
if mode=='error':raise RuntimeError('route failure')
while mode=='wait':time.sleep(0.1)
`);
  for (const language of ['mjs', 'python']) {
    for (const mode of ['ok', 'error', 'SIGINT', 'SIGTERM', ...(language === 'mjs' ? ['child-signal'] : [])]) {
      const temporary = tmp(`life-${language}-${mode}`);
      const env = baseEnv({ TMPDIR: temporary, [OVERRIDE]: override });
      const args = language === 'mjs' ? [process.execPath, [mjs]] : [python, ['-I', py]];
      const child = spawn(args[0], [...args[1], mode.startsWith('SIG') ? 'wait' : mode, root], { env, stdio: ['ignore', 'pipe', 'pipe'] });
      let stderr = '', stdout = ''; child.stderr.on('data', chunk => { stderr += chunk; }); child.stdout.on('data', chunk => { stdout += chunk; });
      const done = exited(child);
      const info = JSON.parse(await waitLine(child));
      assert.equal(info.before, 0, `${language} ${mode}: lazy creation`);
      assert.equal(info.directoryMode, 0o700); assert.equal(info.fileMode, 0o600);
      assert.ok(info.file.startsWith(temporary + path.sep) && !info.file.startsWith(source), `${language}: private file outside repo`);
      if (mode.startsWith('SIG')) child.kill(mode);
      const result = await done;
      if (mode === 'ok') assert.equal(result.code, 0, stderr);
      if (mode === 'error') assert.notEqual(result.code, 0);
      if (mode === 'SIGINT') assert.ok(result.code === 130 || result.signal === 'SIGINT', `${language} SIGINT ${JSON.stringify(result)}`);
      if (mode === 'SIGTERM') assert.ok(result.code === 143 || result.signal === 'SIGTERM', `${language} SIGTERM ${JSON.stringify(result)}`);
      if (mode === 'child-signal') {
        assert.equal(result.signal, 'SIGINT', `${language} child-signal ${JSON.stringify(result)}`);
        assert.doesNotMatch(stdout, /CONTINUED-AFTER-SIGNAL/, 'route must stop immediately');
      }
      assert.equal(fs.existsSync(info.file), false, `${language} ${mode}: file removed`);
      assert.deepEqual(netDirectories(temporary), [], `${language} ${mode}: no leftover directory`);
      assert.ok(!stderr.includes(SECRET), `${language} ${mode}: value leaked`);
    }
  }
});

test('B-07 lifecycle (shell): trap chain, subshell lifetime, removal before exec, INT/TERM', async () => {
  const root = repository('shell-life-repo'), work = tmp('shell-life');
  const override = overrideFile(work, [['global', 'credential.helper', '!fixture-helper']]);
  const script = path.join(work, 'route.sh');
  fs.writeFileSync(script, `set -euo pipefail
. "$OG_SOURCE/scripts/lib/bd-env.sh"
bd_env_sanitize_git
trap 'echo own-exit >> "$OG_LOG"' EXIT
mode="$1"; root="$2"
case "$mode" in
  subshell)
    listing="$(bd_env_network_git "$root" config --global --show-origin --list)"
    file="\${listing#file:}"; file="\${file%%$'\\t'*}"
    echo "SUBFILE=$file"; [ -e "$file" ] && echo SUBFILE-EXISTS
    echo "PARENT=[$BD_ENV_NETWORK_CONFIG]"
    exit 0 ;;
esac
bd_env_network_git "$root" config --global --list >/dev/null
echo "FILE=$BD_ENV_NETWORK_CONFIG"
case "$mode" in
  ok) exit 0 ;;
  error) false ;;
  exec) bd_env_network_cleanup; exec env ;;
  wait) while :; do sleep 0.1; done ;;
esac
`);
  for (const mode of ['ok', 'error', 'exec', 'subshell', 'SIGINT', 'SIGTERM']) {
    const temporary = tmp(`shell-${mode}`), log = path.join(temporary, 'own.log');
    const env = baseEnv({ TMPDIR: temporary, [OVERRIDE]: override, OG_SOURCE: source, OG_LOG: log });
    const child = spawn('bash', [script, mode.startsWith('SIG') ? 'wait' : mode, root], { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
    let finished = false;
    const done = exited(child).then(result => { finished = true; return result; });
    if (mode.startsWith('SIG')) {
      while (!stdout.includes('FILE=') && !finished) await new Promise(resolve => setTimeout(resolve, 20));
      assert.ok(!finished, `shell ${mode}: route ended before signal: ${stderr}`);
      const file = /FILE=(.*)/.exec(stdout)[1];
      assert.equal(fs.statSync(file).mode & 0o777, 0o600); assert.equal(fs.statSync(path.dirname(file)).mode & 0o777, 0o700);
      child.kill(mode);
    }
    const result = await done;
    if (mode === 'ok' || mode === 'exec' || mode === 'subshell') assert.equal(result.code, 0, stderr);
    if (mode === 'error') assert.notEqual(result.code, 0);
    if (mode === 'SIGINT') assert.equal(result.code, 130, JSON.stringify(result));
    if (mode === 'SIGTERM') assert.equal(result.code, 143, JSON.stringify(result));
    assert.deepEqual(netDirectories(temporary), [], `shell ${mode}: no leftover directory`);
    if (mode !== 'exec') assert.match(fs.readFileSync(log, 'utf8'), /own-exit/, `shell ${mode}: existing EXIT trap still runs`);
    if (mode === 'exec') assert.doesNotMatch(stdout.split('FILE=')[1] || '', /GIT_CONFIG_GLOBAL=.*overgate-git-net/, 'exec env without network file');
    if (mode === 'subshell') {
      assert.match(stdout, /SUBFILE=.*overgate-git-net/); assert.doesNotMatch(stdout, /SUBFILE-EXISTS/);
      assert.match(stdout, /PARENT=\[\]/, 'subshell state does not leak to parent');
    }
  }
});

// Локальный HTTP remote, который требует вход и записывает присланные учётные данные.
async function authRemote() {
  const work = tmp('http'), log = path.join(work, 'auth.log'), server = path.join(work, 'server.mjs');
  fs.writeFileSync(log, '');
  fs.writeFileSync(server, `import http from 'node:http'; import fs from 'node:fs';
const server = http.createServer((request, response) => {
  const auth = request.headers.authorization || '';
  fs.appendFileSync(process.argv[2], (auth.startsWith('Basic ') ? Buffer.from(auth.slice(6), 'base64').toString() : '-') + ' ' + request.url + '\\n');
  response.writeHead(401, { 'WWW-Authenticate': 'Basic realm="og4py"' }); response.end('auth required');
});
server.listen(0, '127.0.0.1', () => process.stdout.write(server.address().port + '\\n'));
`);
  const child = spawn(process.execPath, [server, log], { stdio: ['ignore', 'pipe', 'inherit'] });
  const port = await waitLine(child);
  return { url: `http://127.0.0.1:${port}/project.git`, log, close: () => child.kill('SIGTERM') };
}
const credentialHelper = "!f() { echo username=fixture; echo password=synthetic; }; f";

function stubBin(work) {
  const bin = path.join(work, 'bin'); fs.mkdirSync(bin, { recursive: true });
  fs.writeFileSync(path.join(bin, 'bd'), '#!/usr/bin/env bash\ncase "$1" in where) exit 0;; export) while [ $# -gt 0 ]; do [ "$1" = -o ] && : > "$2"; shift; done; exit 0;; *) exit 0;; esac\n', { mode: 0o755 });
  return bin;
}

test('B-01/B-02: route network calls present the user helper credentials; without helper fail closed with no prompt', async () => {
  const remote = await authRemote();
  try {
    const work = tmp('routes'), bin = stubBin(work);
    const withHelper = overrideFile(work, [['unknown', 'credential.helper', credentialHelper], ['global', 'user.name', 'G'], ['global', 'user.email', 'g@example.invalid']]);
    const without = overrideFile(work, [['global', 'user.name', 'G'], ['global', 'user.email', 'g@example.invalid']]);
    const legacy = repository('route-legacy', remote.url);
    git(legacy, ...FIXTURE_IDENTITY, 'commit', '-q', '--allow-empty', '-m', 'init');
    registerPrefix(legacy);
    const routes = {
      'bd-read fetch': [legacy, 'bash', [path.join(source, 'scripts/bd-read.sh'), 'list']],
      'bd-sync-export': [legacy, 'bash', [path.join(source, 'scripts/bd-sync-export.sh')]],
      'bd-sync-restore': [legacy, 'bash', [path.join(source, 'scripts/bd-sync-restore.sh')]],
      'bd-wt remote mode': [legacy, 'bash', [path.join(source, 'scripts/bd-wt.sh'), 'list']],
      'ManagedGit readPublished': [legacy, process.execPath, ['--input-type=module', '-e',
        `const { ManagedGit } = await import(${JSON.stringify(pathToFileURL(path.join(source, 'scripts/lib/bd-managed-git.mjs')).href)}); new ManagedGit({ cwd: process.cwd(), readIssuePrefix: () => 'og' }).readPublished();`]],
      'installer beads_inventory': [legacy, python, ['-I', '-c', `import importlib.util,sys,json
spec=importlib.util.spec_from_file_location('i',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
print(json.dumps(m.beads_inventory(m.Path(sys.argv[2]))['remote']))`, installerPath, legacy]],
    };
    for (const [name, [cwd, command, args]] of Object.entries(routes)) {
      for (const [label, file] of [['helper', withHelper], ['no helper', without]]) {
        fs.writeFileSync(remote.log, '');
        const run = spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 60000,
          env: baseEnv({ [OVERRIDE]: file, GIT_CONFIG_NOSYSTEM: '1', PATH: `${bin}${path.delimiter}${process.env.PATH}`, BD_BIN: path.join(bin, 'bd') }) });
        assert.notEqual(run.error?.code, 'ETIMEDOUT', `${name} ${label}: must not wait for a prompt`);
        const seen = fs.readFileSync(remote.log, 'utf8');
        if (label === 'helper') assert.match(seen, /^fixture:synthetic /m, `${name}: helper credentials reached remote\n${run.stderr}`);
        else {
          assert.doesNotMatch(seen, /fixture:synthetic/, `${name}: no credentials without helper`);
          assert.match(seen, /^- /m, `${name}: request reached remote`);
          assert.match(run.stdout + run.stderr, /terminal prompts disabled|could not read Username|unavailable|unknown|fail-closed/i, `${name}: fail-closed diagnostic`);
        }
      }
    }
  } finally { remote.close(); }
});

test('diagnostic mode (shell/mjs/python): keys and scope without values, probe in route environment', async () => {
  const remote = await authRemote();
  try {
    const work = tmp('diagnose'), bare = path.join(work, 'remote.git');
    git(work, 'init', '-q', '--bare', bare);
    const root = repository('diagnose-repo', bare);
    git(root, ...FIXTURE_IDENTITY, 'commit', '-q', '--allow-empty', '-m', 'init');
    const override = overrideFile(work, [['unknown', 'credential.helper', `!${SECRET}`], ['global', 'user.email', `${SECRET}@example.invalid`]]);
    const commands = {
      shell: probe => ['bash', [path.join(source, 'scripts/lib/bd-env.sh'), '--diagnose', probe]],
      mjs: probe => [process.execPath, [path.join(source, 'scripts/lib/bd-git-environment.mjs'), '--diagnose', '--probe', probe]],
      python: probe => [python, ['-I', installerPath, 'network-diagnose', '--probe', probe]],
    };
    const home = path.join(work, 'home');
    fs.mkdirSync(home);
    fs.writeFileSync(path.join(home, '.gitconfig'), `[http]\n\tproxy = http://user:${SECRET}@proxy.invalid\n[url "git@example.invalid:"]\n\tinsteadOf = https://example.invalid/\n[user]\n\temail = ${SECRET}@example.invalid\n`);
    for (const [language, command] of Object.entries(commands)) {
      const [plainBinary, plainArgs] = command('ls-remote');
      const residual = spawnSync(plainBinary, plainArgs.slice(0, language === 'shell' ? 2 : language === 'mjs' ? 2 : 3), { cwd: root,
        env: baseEnv({ HOME: home, XDG_CONFIG_HOME: path.join(home, '.config') }), encoding: 'utf8' });
      assert.equal(residual.status, 0, `${language}: ${residual.stderr}`);
      assert.match(residual.stdout, /residual: global http\.proxy/, `${language}: residual http.* named`);
      assert.match(residual.stdout, /residual: global url\.git@example\.invalid:\.insteadof/, `${language}: residual insteadOf named`);
      assert.match(residual.stdout, /carried: global user\.email/);
      assert.ok(!(residual.stdout + residual.stderr).includes(SECRET), `${language}: residual value leaked`);
      git(root, 'remote', 'set-url', 'origin', bare);
      let [binary, args] = command('ls-remote');
      let run = spawnSync(binary, args, { cwd: root, env: baseEnv({ [OVERRIDE]: override, GIT_CONFIG_NOSYSTEM: '1' }), encoding: 'utf8' });
      assert.equal(run.status, 0, `${language}: ${run.stderr}`);
      assert.match(run.stdout, /carried: unknown credential\.helper/);
      assert.match(run.stdout, /carried: global user\.email/);
      assert.match(run.stdout, /probe: ls-remote exit=0 result=ok/);
      assert.ok(!(run.stdout + run.stderr).includes(SECRET), `${language}: diagnostic leaked a value`);
      git(root, 'remote', 'set-url', 'origin', remote.url);
      [binary, args] = command('push-dry-run');
      run = spawnSync(binary, args, { cwd: root, env: baseEnv({ [OVERRIDE]: overrideFile(work, []) }), encoding: 'utf8', timeout: 60000 });
      assert.match(run.stdout, /carried: <none>/, `${language}: ${run.stderr}`);
      assert.match(run.stdout, /probe: push-dry-run exit=\d+ result=auth-unavailable/, `${language}: ${run.stdout}${run.stderr}`);
    }
  } finally { remote.close(); }
});

test('residual: failed network call names non-carried user keys without values (shell/mjs/python)', () => {
  const work = tmp('residual'), root = repository('residual-repo', path.join(work, 'missing-remote.git'));
  const home = path.join(work, 'home');
  fs.mkdirSync(home);
  fs.writeFileSync(path.join(home, '.gitconfig'), `[http]\n\tproxy = http://user:${SECRET}@proxy.invalid\n[core]\n\tsshCommand = ssh -i /secret/${SECRET}\n`);
  const env = baseEnv({ HOME: home, XDG_CONFIG_HOME: path.join(home, '.config') });
  const runs = {
    shell: spawnSync('bash', ['-c', '. "$1/scripts/lib/bd-env.sh"; bd_env_sanitize_git; bd_env_network_git "$2" fetch -q origin', '_', source, root], { cwd: root, env, encoding: 'utf8' }),
    mjs: spawnSync(process.execPath, ['--input-type=module', '-e', `const { ManagedGit } = await import(process.argv[1]);
const repository = Object.create(ManagedGit.prototype); repository.cwd = process.argv[2]; repository.git = 'git';
try { repository.call(['fetch', '-q', 'origin'], { network: true }); } catch (error) { console.error(error.message); process.exit(1); }`,
    pathToFileURL(path.join(source, 'scripts/lib/bd-managed-git.mjs')).href, root], { cwd: root, env, encoding: 'utf8' }),
    python: spawnSync(python, ['-I', '-c', `import importlib.util,sys
spec=importlib.util.spec_from_file_location('i',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
try:m.net_git(sys.argv[2],'fetch','-q','origin')
except m.InstallError as error:print(error,file=sys.stderr);sys.exit(1)`, installerPath, root], { cwd: root, env, encoding: 'utf8' }),
  };
  for (const [language, run] of Object.entries(runs)) {
    assert.notEqual(run.status, 0, language);
    assert.match(run.stderr, /http\.proxy \(global\)/, `${language}: residual key named\n${run.stderr}`);
    assert.match(run.stderr, /core\.sshcommand \(global\)/, `${language}: residual key named`);
    assert.match(run.stderr, /og-4py residual/, language);
    assert.ok(!run.stderr.includes(SECRET), `${language}: residual value leaked`);
  }
});

// Обёртка git, фиксирующая окружение каждого вызова: сетевые ли команды видят helper-маркер
// и сколько файлов переноса существует в момент вызова.
function probeGit(work) {
  const bin = path.join(work, 'probe-bin'), log = path.join(work, 'git-calls.log');
  fs.mkdirSync(bin, { recursive: true }); fs.writeFileSync(log, '');
  fs.writeFileSync(path.join(bin, 'git'), `#!/usr/bin/env bash
args=("$@"); i=0
while [ "$i" -lt "\${#args[@]}" ]; do case "\${args[$i]}" in -C|-c) i=$((i+2)) ;; --*) i=$((i+1)) ;; *) break ;; esac; done
sub="\${args[$i]:-}"
marker=no
if [ -n "\${GIT_CONFIG_GLOBAL:-}" ] && [ -f "\${GIT_CONFIG_GLOBAL}" ] && grep -q OGMARKER "\${GIT_CONFIG_GLOBAL}" 2>/dev/null; then marker=yes; fi
nets=$(ls -d "$TMPDIR"/overgate-git-net* 2>/dev/null | wc -l | tr -d ' ')
parent=$(ps -o args= -p "$PPID" 2>/dev/null | tr '\\t\\n' '  ')
printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "$parent" "$sub" "\${GIT_CONFIG_GLOBAL:-<unset>}" "$marker" "$nets" >> '${log}'
exec '${realGit}' "$@"
`, { mode: 0o755 });
  return { bin, log, calls: () => fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).map(line => {
    const [parent, sub, global, marker, nets] = line.split('\t'); return { parent, sub, global, marker, nets: Number(nets) }; }) };
}
const NETWORK = new Set(['ls-remote', 'fetch', 'push', 'commit-tree']);
function assertIsolation(calls, label) {
  assert.ok(calls.some(call => NETWORK.has(call.sub)), `${label}: route made network calls`);
  for (const call of calls) {
    if (NETWORK.has(call.sub)) assert.equal(call.marker, 'yes', `${label}: ${call.sub} must see the carried helper`);
    else if (call.sub !== 'config') assert.ok(['/dev/null', 'NUL'].includes(call.global), `${label}: ${call.sub} must stay isolated (${call.global})`);
  }
}

test('B-09 chains: parent with GIT_CONFIG_NOSYSTEM=1 and unknown-scope helper; child network calls see it; file not passed through exec', () => {
  const work = tmp('chains'), probe = probeGit(work), bin = stubBin(work);
  const override = overrideFile(work, [['unknown', 'credential.helper', '!OGMARKER-helper'], ['system', 'user.name', 'S'], ['system', 'user.email', 's@example.invalid']]);
  const bare = path.join(work, 'remote.git');
  git(work, 'init', '-q', '--bare', bare);
  const seed = path.join(work, 'seed');
  git(work, 'init', '-q', '-b', 'main', seed);
  git(seed, 'config', 'user.name', 'fixture'); git(seed, 'config', 'user.email', 'fixture@example.invalid');
  const files = ['scripts/bd-apply-intents.sh', 'scripts/bd-read.sh', 'scripts/bd-wt.sh', 'scripts/lib/bd-env.sh', 'scripts/lib/bd-read-engine.mjs',
    'scripts/lib/bd-managed-read-check.mjs', ...fs.readdirSync(path.join(source, 'scripts/lib')).filter(name => /^bd-(managed-|snapshot|git-environment)/.test(name)).map(name => `scripts/lib/${name}`)];
  for (const name of new Set(files)) { const target = path.join(seed, name); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.copyFileSync(path.join(source, name), target); }
  git(seed, 'add', '-A'); git(seed, 'commit', '-q', '-m', 'trusted helper');
  git(seed, 'remote', 'add', 'origin', bare); git(seed, 'push', '-q', 'origin', 'main');
  registerPrefix(seed);
  // Remote snapshot с managed marker: bd-wt выбирает managed route и делает exec bd-read.sh.
  const index = path.join(work, 'index');
  const blob = execFileSync('git', ['hash-object', '-w', '--stdin'], { cwd: seed, env: fixtureEnv, input: '{"version":1}\n' }).toString().trim();
  execFileSync('git', ['update-index', '--add', '--cacheinfo', `100644,${blob},.beads/overgate-managed-v1.json`], { cwd: seed, env: { ...fixtureEnv, GIT_INDEX_FILE: index } });
  const tree = execFileSync('git', ['write-tree'], { cwd: seed, env: { ...fixtureEnv, GIT_INDEX_FILE: index } }).toString().trim();
  const commit = git(seed, 'commit-tree', tree, '-m', 'managed marker');
  git(seed, 'push', '-q', 'origin', `${commit}:refs/heads/beads-backup`);
  const env = extra => baseEnv({ [OVERRIDE]: override, GIT_CONFIG_NOSYSTEM: '1', TMPDIR: tmp('chain-tmp'),
    PATH: `${probe.bin}${path.delimiter}${bin}${path.delimiter}${process.env.PATH}`, BD_BIN: path.join(bin, 'bd'), ...extra });
  // bd-wt → bd-read (exec).
  fs.writeFileSync(probe.log, '');
  spawnSync('bash', ['scripts/bd-wt.sh', 'list'], { cwd: seed, env: env(), encoding: 'utf8' });
  let calls = probe.calls();
  assertIsolation(calls, 'bd-wt → bd-read');
  const readerCalls = calls.filter(call => call.parent.includes('bd-read.sh'));
  assert.ok(calls.some(call => call.sub === 'fetch' && call.parent.includes('bd-wt.sh')), 'bd-wt remote mode fetched');
  assert.ok(readerCalls.some(call => call.sub === 'fetch' && call.marker === 'yes'), 'exec bd-read.sh fetched with helper');
  assert.equal(readerCalls[0].nets, 0, 'bd-wt network file removed before exec bd-read.sh');
  // bd-apply-intents → node (exec).
  git(seed, 'push', '-q', 'origin', '--delete', 'beads-backup');
  fs.writeFileSync(probe.log, '');
  const apply = spawnSync('bash', ['scripts/bd-apply-intents.sh', '--read-state'], { cwd: seed, env: env(), encoding: 'utf8' });
  assert.equal(apply.status, 0, apply.stderr);
  calls = probe.calls();
  assertIsolation(calls, 'bd-apply-intents → node');
  assert.ok(calls.some(call => call.sub === 'ls-remote' && call.parent.includes('bd-apply-intents.sh')), 'shell trusted main ls-remote');
  const nodeCalls = calls.filter(call => call.parent.includes('bd-managed-entry.mjs'));
  assert.ok(nodeCalls.length > 0 && nodeCalls[0].nets === 0, 'shell network file removed before exec node');
  assert.ok(nodeCalls.some(call => call.sub === 'ls-remote' && call.marker === 'yes'), 'node child sees helper');
});
