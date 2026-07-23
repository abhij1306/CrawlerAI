import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';

import type { CrawlRun } from '../../lib/api/types';
import { RunTerminalShell } from './run-terminal-shell';

function makeRun(url: string): CrawlRun {
  return {
    id: 1,
    user_id: 1,
    run_type: 'crawl',
    url,
    status: 'completed',
    surface: 'ecommerce_listing',
    settings: {},
    requested_fields: [],
    result_summary: {},
    run_health: {},
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
    completed_at: null,
  };
}

function renderShell(run: CrawlRun) {
  render(
    <RunTerminalShell
      run={run}
      runErrorMessage=""
      actionError=""
      actions={null}
      tabs={null}
      summary={null}
    >
      <div>terminal content</div>
    </RunTerminalShell>,
  );
}

describe('RunTerminalShell run URL', () => {
  it('renders http(s) run URLs as external links', () => {
    renderShell(makeRun('https://shop-demo.example/products'));
    const link = screen.getByRole('link', { name: 'https://shop-demo.example/products' });
    expect(link).toHaveAttribute('href', 'https://shop-demo.example/products');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('never renders dangerous run URLs as clickable links', () => {
    renderShell(makeRun('javascript:alert(document.cookie)'));
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('javascript:alert(document.cookie)')).toBeInTheDocument();
  });
});
