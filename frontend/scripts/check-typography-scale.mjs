/**
 * Typography scale gate.
 *
 * The type ladder is 12/14/16/20/24/32, declared once in app/globals.css and
 * consumed only through the --text-* tokens (or the .type-* classes built on
 * them). Two things break that contract and are banned here:
 *
 *   1. text-xs / text-2xs — the 10px and 11px tiers were removed from the
 *      ladder, so these utilities no longer exist. A leftover renders at the
 *      inherited size instead of erroring, which is exactly the kind of silent
 *      drift this script exists to catch.
 *   2. Arbitrary font sizes — text-[13px], font-size: 15px, and friends. The
 *      table tokens are the one sanctioned escape, since they are themselves
 *      driven by --text-*.
 *
 * Mirrors check-token-escapes.mjs in shape and reporting.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();
const SOURCE_ROOTS = ['app', 'components', 'lib', 'src'];
const STYLESHEET = join('app', 'globals.css');

const RULES = [
  {
    pattern: /\btext-(?:2xs|xs)\b/,
    message: 'text-xs / text-2xs were removed from the ladder — use text-sm (12px)',
  },
  {
    pattern: /text-\[\d+(?:\.\d+)?(?:px|rem|em)\]/,
    message: 'arbitrary font size — use a --text-* ladder step',
  },
  {
    // text-[length:...] is allowed only for the table tokens.
    pattern: /text-\[length:(?!var\(--table-(?:font-size|header-font-size)\)\])/,
    message: 'arbitrary length font size — use a --text-* ladder step',
  },
  {
    // 14px is the baseline and carries essentially all content. 12px is a
    // deliberately rare tier for uppercase micro-labels, so text-sm is only
    // allowed alongside `uppercase`. Demote prose with --text-muted, not size.
    pattern: /\btext-sm\b/,
    allowIf: /\buppercase\b/,
    message: 'text-sm (12px) is for uppercase micro-labels only — use text-base (14px)',
  },
];

const STYLESHEET_RULES = [
  {
    pattern: /font-size:\s*\d+(?:\.\d+)?(?:px|rem|em)\s*;/,
    message: 'hardcoded font-size — reference a --text-* ladder token',
  },
];

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) return walk(path);
    if (!/\.(tsx|ts)$/.test(path)) return [];
    if (/\.(test|spec)\.(tsx|ts)$/.test(path)) return [];
    return [path];
  });
}

const violations = [];

function inspect(file, rules) {
  const normalized = relative(ROOT, file).replaceAll('\\', '/');
  const lines = readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, index) => {
    for (const rule of rules) {
      if (!rule.pattern.test(line)) continue;
      if (rule.allowIf?.test(line)) continue;
      violations.push(`${normalized}:${index + 1} — ${rule.message}`);
    }
  });
}

for (const root of SOURCE_ROOTS) {
  const rootPath = join(ROOT, root);
  if (!existsSync(rootPath)) continue;
  for (const file of walk(rootPath)) inspect(file, RULES);
}

const stylesheetPath = join(ROOT, STYLESHEET);
if (existsSync(stylesheetPath)) inspect(stylesheetPath, STYLESHEET_RULES);

if (violations.length) {
  console.error('Typography scale violations found:');
  for (const violation of violations) console.error(`- ${violation}`);
  process.exit(1);
}
