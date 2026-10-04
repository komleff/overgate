#!/usr/bin/env node
// Чтение задач Beads из снимка origin/beads-backup (JSONL на stdin), без bd и базы.
// Подкоманды: list / show <id> / ready. См. правила проекта .claude/rules/beads.md (помощник чтения снимка).
// ready — ПРИБЛИЖЕНИЕ bd ready: авторитетен bd ready из основного checkout.

import { readFileSync } from 'node:fs';

const argv = process.argv.slice(2);
const sub = argv[0];
const flag = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
const hasFlag = (name) => argv.includes(name);

// Снимок со stdin (fd 0).
let raw = '';
try { raw = readFileSync(0, 'utf8'); } catch { raw = ''; }
const issues = [];
raw.split(/\n/).forEach((line, i) => {
  const s = line.trim();
  if (!s) return;
  let o;
  // fail-closed: повреждённый снимок не игнорируем по-тихому (иначе ready/list считались бы
  // по частичному набору и могли скрыть блокеры / задачи).
  try { o = JSON.parse(s); }
  catch { console.error(`ERROR: снимок повреждён — строка ${i + 1} не парсится как JSON (fail-closed).`); process.exit(2); }
  if (o && o._type === 'memory') return;   // служебные строки — не задачи
  if (o && o.id) issues.push(o);
});
const byId = new Map(issues.map((i) => [i.id, i]));
// Санитайз control/ANSI-символов для human-вывода: задачи, созданные ВНЕ очереди (напрямую
// bd / из worktree / старым tooling), могли получить escape-последовательности → terminal-injection
// при печати в bd-read/логи. Заменяем control (кроме \t,\n) на '?'. --json остаётся raw.
const safe = (s) => Array.from(String(s == null ? '' : s)).map((c) => { const n = c.charCodeAt(0); return (n === 127 || (n < 32 && n !== 9 && n !== 10)) ? '?' : c; }).join('');
const trunc = (s, n) => { s = safe(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

// Явные НЕ-блокирующие типы рёбер (всё остальное трактуем как блокирующее).
const NONBLOCKING = new Set(['parent-child', 'related', 'discovered-from', 'relates-to']);
// Активные блокеры задачи. Консервативно: НЕ блокирует только явный известный
// non-blocking тип; ребро 'blocks' / без типа / неизвестного типа / кривое (не объект)
// считаем блокирующим. Блокер отсутствует в снимке / внешний → тоже активный.
const activeBlockers = (issue) => {
  // bd export ОПУСКАЕТ массив dependencies у задач без зависимостей (в реальном snapshot он есть
  // лишь у части задач). Тогда доверяем dependency_count: >0 без массива → блокеры неизвестны →
  // консервативно блокируем; 0/нет → блокеров нет. (Раньше отсутствие массива fail-clos'ило весь ready.)
  if (!Array.isArray(issue.dependencies)) {
    return Number(issue.dependency_count) > 0 ? ['(unknown)'] : [];
  }
  const deps = issue.dependencies;
  const blockers = [];
  for (const d of deps) {
    // Сначала валидируем ФОРМУ ребра: объект со строковым depends_on_id и (если задан)
    // issue_id == текущей задаче. НЕ блокирует только хорошо сформированное ребро
    // известного non-blocking типа; всё прочее (кривое / без depends_on_id / без типа /
    // неизвестный тип) — консервативно считаем блокирующим.
    const wellFormed = d && typeof d === 'object' && typeof d.depends_on_id === 'string'
      && (d.issue_id === undefined || d.issue_id === issue.id);
    if (wellFormed && NONBLOCKING.has(d.type)) continue;
    const bid = wellFormed ? d.depends_on_id : null;
    const b = bid ? byId.get(bid) : null;
    if (!b || b.status !== 'closed') blockers.push(bid);
  }
  return blockers;
};

if (sub === 'list' || sub === 'ready') {
  let rows = issues;
  if (sub === 'ready') {
    // fail-closed только если снимок вообще не несёт инфо о зависимостях (ни массива dependencies,
    // ни dependency_count ни у одной задачи) — тогда ready недостоверен. Если инфо есть хоть в какой
    // форме, отсутствие массива у конкретной задачи трактуется per-issue в activeBlockers (по count).
    const schemaOk = issues.length === 0
      || issues.some((i) => Array.isArray(i.dependencies) || 'dependency_count' in i);
    if (!schemaOk) {
      console.error('ERROR: снимок не несёт инфо о зависимостях (ни dependencies, ни dependency_count) — ready ненадёжен (fail-closed).');
      console.error('       Используйте авторитетный `bd ready` из основного checkout.');
      process.exit(2);
    }
    rows = issues.filter((i) => i.status === 'open' && activeBlockers(i).length === 0);
    const fa = flag('--assignee');   // ready [--assignee] — фильтр по исполнителю (как в usage)
    if (fa) rows = rows.filter((i) => i.assignee === fa);
  } else {
    const fs = flag('--status'), fp = flag('--priority'), fa = flag('--assignee'), ft = flag('--type');
    rows = rows.filter((i) =>
      (!fs || i.status === fs) &&
      (fp === undefined || String(i.priority) === String(fp)) &&
      (!fa || i.assignee === fa) &&
      (!ft || i.issue_type === ft));
  }
  if (hasFlag('--json')) { console.log(JSON.stringify(rows)); process.exit(0); }
  if (!rows.length) { console.log('(нет задач)'); process.exit(0); }
  for (const i of rows) {
    console.log(`${safe(i.id).padEnd(10)} ${safe(i.status).padEnd(11)} P${safe(i.priority ?? '?')} ${safe(i.issue_type).padEnd(8)} ${trunc(i.title, 60)}`);
  }
  process.exit(0);
}

if (sub === 'show') {
  const id = argv[1] && !argv[1].startsWith('-') ? argv[1] : flag('--id');
  if (!id) { console.error('ERROR: укажите id: bd-read.sh show <id>'); process.exit(1); }
  const it = byId.get(id);
  if (!it) { console.error(`ERROR: задача ${id} не найдена в снимке.`); process.exit(1); }
  if (hasFlag('--json')) { console.log(JSON.stringify(it)); process.exit(0); }
  const show = (k, v) => { if (v !== undefined && v !== null && v !== '') console.log(`${k}: ${safe(v)}`); };
  show('ID', it.id); show('Title', it.title); show('Status', it.status);
  show('Priority', it.priority); show('Type', it.issue_type); show('Assignee', it.assignee);
  show('External-ref', it.external_ref); show('Close-reason', it.close_reason);
  if (it.description) console.log(`\nDescription:\n${safe(it.description)}`);
  if (it.notes) console.log(`\nNotes:\n${safe(it.notes)}`);
  const blockedBy = (Array.isArray(it.dependencies) ? it.dependencies : [])
    .filter((d) => d && d.type === 'blocks')
    .map((d) => { const b = byId.get(d.depends_on_id); return `${safe(d.depends_on_id)} [${b ? safe(b.status) : 'отсутствует в снимке'}]`; });
  if (blockedBy.length) console.log(`\nBlocked by:\n  ${blockedBy.join('\n  ')}`);
  const blocks = issues.filter((o) => (Array.isArray(o.dependencies) ? o.dependencies : [])
    .some((d) => d && d.type === 'blocks' && d.depends_on_id === id)).map((o) => safe(o.id));
  if (blocks.length) console.log(`\nBlocks:\n  ${blocks.join(', ')}`);
  process.exit(0);
}

console.error('Usage: bd-read.sh <list|show <id>|ready> [--status S] [--priority N] [--assignee A] [--type T] [--json]');
process.exit(1);
