import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { render } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vite-plus/test';

import type { CrawlRecord } from '../../lib/api/types';
import { HEADER_HEIGHT, ROW_HEIGHT, RecordsTable } from './records-table';

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

// Windowing heights come from the computed CSS vars once at mount; the exported
// constants are the fallbacks. jsdom reports clientHeight 0, so the component
// keeps its 560px default viewport for both cases below.
function makeRecord(id: number): CrawlRecord {
  return {
    id,
    run_id: 1,
    source_url: `https://example.com/source/${id}`,
    data: { title: `Record ${id}` },
    raw_data: {},
    discovered_data: {},
    source_trace: {},
    raw_html_path: null,
    created_at: '2026-07-22T00:00:00Z',
  };
}

function stubCssVars(values: Record<string, string>) {
  vi.stubGlobal('getComputedStyle', () => ({
    getPropertyValue: (name: string) => values[name] ?? '',
  }));
}

function renderTable(recordCount: number) {
  const records = Array.from({ length: recordCount }, (_, index) => makeRecord(index + 1));
  return render(
    createElement(RecordsTable, {
      records,
      visibleColumns: ['title'],
      selectedIds: [],
      onSelectAll: () => {},
      onToggleRow: () => {},
    }),
  );
}

function bottomSpacerHeight(container: HTMLElement) {
  // At scrollTop 0 the top spacer is absent; the only aria-hidden div is the
  // bottom spacer whose height is (totalCount - endIndex) * rowHeight.
  const spacers = container.querySelectorAll('[aria-hidden]');
  expect(spacers).toHaveLength(1);
  return (spacers[0] as HTMLElement).style.height;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('records-table derived windowing heights', () => {
  it('drives the windowing math from the CSS vars at mount', () => {
    stubCssVars({ '--table-header-height': '40px', '--table-row-height': '50px' });
    const { container } = renderTable(100);
    // visibleCount = ceil((560 - 40) / 50) + 16 = 27 → bottom spacer (100 - 27) * 50.
    expect(bottomSpacerHeight(container)).toBe('3650px');
  });

  it('falls back to the exported constants when the CSS vars are absent', () => {
    stubCssVars({});
    const { container } = renderTable(100);
    // visibleCount = ceil((560 - 30) / 38) + 16 = 30 → bottom spacer (100 - 30) * 38.
    expect(bottomSpacerHeight(container)).toBe('2660px');
  });
});
