import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const failWhenMissing = process.argv.includes('--require-dist');
const maxJsBytes = 350 * 1024;
const maxCssBytes = 140 * 1024;

if (!fs.existsSync(dist)) {
  if (failWhenMissing) {
    console.error('Bundle budget check failed: dist/ does not exist. Run vp build first.');
    process.exit(1);
  }
  console.warn('Bundle budget check skipped: dist/ does not exist.');
  process.exit(0);
}

const failures = [];

function collectBudgetedAssets(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      return collectBudgetedAssets(fullPath);
    }
    return entry.isFile() && /\.(?:js|css)$/.test(entry.name) ? [fullPath] : [];
  });
}

for (const assetPath of collectBudgetedAssets(dist)) {
  const size = fs.statSync(assetPath).size;
  const limit = assetPath.endsWith('.js') ? maxJsBytes : maxCssBytes;
  if (size <= limit) continue;
  failures.push(
    `${path.relative(root, assetPath).replaceAll('\\', '/')} is ${Math.ceil(
      size / 1024,
    )} KiB; limit is ${Math.ceil(limit / 1024)} KiB.`,
  );
}

if (failures.length) {
  console.error('Bundle budget check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}
