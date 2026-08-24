/**
 * Colour contrast + border-freeze gate.
 *
 * Parses the two token blocks in app/globals.css (`:root` for light,
 * `html[data-theme='dark']` for dark), resolves var() indirection, composites
 * any translucent value over its surface, and asserts the contrast contract
 * documented alongside the tokens:
 *
 *   - text-primary / secondary / muted clear 4.5:1 on every surface they are
 *     used on.
 *   - text-subtle is placeholder-and-disabled only (WCAG-exempt) and clears
 *     3:1 for legibility.
 *   - accent-fg on accent clears 4.5:1, so 14px button text passes AA.
 *   - each semantic *-text clears 4.5:1 on its own *-bg.
 *
 * A token the contract names but the stylesheet does not define is a FAILURE,
 * not a skip: a renamed or deleted token would otherwise quietly remove its own
 * assertion and leave the gate green. Skips are reserved for the one supported
 * optional case — a value that resolves but is not a plain colour (color-mix()
 * and other computed forms this script cannot evaluate).
 *
 * There is deliberately NO border assertion. Borders are frozen by project
 * constraint — separation is carried by fill and shadow instead — so asserting
 * a threshold they are not allowed to meet would just be a permanently red
 * gate. What IS asserted is that the border tokens have not drifted: that
 * turns "no stronger borders" from a review convention into something CI
 * enforces.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.cwd();
const STYLESHEET = join(ROOT, 'app', 'globals.css');

/* ── Token extraction ─────────────────────────────────────────────────── */

function blockBody(css, selector) {
  // Anchor to the selector at the start of its own line, immediately followed
  // by its brace. globals.css names ":root" inside a comment and again,
  // indented, inside two media queries; a bare indexOf would land on the
  // comment and only reach the right block because no brace happens to sit
  // in between.
  let start = -1;
  for (let i = css.indexOf(selector); i !== -1; i = css.indexOf(selector, i + 1)) {
    if (i !== 0 && css[i - 1] !== '\n') continue;
    if (!/^[ \t]*\{/.test(css.slice(i + selector.length))) continue;
    start = i;
    break;
  }
  if (start === -1) throw new Error(`Could not find "${selector}" in globals.css`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`Unbalanced braces after "${selector}"`);
}

function readTokens(body) {
  const tokens = new Map();
  const declaration = /(--[\w-]+)\s*:\s*([^;]+);/g;
  let match;
  while ((match = declaration.exec(body)) !== null) {
    tokens.set(match[1], match[2].trim());
  }
  return tokens;
}

/* ── Colour parsing ───────────────────────────────────────────────────── */

const UNRESOLVED = Symbol('unresolved');

function resolve(name, tokens, seen = new Set()) {
  if (seen.has(name)) return UNRESOLVED;
  seen.add(name);
  const raw = tokens.get(name);
  if (raw === undefined) return UNRESOLVED;
  const varOnly = /^var\(\s*(--[\w-]+)\s*\)$/.exec(raw);
  if (varOnly) return resolve(varOnly[1], tokens, seen);
  return raw;
}

function parseColor(value) {
  if (typeof value !== 'string') return null;
  const text = value.trim();

  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(text);
  if (hex) {
    let digits = hex[1];
    if (digits.length === 3) digits = digits.replace(/([0-9a-f])/gi, '$1$1');
    const int = Number.parseInt(digits.slice(0, 6), 16);
    return {
      r: (int >> 16) & 255,
      g: (int >> 8) & 255,
      b: int & 255,
      a: digits.length === 8 ? Number.parseInt(digits.slice(6, 8), 16) / 255 : 1,
    };
  }

  const rgb = /^rgba?\(([^)]+)\)$/i.exec(text);
  if (rgb) {
    const parts = rgb[1].split(/[,/]/).map((p) => p.trim());
    if (parts.length < 3) return null;
    const channel = (p) =>
      p.endsWith('%') ? (Number.parseFloat(p) / 100) * 255 : Number.parseFloat(p);
    const [r, g, b] = parts.slice(0, 3).map(channel);
    if ([r, g, b].some(Number.isNaN)) return null;
    const alpha = parts[3] === undefined ? 1 : Number.parseFloat(parts[3]);
    return { r, g, b, a: Number.isNaN(alpha) ? 1 : alpha };
  }

  // color-mix() and other computed forms are reported as skips, not failures.
  return null;
}

function composite(fg, bg) {
  if (fg.a >= 1) return fg;
  return {
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  };
}

function luminance({ r, g, b }) {
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/* ── The contract ─────────────────────────────────────────────────────── */

const SURFACES = ['--bg-base', '--bg-alt', '--bg-panel', '--bg-elevated', '--bg-well'];

const PAIRS = [
  { fg: '--text-primary', backgrounds: SURFACES, min: 4.5 },
  { fg: '--text-secondary', backgrounds: SURFACES, min: 4.5 },
  { fg: '--text-muted', backgrounds: SURFACES, min: 4.5 },
  // Placeholder / disabled only — WCAG-exempt, held to 3:1 for legibility.
  { fg: '--text-subtle', backgrounds: ['--bg-panel', '--bg-well'], min: 3 },
  { fg: '--accent-fg', backgrounds: ['--accent'], min: 4.5 },
  { fg: '--success-text', backgrounds: ['--success-bg'], min: 4.5 },
  { fg: '--warning-text', backgrounds: ['--warning-bg'], min: 4.5 },
  { fg: '--danger-text', backgrounds: ['--danger-bg'], min: 4.5 },
  { fg: '--info-text', backgrounds: ['--info-bg'], min: 4.5 },
];

// Borders are frozen: no component may gain a border it does not already have,
// and no existing border may be strengthened. Drift here is a hard failure.
const FROZEN_BORDERS = {
  light: { '--border-subtle': '#f0f0f1', '--border': '#e7e7e9', '--border-strong': '#d9d9dc' },
  dark: { '--border-subtle': '#1c1e24', '--border': '#23262d', '--border-strong': '#2f323b' },
};

/* ── Run ──────────────────────────────────────────────────────────────── */

if (!existsSync(STYLESHEET)) {
  console.error(`Stylesheet not found: ${STYLESHEET}`);
  process.exit(1);
}

const css = readFileSync(STYLESHEET, 'utf8');
const themes = {
  light: readTokens(blockBody(css, ':root')),
  dark: readTokens(blockBody(css, "html[data-theme='dark']")),
};

// The dark block only overrides; anything it omits falls through to :root.
for (const [name, value] of themes.light) {
  if (!themes.dark.has(name)) themes.dark.set(name, value);
}

const failures = [];
const skips = [];

for (const [themeName, tokens] of Object.entries(themes)) {
  const colorOf = (name, over = null) => {
    const resolved = resolve(name, tokens);
    // Undefined (or self-referential) means the contract names a token the
    // stylesheet no longer has — a broken contract, never a skip.
    if (resolved === UNRESOLVED) return { missing: `${name} is not defined` };
    const parsed = parseColor(resolved);
    // Resolved but not a plain colour: color-mix() and friends genuinely
    // cannot be evaluated here. This is the only supported skip.
    if (!parsed) return { skip: `${name} is not a plain colour (${resolved})` };
    return { color: over ? composite(parsed, over) : parsed };
  };

  const record = (result) => {
    if (result.missing) failures.push(`${themeName}: ${result.missing}`);
    else if (result.skip) skips.push(`${themeName}: ${result.skip}`);
    return result;
  };

  // Every translucent surface is composited over the page canvas, so the
  // canvas is required too; white only keeps the rest of the run informative.
  const canvas = record(colorOf('--bg-base'));

  for (const { fg, backgrounds, min } of PAIRS) {
    for (const bgName of backgrounds) {
      // A translucent surface sits on the page canvas.
      const bg = record(colorOf(bgName, canvas.color ?? { r: 255, g: 255, b: 255, a: 1 }));
      if (!bg.color) continue;
      const fgColor = record(colorOf(fg, bg.color));
      if (!fgColor.color) continue;
      const ratio = contrast(fgColor.color, bg.color);
      if (ratio < min) {
        failures.push(`${themeName}: ${fg} on ${bgName} is ${ratio.toFixed(2)}:1, needs ${min}:1`);
      }
    }
  }

  for (const [name, expected] of Object.entries(FROZEN_BORDERS[themeName])) {
    const actual = resolve(name, tokens);
    if (actual === UNRESOLVED) {
      failures.push(`${themeName}: ${name} is missing — border tokens are frozen`);
    } else if (actual.toLowerCase() !== expected) {
      failures.push(
        `${themeName}: ${name} changed to ${actual} (frozen at ${expected}). ` +
          'Borders may not be strengthened — use fill or shadow for separation.',
      );
    }
  }
}

if (skips.length) {
  console.warn('Skipped (not resolvable to a plain colour):');
  for (const skip of new Set(skips)) console.warn(`- ${skip}`);
}

if (failures.length) {
  console.error('Contrast contract violations:');
  for (const failure of new Set(failures)) console.error(`- ${failure}`);
  process.exit(1);
}

console.log('Contrast contract satisfied for light and dark themes.');
