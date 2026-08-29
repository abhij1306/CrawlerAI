#!/usr/bin/env node

import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backendRoot = join(repositoryRoot, 'backend');
const frontendRoot = join(repositoryRoot, 'frontend');
const args = process.argv.slice(2).filter((argument) => argument !== '--');

function option(name, fallback) {
  const separateIndex = args.indexOf(name);
  if (separateIndex >= 0) return args[separateIndex + 1] ?? fallback;
  const inline = args.find((argument) => argument.startsWith(`${name}=`));
  return inline?.slice(name.length + 1) ?? fallback;
}

const mode = option('--mode', 'fix');
if (!['fix', 'check'].includes(mode)) throw new Error(`Unknown quality mode: ${mode}`);

const requestedScope = option('--scope', 'all').toLowerCase();
const validScopes = new Set(['all', 'backend', 'frontend', 'contract']);
if (!validScopes.has(requestedScope)) throw new Error(`Unknown quality scope: ${requestedScope}`);
const scopes =
  requestedScope === 'all'
    ? new Set(['backend', 'frontend', 'contract'])
    : new Set([requestedScope]);

function executable(candidates, missingMessage) {
  const candidate = candidates.find(existsSync);
  if (!candidate) throw new Error(missingMessage);
  return candidate;
}

const backendPython = () =>
  executable(
    [join(backendRoot, '.venv', 'Scripts', 'python.exe'), join(backendRoot, '.venv', 'bin', 'python')],
    "Backend virtual environment missing. Run 'uv sync --frozen --extra dev' in backend/.",
  );

function backendTool(name) {
  return executable(
    [join(backendRoot, '.venv', 'Scripts', `${name}.exe`), join(backendRoot, '.venv', 'bin', name)],
    `Backend tool '${name}' missing. Run 'uv sync --frozen --extra dev' in backend/.`,
  );
}

function step(name, command, commandArgs, cwd, env = process.env) {
  process.stdout.write(`\n==> ${name}\n`);
  const result = spawnSync(command, commandArgs, { cwd, env, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function vp(name, commandArgs, env = process.env) {
  if (process.platform === 'win32') {
    step(name, process.env.ComSpec ?? 'cmd.exe', ['/d', '/s', '/c', 'vp', ...commandArgs], frontendRoot, env);
    return;
  }
  step(name, 'vp', commandArgs, frontendRoot, env);
}

function backendChecks() {
  const ruffArgs = ['.'];
  if (mode === 'check') {
    step('Ruff lint', backendTool('ruff'), ['check', ...ruffArgs], backendRoot);
    step('Ruff format', backendTool('ruff'), ['format', '--check', ...ruffArgs], backendRoot);
  } else {
    step('Ruff lint fixes', backendTool('ruff'), ['check', ...ruffArgs, '--fix'], backendRoot);
    step('Ruff format fixes', backendTool('ruff'), ['format', ...ruffArgs], backendRoot);
  }
  step('Mypy', backendTool('mypy'), [], backendRoot);
  step('Architecture policy', backendTool('lint-imports'), ['--no-cache'], backendRoot);
  step('Dead-code policy', backendTool('vulture'), ['app', '--min-confidence', '100'], backendRoot);
  step('Dependency hygiene', backendTool('deptry'), ['.'], backendRoot);
}

function frontendChecks() {
  vp(
    mode === 'check' ? 'Frontend format, lint, and types' : 'Frontend format, lint, and types with fixes',
    mode === 'check' ? ['check'] : ['check', '--fix'],
  );
  vp('Frontend policy', ['run', 'check:policy']);
  vp('Frontend dead-code and dependency policy', ['exec', 'knip']);
}

function contractCheck() {
  const output = join(backendRoot, '.artifacts', 'openapi.json');
  step(
    'Export OpenAPI contract',
    backendPython(),
    ['-m', 'scripts.export_openapi', '--output', output],
    backendRoot,
  );
  vp('API contract policy', ['run', 'check:contract'], {
    ...process.env,
    CRAWLERAI_OPENAPI_JSON: output,
  });
}

if (scopes.has('backend')) backendChecks();
if (scopes.has('frontend')) frontendChecks();
if (scopes.has('contract')) contractCheck();

process.stdout.write(`\n${[...scopes].join(', ')} quality ${mode} passed.\n`);
