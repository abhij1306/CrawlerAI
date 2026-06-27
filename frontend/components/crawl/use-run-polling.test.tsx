import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vite-plus/test';

import type { CrawlRun } from '../../lib/api/types';
import { useTerminalSync } from './use-run-polling';

type SyncHarnessProps = {
  run: CrawlRun | undefined;
  terminal: boolean;
  refetch: () => Promise<unknown>;
};

function makeTerminalRun(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: 101,
    user_id: 1,
    run_type: 'crawl',
    url: 'https://example.com/products/chair',
    status: 'completed',
    surface: 'ecommerce_detail',
    settings: {},
    requested_fields: [],
    result_summary: {},
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
    updated_at: new Date('2026-04-08T10:05:00Z').toISOString(),
    completed_at: new Date('2026-04-08T10:05:00Z').toISOString(),
    ...overrides,
  };
}

function SyncHarness({ run, terminal, refetch }: Readonly<SyncHarnessProps>) {
  useTerminalSync(run, terminal, [{ refetch }]);
  return null;
}

describe('useTerminalSync', () => {
  it('refetches only after an observed active run becomes terminal', async () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    const terminalRun = makeTerminalRun();
    const activeRun = makeTerminalRun({
      status: 'running',
      completed_at: null,
      updated_at: new Date('2026-04-08T10:04:00Z').toISOString(),
    });
    const { rerender } = render(<SyncHarness run={terminalRun} terminal refetch={refetch} />);

    expect(refetch).not.toHaveBeenCalled();

    rerender(<SyncHarness run={activeRun} terminal={false} refetch={refetch} />);
    expect(refetch).not.toHaveBeenCalled();

    rerender(<SyncHarness run={terminalRun} terminal refetch={refetch} />);
    await waitFor(() => {
      expect(refetch).toHaveBeenCalledTimes(1);
    });

    rerender(<SyncHarness run={terminalRun} terminal refetch={refetch} />);
    expect(refetch).toHaveBeenCalledTimes(1);

    rerender(
      <SyncHarness
        run={makeTerminalRun({ updated_at: new Date('2026-04-08T10:06:00Z').toISOString() })}
        terminal
        refetch={refetch}
      />,
    );

    await waitFor(() => {
      expect(refetch).toHaveBeenCalledTimes(2);
    });
  });
});
