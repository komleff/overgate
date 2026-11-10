// Git trust checks and publication must not inherit caller-supplied repository,
// remote, URL rewrite, config, hook or object namespace overrides.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function cleanGitEnvironment(source = process.env) {
  const env = {};
  for (const [name, value] of Object.entries(source)) {
    if (name.startsWith('GIT_') && !/^(GIT_AUTHOR|GIT_COMMITTER)_(NAME|EMAIL|DATE)$/.test(name)) continue;
    env[name] = value;
  }
  env.GIT_CONFIG_GLOBAL = process.platform === 'win32' ? 'NUL' : '/dev/null';
  env.GIT_CONFIG_NOSYSTEM = '1';
  env.GIT_TERMINAL_PROMPT = '0';
  env.MSYS2_ARG_CONV_EXCL = '*';
  return env;
}

export function cleanBeadsEnvironment(source = process.env) {
  const env = cleanGitEnvironment(source);
  for (const name of Object.keys(env)) if (/^(BEADS_|BD_|DOLT_|OTEL_)/.test(name)) delete env[name];
  return env;
}

// ---------------------------------------------------------------------------
// og-4py, ADR §3.39: сетевые вызовы Git (ls-remote/fetch/push) и commit-tree снимка
// получают перенос allowlist пользовательского config. Чистая изоляция выше не меняется.
// Спецификация общая для shell (bd-env.sh), mjs и python (install-overgate.py).
export const USER_CONFIG_OVERRIDE = 'OVERGATE_GIT_USER_CONFIG_FILE';
export const USER_CONFIG_PATTERN = '^(credential\\..+|user\\.name|user\\.email)$';
// Residual: не переносится; в диагностике печатаются только имена ключей и scope.
export const RESIDUAL_CONFIG_PATTERN = '^(http\\..+|url\\..+\\.(insteadof|pushinsteadof)|core\\.sshcommand|author\\..+|committer\\..+|commit\\.gpgsign|gpg\\..+)$';
const ALLOWED_KEY = /^(credential\..+|user\.name|user\.email)$/;
const KEY_SHAPE = /^[A-Za-z0-9-]+(\..*)?\.[A-Za-z][A-Za-z0-9-]*$/;
const SCOPES = new Set(['system', 'global', 'local', 'worktree', 'command', 'unknown']);
const CARRIED_SCOPES = new Set(['system', 'global', 'unknown']);
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };

// Ключ печатается без userinfo URL: в subsection может оказаться токен.
export function redactKey(key) {
  return String(key).replace(/(:\/\/)[^/@]*@/g, '$1<userinfo>@');
}

function withoutGitVariables(source) {
  const env = {};
  for (const [name, value] of Object.entries(source)) if (!name.startsWith('GIT_')) env[name] = value;
  env.GIT_TERMINAL_PROMPT = '0';
  env.MSYS2_ARG_CONV_EXCL = '*';
  return env;
}

// Формат: scope\0key\nvalue\0 (git config --show-scope -z). Ключ без значения — key\0.
export function parseUserGitConfig(raw) {
  requireThat(Buffer.isBuffer(raw), 'user Git config must be bytes');
  if (raw.length === 0) return [];
  requireThat(raw.at(-1) === 0, 'user Git config framing invalid (fail-closed)');
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let fields;
  try { fields = decoder.decode(raw.subarray(0, raw.length - 1)).split('\0'); }
  catch { throw new Error('user Git config encoding invalid (fail-closed)'); }
  requireThat(fields.length % 2 === 0, 'user Git config framing invalid (fail-closed)');
  const entries = [];
  for (let index = 0; index < fields.length; index += 2) {
    const scope = fields[index], record = fields[index + 1];
    requireThat(SCOPES.has(scope), 'user Git config scope invalid (fail-closed)');
    const separator = record.indexOf('\n');
    const key = separator < 0 ? record : record.slice(0, separator);
    requireThat(KEY_SHAPE.test(key), 'user Git config key framing invalid (fail-closed)');
    entries.push({ scope, key, value: separator < 0 ? null : record.slice(separator + 1) });
  }
  return entries;
}

function readerOutput(root, source, pattern, extra = []) {
  if (Object.hasOwn(source, USER_CONFIG_OVERRIDE)) {
    try { return fs.readFileSync(source[USER_CONFIG_OVERRIDE]); }
    catch { throw new Error(`${USER_CONFIG_OVERRIDE} is set but unreadable (fail-closed)`); }
  }
  // Без GIT_CONFIG_NOSYSTEM и прочих caller GIT_*: иначе теряются scope system/unknown.
  const run = spawnSync('git', ['config', ...extra, '--show-scope', '--includes', '-z', '--get-regexp', pattern],
    { cwd: root, env: withoutGitVariables(source), maxBuffer: 4 * 1024 * 1024, timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] });
  if (run.error) throw new Error('user Git config reader unavailable (fail-closed)');
  if (run.status === 1) return Buffer.alloc(0);
  requireThat(run.status === 0, `user Git config reader failed (exit ${run.status}); Git >= 2.26 with --show-scope is required (fail-closed)`);
  return run.stdout;
}

export function readUserGitConfig(root, source = process.env) {
  return parseUserGitConfig(readerOutput(root, source, USER_CONFIG_PATTERN))
    .filter(entry => CARRIED_SCOPES.has(entry.scope) && ALLOWED_KEY.test(entry.key));
}

// Только имена и scope residual-ключей; значения не читаются (--name-only).
export function residualUserGitKeys(root, source = process.env) {
  if (Object.hasOwn(source, USER_CONFIG_OVERRIDE)) return [];
  let raw;
  try { raw = readerOutput(root, source, RESIDUAL_CONFIG_PATTERN, ['--name-only']); } catch { return []; }
  const fields = raw.toString('utf8').split('\0');
  if (fields.at(-1) === '') fields.pop();
  const result = [];
  for (let index = 0; index + 1 < fields.length; index += 2)
    if (CARRIED_SCOPES.has(fields[index])) result.push({ scope: fields[index], key: fields[index + 1] });
  return result;
}

export function residualHint(root, source = process.env) {
  const keys = residualUserGitKeys(root, source);
  if (!keys.length) return '';
  return `; user Git config keys not carried into the Beads network route: ${keys.map(item => `${redactKey(item.key)} (${item.scope})`).join(', ')}`
    + ' — og-4py residual (ADR §3.39); diagnose: node scripts/lib/bd-git-environment.mjs --diagnose --probe ls-remote';
}

const networkState = new Map();
let handlersInstalled = false;

export function disposeNetworkGitEnvironment() {
  for (const { directory } of networkState.values()) {
    try { fs.rmSync(directory, { recursive: true, force: true }); } catch { /* best effort при выходе */ }
  }
  networkState.clear();
}

const signalHandlers = new Map();
function installNetworkHandlers() {
  if (handlersInstalled) return;
  handlersInstalled = true;
  process.on('exit', disposeNetworkGitEnvironment);
  for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
    const handler = () => { disposeNetworkGitEnvironment(); process.exit(code); };
    signalHandlers.set(signal, handler);
    process.on(signal, handler);
  }
}

// Синхронный код не отдаёт управление обработчику сигнала до конца стека. Если сетевой
// child убит SIGINT/SIGTERM (Ctrl-C группы процессов), файл удаляется и процесс сразу
// завершается тем же сигналом, не продолжая маршрут.
export function exitOnNetworkSignal(error) {
  const signal = error?.signal;
  if (signal !== 'SIGINT' && signal !== 'SIGTERM') return;
  disposeNetworkGitEnvironment();
  for (const [name, handler] of signalHandlers) process.removeListener(name, handler);
  process.kill(process.pid, signal);
}

// Каждая запись — собственная секция в порядке вывода reader. `git config --add` не подходит:
// он дописывает ключ в уже существующую одноимённую секцию и меняет порядок списка helper.
// Ключ без значения пишется без `=` (как в исходнике: boolean true / ошибка git для строк).
const CONFIG_ESCAPES = { '\\': '\\\\', '"': '\\"', '\n': '\\n', '\t': '\\t', '\b': '\\b' };
export function carriedConfigBytes(entries) {
  let text = '', expected = '';
  for (const { key, value } of entries) {
    const first = key.indexOf('.'), last = key.lastIndexOf('.');
    const section = key.slice(0, first), variable = key.slice(last + 1);
    const subsection = first === last ? null : key.slice(first + 1, last);
    const residue = value === null ? '' : value.replace(/[\n\t\b]/g, '');
    requireThat(!/[\x00-\x1f\x7f]/.test(residue) && !/[\x00\n]/.test(subsection ?? ''),
      `user Git config value/key unsupported for transfer: ${redactKey(key)} (fail-closed)`);
    text += subsection === null ? `[${section}]\n` : `[${section} "${subsection.replace(/[\\"]/g, character => CONFIG_ESCAPES[character])}"]\n`;
    text += value === null ? `\t${variable}\n` : `\t${variable} = "${value.replace(/[\\"\n\t\b]/g, character => CONFIG_ESCAPES[character])}"\n`;
    const canonical = `${section.toLowerCase()}${subsection === null ? '' : '.' + subsection}.${variable.toLowerCase()}`;
    expected += value === null ? `${canonical}\0` : `${canonical}\n${value}\0`;
  }
  return { text, expected };
}

function writeCarriedConfig(file, entries, source) {
  const { text, expected } = carriedConfigBytes(entries);
  fs.writeFileSync(file, text, { mode: 0o600 });
  // Read-back тем же git: перенос побайтно совпадает с записями reader.
  const run = spawnSync('git', ['config', '--file', file, '-z', '--list'],
    { env: cleanGitEnvironment(source), stdio: ['ignore', 'pipe', 'ignore'], timeout: 30000, maxBuffer: 4 * 1024 * 1024 });
  requireThat((run.status === 0 || (run.status === 1 && !text)) && (run.stdout ?? Buffer.alloc(0)).toString('utf8') === expected,
    'user Git config transfer read-back mismatch (fail-closed)');
}

// Окружение сетевого вызова: чистая изоляция + приватный временный GIT_CONFIG_GLOBAL.
// Файл создаётся лениво, один раз на процесс и корень; удаляется при выходе/сигнале.
export function networkGitEnvironment(root, source = process.env) {
  const resolved = path.resolve(root);
  let state = networkState.get(resolved);
  if (!state) {
    installNetworkHandlers();
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'overgate-git-net-'));
    state = { directory, file: path.join(directory, 'config') };
    networkState.set(resolved, state);
    try {
      fs.chmodSync(directory, 0o700);
      fs.writeFileSync(state.file, '', { mode: 0o600, flag: 'wx' });
      writeCarriedConfig(state.file, readUserGitConfig(resolved, source), source);
      fs.chmodSync(state.file, 0o600);
    } catch (error) {
      networkState.delete(resolved);
      fs.rmSync(directory, { recursive: true, force: true });
      throw error;
    }
  }
  return { ...cleanGitEnvironment(source), GIT_CONFIG_GLOBAL: state.file };
}

// --- Preflight: helper для URL по правилам git (urlmatch.c / credential.c).
const URL_UNSAFE = ' <>"%{}|\\^`';
const URL_RESERVED = ":/?#[]@!$&'()*+,;=";
const CREDENTIAL_UNSAFE = ' <>"%{}|\\^`:?#[]@';
const indexOfAny = (text, characters) => {
  for (let index = 0; index < text.length; index++) if (characters.includes(text[index])) return index;
  return text.length;
};
const hex = byte => '%' + byte.toString(16).toUpperCase().padStart(2, '0');

function percentDecode(text) {
  const bytes = [];
  const raw = Buffer.from(text, 'utf8');
  for (let index = 0; index < raw.length; index++) {
    if (raw[index] === 0x25 && index + 2 < raw.length + 0 && /^[0-9A-Fa-f]{2}$/.test(raw.subarray(index + 1, index + 3).toString('latin1'))) {
      bytes.push(parseInt(raw.subarray(index + 1, index + 3).toString('latin1'), 16)); index += 2;
    } else bytes.push(raw[index]);
  }
  return Buffer.from(bytes).toString('utf8');
}

function percentEncode(text, encodeSlash) {
  let out = '';
  for (const byte of Buffer.from(text, 'utf8')) {
    const character = String.fromCharCode(byte);
    out += byte <= 0x1f || byte >= 0x7f || (encodeSlash && character === '/') || CREDENTIAL_UNSAFE.includes(character) ? hex(byte) : character;
  }
  return out;
}

function normalizeEscapes(text) {
  let out = '';
  const raw = Buffer.from(text, 'utf8');
  for (let index = 0; index < raw.length; index++) {
    let byte = raw[index], escaped = false;
    if (byte === 0x25) {
      const digits = raw.subarray(index + 1, index + 3).toString('latin1');
      if (!/^[0-9A-Fa-f]{2}$/.test(digits)) return null;
      byte = parseInt(digits, 16); index += 2; escaped = true;
    }
    const character = String.fromCharCode(byte);
    out += byte <= 0x1f || byte >= 0x7f || URL_UNSAFE.includes(character) || (escaped && URL_RESERVED.includes(character)) ? hex(byte) : character;
  }
  return out;
}

export function normalizeUrl(url, allowGlobs = false) {
  const scheme = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.exec(url);
  if (!scheme) return null;
  const result = { scheme: scheme[0].slice(0, -3).toLowerCase(), user: null, host: '', port: '', path: '/' };
  let rest = url.slice(scheme[0].length);
  const at = rest.indexOf('@');
  if (at >= 0 && at < indexOfAny(rest, '/?#')) {
    const info = normalizeEscapes(rest.slice(0, at));
    if (info === null) return null;
    const colon = info.indexOf(':');
    result.user = colon < 0 ? info : info.slice(0, colon);
    rest = rest.slice(at + 1);
  }
  const end = indexOfAny(rest, '/?#');
  const authority = rest.slice(0, end);
  let host = authority, port = null;
  if (authority.startsWith('[')) {
    const close = authority.indexOf(']');
    if (close < 0) return null;
    host = authority.slice(0, close + 1);
    const tail = authority.slice(close + 1);
    if (tail) { if (!tail.startsWith(':')) return null; port = tail.slice(1); }
  } else {
    const colon = authority.indexOf(':');
    if (colon >= 0) { host = authority.slice(0, colon); port = authority.slice(colon + 1); }
  }
  if (!host) { if (result.scheme !== 'file') return null; }
  else if (!(allowGlobs ? /^[A-Za-z0-9.\-*[\]:]+$/ : /^[A-Za-z0-9.\-[\]:]+$/).test(host)) return null;
  result.host = host.toLowerCase();
  if (port !== null && port !== '') {
    if (!/^[0-9]+$/.test(port)) return null;
    const trimmed = port.replace(/^0+(?=.)/, '');
    if ((result.scheme === 'http' && trimmed === '80') || (result.scheme === 'https' && trimmed === '443')) result.port = '';
    else {
      const number = Number(trimmed);
      if (number < 1 || number > 65535) return null;
      result.port = trimmed;
    }
  }
  let pathPart = rest.slice(end);
  pathPart = pathPart.slice(0, indexOfAny(pathPart, '?#'));
  if (pathPart.startsWith('/')) pathPart = pathPart.slice(1);
  const segments = [];
  let trailing = false;
  for (const segment of pathPart === '' ? [] : pathPart.split('/')) {
    const normalized = normalizeEscapes(segment);
    if (normalized === null) return null;
    trailing = false;
    if (normalized === '.') trailing = true;
    else if (normalized === '..') { if (!segments.length) return null; segments.pop(); trailing = true; }
    else segments.push(normalized);
  }
  if (pathPart.endsWith('/') && pathPart !== '') trailing = true;
  result.path = '/' + segments.join('/') + (trailing && segments.length ? '/' : '');
  return result;
}

export function credentialFromUrl(url, partial = false) {
  const protocolEnd = url.indexOf('://');
  if (!partial && protocolEnd <= 0) return null;
  const tail = protocolEnd >= 0 ? url.slice(protocolEnd + 3) : url;
  const at = tail.indexOf('@'), colon = tail.indexOf(':'), slash = indexOfAny(tail, '/?#');
  const result = { protocol: protocolEnd > 0 ? url.slice(0, protocolEnd) : null, username: null, host: null, path: null };
  let host;
  if (at < 0 || slash <= at) host = tail.slice(0, slash);
  else if (colon < 0 || at <= colon) { result.username = percentDecode(tail.slice(0, at)); host = tail.slice(at + 1, slash); }
  else { result.username = percentDecode(tail.slice(0, colon)); host = tail.slice(at + 1, slash); }
  if (!partial || host.length > 0) result.host = percentDecode(host);
  let remainder = tail.slice(slash);
  while (remainder.startsWith('/')) remainder = remainder.slice(1);
  if (remainder) {
    let decoded = percentDecode(remainder);
    while (decoded.length > 1 && decoded.endsWith('/')) decoded = decoded.slice(0, -1);
    result.path = decoded;
  }
  return result;
}

function formatCredential(credential) {
  let out = `${credential.protocol}://`;
  if (credential.username) out += percentEncode(credential.username, true) + '@';
  if (credential.host) out += credential.host;
  if (credential.path) out += '/' + percentEncode(credential.path, false);
  return out;
}

function matchHost(host, pattern) {
  const hostParts = host.split('.'), patternParts = pattern.split('.');
  return hostParts.length === patternParts.length && patternParts.every((part, index) => part === '*' || part === hostParts[index]);
}

function matchPathPrefix(urlPath, prefixPath) {
  if (!prefixPath || prefixPath === '/') return true;
  const prefix = prefixPath.endsWith('/') ? prefixPath.slice(0, -1) : prefixPath;
  return urlPath.startsWith(prefix) && (urlPath.length === prefix.length || urlPath[prefix.length] === '/');
}

export function credentialPatternMatches(pattern, target, credential) {
  const prefix = normalizeUrl(pattern, true);
  if (prefix) {
    return target.scheme === prefix.scheme && (prefix.user === null || target.user === prefix.user)
      && matchHost(target.host, prefix.host) && target.port === prefix.port && matchPathPrefix(target.path, prefix.path);
  }
  const want = credentialFromUrl(pattern, true);
  return ['protocol', 'host', 'path', 'username'].every(field => want[field] === null || credential[field] === want[field]);
}

// Итоговый список helper для URL: порядок записей, url-match, сброс пустым значением.
export function credentialHelpersFromEntries(entries, url) {
  const credential = credentialFromUrl(url);
  if (!credential) return [];
  const target = normalizeUrl(formatCredential(credential));
  let helpers = [];
  for (const { key, value } of entries) {
    if (!key.startsWith('credential.')) continue;
    const rest = key.slice('credential.'.length), dot = rest.lastIndexOf('.');
    const variable = dot < 0 ? rest : rest.slice(dot + 1);
    if (variable.toLowerCase() !== 'helper') continue;
    if (dot >= 0 && (!target || !credentialPatternMatches(rest.slice(0, dot), target, credential))) continue;
    requireThat(value !== null, `valueless ${redactKey(key)} is invalid Git config (fail-closed)`);
    if (value === '') helpers = []; else helpers.push(value);
  }
  return helpers;
}

// Эффективный credential config так, как его видит git в окружении маршрута.
export function credentialHelpersFor(root, url, env) {
  const run = spawnSync('git', ['config', '-z', '--get-regexp', '^credential\\.'],
    { cwd: root, env, maxBuffer: 4 * 1024 * 1024, timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] });
  if (run.error) throw new Error('effective credential config unavailable (fail-closed)');
  if (run.status === 1) return [];
  requireThat(run.status === 0, `effective credential config unavailable (exit ${run.status}) (fail-closed)`);
  const records = run.stdout.toString('utf8').split('\0');
  if (records.at(-1) === '') records.pop();
  const entries = records.map(record => {
    const separator = record.indexOf('\n');
    return separator < 0 ? { key: record, value: null } : { key: record.slice(0, separator), value: record.slice(separator + 1) };
  });
  return credentialHelpersFromEntries(entries, url);
}

// --- Диагностика для живых проверок: ключи и scope без значений + сетевая проба.
const PROBES = {
  'ls-remote': ['ls-remote', '--heads', 'origin'],
  'push-dry-run': ['push', '--dry-run', 'origin', 'HEAD:refs/heads/og-auth-probe'],
};

export function diagnoseNetwork({ root = process.cwd(), probe = null, source = process.env } = {}) {
  const lines = ['OverGate Beads network Git diagnostic (mjs; values hidden)'];
  const carried = readUserGitConfig(root, source);
  lines.push(...(carried.length ? carried.map(item => `carried: ${item.scope} ${redactKey(item.key)}`) : ['carried: <none>']));
  for (const item of residualUserGitKeys(root, source)) lines.push(`residual: ${item.scope} ${redactKey(item.key)} (not carried; og-4py residual, ADR §3.39)`);
  if (probe) {
    requireThat(Object.hasOwn(PROBES, probe), 'probe must be ls-remote or push-dry-run');
    const run = spawnSync('git', PROBES[probe], { cwd: root, env: networkGitEnvironment(root, source), timeout: 120000,
      stdio: ['ignore', 'ignore', 'pipe'] });
    const stderr = run.stderr ? run.stderr.toString('utf8') : '';
    const result = run.status === 0 ? 'ok'
      : /terminal prompts disabled|could not read (Username|Password)|Authentication failed|HTTP (401|403)|returned error: 40[13]/i.test(stderr) ? 'auth-unavailable' : 'failed';
    lines.push(`probe: ${probe} exit=${run.status} result=${result}`);
  }
  return lines.join('\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2), options = {};
    requireThat(args[0] === '--diagnose', 'usage: node scripts/lib/bd-git-environment.mjs --diagnose [--probe ls-remote|push-dry-run] [--root DIR]');
    for (let index = 1; index < args.length; index += 2) {
      requireThat(['--probe', '--root'].includes(args[index]) && args[index + 1], 'usage: --diagnose [--probe ls-remote|push-dry-run] [--root DIR]');
      options[args[index].slice(2)] = args[index + 1];
    }
    process.stdout.write(diagnoseNetwork(options) + '\n');
  } catch (error) {
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  }
}
