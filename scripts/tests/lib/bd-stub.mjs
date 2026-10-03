#!/usr/bin/env node
// Stateful-стаб bd для тестов: логирует argv в $BD_STUB_LOG и ведёт мини-БД в
// $BD_STUB_STATE (JSONL issue-объектов). Позволяет проверять идемпотентность:
// после create последующий export содержит задачу с маркером external_ref.
import { appendFileSync, readFileSync, writeFileSync, existsSync } from 'node:fs';

const args = process.argv.slice(2);
const LOG = process.env.BD_STUB_LOG;
const STATE = process.env.BD_STUB_STATE;
if (LOG) appendFileSync(LOG, args.join('\t') + '\n');

const readState = () => (STATE && existsSync(STATE))
  ? readFileSync(STATE, 'utf8').split(/\n/).filter(Boolean).map((l) => JSON.parse(l)) : [];
const writeState = (arr) => { if (STATE) writeFileSync(STATE, arr.map((o) => JSON.stringify(o)).join('\n') + (arr.length ? '\n' : '')); };
// Поддержка обеих форм флага: --flag value и --flag=value.
const flagVal = (flag) => {
  const eq = args.find((a) => a.startsWith(flag + '='));
  if (eq) return eq.slice(flag.length + 1);
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
};

const cmd = args[0];
if (cmd === 'export') {
  const out = flagVal('-o');
  // bd 0.62 export передаёт счётчик, но не тексты комментариев.
  const data = readState().map(({ comments, ...issue }) => JSON.stringify({
    ...issue, comment_count: (comments || []).length,
  })).join('\n');
  const text = data + (data ? '\n' : '');
  if (out) writeFileSync(out, text); else process.stdout.write(text);
  process.exit(0);
}
if (cmd === 'create') {
  const st = readState();
  const ctr = STATE ? STATE + '.ctr' : null;
  let n = 0;
  if (ctr && existsSync(ctr)) { const v = parseInt(readFileSync(ctr, 'utf8'), 10); if (!Number.isNaN(v)) n = v; }
  n++;
  if (ctr) writeFileSync(ctr, String(n));
  const id = `U2-stub${n}`;
  st.push({ id, status: 'open', external_ref: flagVal('--external-ref'), notes: '', comments: [], dependencies: [] });
  writeState(st);
  process.stdout.write(id + '\n');   // --silent: только ID
  process.exit(0);
}
const st = readState();
const find = (id) => st.find((o) => o.id === id);
if (cmd === 'close') { const t = find(args[1]); if (t) t.status = 'closed'; writeState(st); process.exit(0); }
if (cmd === 'comment') {
  console.error('unknown command "comment"; use comments add');
  process.exit(1);
}
if (cmd === 'comments') {
  if (args.length === 3 && args[1] !== 'add' && args[2] === '--json') {
    if (process.env.BD_STUB_COMMENTS_READ_FAIL === '1') {
      console.error('comments read failed');
      process.exit(9);
    }
    process.stdout.write(process.env.BD_STUB_COMMENTS_JSON ?? JSON.stringify(find(args[1])?.comments || []));
    process.exit(0);
  }
  // Контракт применяемой формы bd 0.62: --file читает обычный файл, не stdin.
  const file = flagVal('--file') ?? flagVal('-f');
  const fileForm = (args.length === 4 && args[3].startsWith('--file=')) ||
    (args.length === 5 && ['--file', '-f'].includes(args[3]));
  if (args[1] !== 'add' || !fileForm || !file) {
    console.error('expected comments add <id> --file <path>');
    process.exit(1);
  }
  const text = readFileSync(file, 'utf8');
  if (!text.trim()) process.exit(1);
  if (process.env.BD_STUB_COMMENT_FAIL === '1') {
    console.error('comment write failed');
    process.exit(9);
  }
  const t = find(args[2]);
  if (t) (t.comments ||= []).push({ text });
  writeState(st); process.exit(0);
}
if (cmd === 'note') {
  let text = '';
  if (args.includes('--stdin')) { try { text = readFileSync(0, 'utf8'); } catch { text = ''; } }
  else text = args[2] || '';
  const t = find(args[1]);
  if (t) t.notes = (t.notes || '') + '\n' + text;
  writeState(st); process.exit(0);
}
if (cmd === 'update') { process.exit(0); }
if (cmd === 'dep' && args[1] === 'add') {
  const t = find(args[2]);
  const b = flagVal('--blocked-by') || args[3];
  if (t) (t.dependencies ||= []).push({ issue_id: t.id, depends_on_id: b, type: 'blocks' });
  writeState(st);
  process.exit(0);
}
process.exit(0);
