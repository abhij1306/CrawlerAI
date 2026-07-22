import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

const checks = [
  { file: 'app/data-enrichment/page-view.tsx', maxLines: 260 },
  { file: 'app/runs/page-view.tsx', maxLines: 260 },
  { file: 'components/layout/app-shell.tsx', maxLines: 260 },
];

const requiredApiOwners = [
  'admin.ts',
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
