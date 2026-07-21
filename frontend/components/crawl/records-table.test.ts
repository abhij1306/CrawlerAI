import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vite-plus/test';

import { HEADER_HEIGHT, ROW_HEIGHT } from './records-table';

// Regression guard: the records-table virtualization windowing math runs on JS
// constants because CSS vars can't feed it. They must stay in sync with the
// design tokens in globals.css — a drift here overstates scroll height and
// lags the rendered window behind the scroll position on large result sets.
const globalsCssPath = [
  join(process.cwd(), 'app', 'globals.css'),
  join(process.cwd(), 'frontend', 'app', 'globals.css'),
].find(existsSync);

if (!globalsCssPath) {
  throw new Error('Could not locate app/globals.css');
}

const globalsCss = readFileSync(globalsCssPath, 'utf8');

function tokenPx(name: string): number {
  const match = new RegExp(`--${name}:\\s*(\\d+)px`).exec(globalsCss);
  if (!match) {
    throw new Error(`--${name} not found in globals.css`);
  }
  return Number(match[1]);
}

describe('records-table virtualization constants', () => {
  it('ROW_HEIGHT matches --table-row-height', () => {
    expect(ROW_HEIGHT).toBe(tokenPx('table-row-height'));
  });

  it('HEADER_HEIGHT matches --table-header-height', () => {
    expect(HEADER_HEIGHT).toBe(tokenPx('table-header-height'));
  });
});
