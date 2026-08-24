import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

const checks = [
  { file: 'app/data-enrichment/page-view.tsx', maxLines: 260 },
  { file: 'app/runs/page-view.tsx', maxLines: 260 },
  { file: 'components/layout/app-shell.tsx', maxLines: 260 },
];

// Default per-file LOC cap over app/, components/, lib/, src/ (non-test .ts/.tsx).
const DEFAULT_MAX_LINES = 400;
const scannedRoots = ['app', 'components', 'lib', 'src'];
// Measured 2026-07-22 (wc -l) + ~5% headroom. Raise-only; split the owner instead.
const lineBudgetExceptions = new Map([
  ['lib/api/types.ts', 525],
  ['components/crawl/log-terminal.tsx', 820],
  ['components/crawl/form-fields.tsx', 630],
  ['components/crawl/log-terminal-utils.ts', 520],
  ['components/crawl/crawl-config-logic.ts', 465],
  ['components/crawl/records-table.tsx', 425],
]);

const requiredApiOwners = [
  'admin.ts',
  'api-access.ts',
  'auth.ts',
  'crawls.ts',
  'dashboard.ts',
  'data-enrichment.ts',
  'domain-memory.ts',
  'jobs.ts',
  'knowledge.ts',
  'product-intelligence.ts',
  'selectors.ts',
];

const failures = [];

function read(relativePath) {
  try {
    return fs.readFileSync(path.join(root, relativePath), 'utf8');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    failures.push(`${relativePath} could not be read: ${message}`);
    return null;
  }
}

for (const check of checks) {
  const content = read(check.file);
  if (content === null) continue;
  const lines = content.split(/\r?\n/).length;
  if (lines > check.maxLines) {
    failures.push(`${check.file} has ${lines} lines; limit is ${check.maxLines}. Split the owner.`);
  }
}

for (const owner of requiredApiOwners) {
  const ownerPath = path.join(root, 'lib', 'api', owner);
  if (!fs.existsSync(ownerPath)) {
    failures.push(`lib/api/${owner} is missing. Keep API methods split by domain owner.`);
  }
}

function listSourceFiles(directory) {
  const files = [];
  if (!fs.existsSync(directory)) {
    return files;
  }
  const stack = [directory];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
        continue;
      }
      if (!entry.isFile() || !/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) {
        continue;
      }
      files.push(fullPath);
    }
  }
  return files;
}

for (const scannedRoot of scannedRoots) {
  for (const fullPath of listSourceFiles(path.join(root, scannedRoot))) {
    const relativePath = path.relative(root, fullPath).replaceAll('\\', '/');
    const budget = lineBudgetExceptions.get(relativePath) ?? DEFAULT_MAX_LINES;
    const content = read(relativePath);
    if (content === null) continue;
    const lines = content.split(/\r?\n/).length;
    if (lines > budget) {
      failures.push(
        `${relativePath} has ${lines} lines; limit is ${budget}. Split the owner before raising the budget.`,
      );
    }
  }
}

const dataEnrichmentPage = read('app/data-enrichment/page-view.tsx');
if (
  dataEnrichmentPage !== null &&
  (/\bsessionStorage\b/.test(dataEnrichmentPage) ||
    /\bdataEnrichmentReducer\b/.test(dataEnrichmentPage))
) {
  failures.push('Data Enrichment page must delegate prefill storage and reducer state.');
}

if (failures.length) {
  console.error('Frontend architecture check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}
