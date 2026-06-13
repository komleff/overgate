#!/usr/bin/env node
// Smoke-тест openai-review.mjs — без сети, не требует $OPENAI_API_KEY.
// Проверяет exit codes и вывод (stdout/stderr) на наборе кейсов T1..T5.
// Запуск: node .claude/tools/smoke-test.mjs

import { spawnSync, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import process from 'node:process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(__dirname, 'openai-review.mjs');

// Вычисляем корень git-репозитория для cwd — smoke-тест должен работать независимо от
// того, из какой директории его запустили (например, из IDE вне корня репо).
// Fallback на __dirname при любой ошибке — минимально разумное место для вызова git.
let REPO_ROOT;
try {
  REPO_ROOT = execFileSync('git', ['rev-parse', '--show-toplevel'], {
    encoding: 'utf8',
    cwd: __dirname,
  }).trim();
} catch {
  REPO_ROOT = __dirname;
}

// Запускаем скрипт в child-процессе, чтобы изолировать process.exit и поймать реальный exit code.
// OPENAI_API_KEY явно затираем — smoke-тест должен быть гарантированно off-line и работать даже
// если разработчик держит реальный ключ в окружении.
// cwd = корень репозитория, чтобы git-вызовы внутри openai-review.mjs работали предсказуемо.
function run(args) {
  const env = { ...process.env };
  delete env.OPENAI_API_KEY;
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: 'utf8',
    env,
    cwd: REPO_ROOT,
    // Без shell — аргументы передаются массивом, без риска интерполяции.
    shell: false,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
  };
}

// Минимальный assert-фреймворк — один тест = запись в results, финальный exit по суммарному status.
const results = [];
function check(name, { expectedExit, expectStdout, expectStderr }, actual) {
  const problems = [];
  if (actual.status !== expectedExit) {
    problems.push(`exit ${actual.status} != ${expectedExit}`);
  }
  if (expectStdout && !expectStdout.test(actual.stdout)) {
    problems.push(`stdout не соответствует ${expectStdout}`);
  }
  if (expectStderr && !expectStderr.test(actual.stderr)) {
    problems.push(`stderr не соответствует ${expectStderr}`);
  }
  const ok = problems.length === 0;
  results.push({ name, ok, problems, actual });
}

// T1. --help → exit 0, stdout содержит "Usage".
check(
  'T1 --help → exit 0 + stdout содержит Usage',
  { expectedExit: 0, expectStdout: /Usage/ },
  run(['--help']),
);

// T2. --model без --base → exit 2.
check(
  'T2 --model без --base → exit 2',
  { expectedExit: 2 },
  run(['--model', 'gpt-5.4']),
);

// T3. --base без --model → exit 2.
check(
  'T3 --base без --model → exit 2',
  { expectedExit: 2 },
  run(['--base', 'main']),
);

// T4. Модель вне allowlist → exit 2, stderr содержит "вне allowlist".
check(
  'T4 модель вне allowlist → exit 2 + stderr содержит "вне allowlist"',
  { expectedExit: 2, expectStderr: /вне allowlist/ },
  run(['--model', 'gpt-5.0-garbage', '--base', 'main']),
);

// T5. Без аргументов → exit 2 с usage (strict-поведение, чтобы автоматизация не подумала что всё ok).
check(
  'T5 без аргументов → exit 2',
  { expectedExit: 2 },
  run([]),
);

// Печать результатов и финальный exit.
let failed = 0;
for (const r of results) {
  const mark = r.ok ? 'PASS' : 'FAIL';
  process.stdout.write(`[${mark}] ${r.name}\n`);
  if (!r.ok) {
    failed += 1;
    for (const p of r.problems) process.stdout.write(`       - ${p}\n`);
    // Печатаем actual-вывод для диагностики упавшего кейса.
    if (r.actual.stdout) process.stdout.write(`       stdout: ${r.actual.stdout.replace(/\n/g, '\\n').slice(0, 200)}\n`);
    if (r.actual.stderr) process.stdout.write(`       stderr: ${r.actual.stderr.replace(/\n/g, '\\n').slice(0, 200)}\n`);
  }
}

process.stdout.write(`\n${results.length - failed}/${results.length} passed\n`);
process.exit(failed === 0 ? 0 : 1);
