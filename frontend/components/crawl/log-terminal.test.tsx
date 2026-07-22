import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vite-plus/test';

import type { CrawlLog } from '../../lib/api/types';
import { LogTerminal } from './log-terminal';
import { LOG_GROUP_WINDOW_SIZE } from './log-terminal-utils';

const ZEBRA_CLASS = 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]';

function makeStartingLogs(count: number): CrawlLog[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    level: 'info',
    message: `Starting crawl run for https://example.com/p/${index + 1} (${index + 1}/${count})`,
    created_at: new Date(Date.parse('2026-04-08T10:00:00Z') + index * 1000).toISOString(),
  }));
}

function rowClassFor(url: string): string {
  const section = screen.getByTitle(url).closest('section');
  return section?.querySelector('div')?.className ?? '';
}

function stubScrollIntoView() {
  const scrollIntoView = vi.fn();
  const descriptor = Object.getOwnPropertyDescriptor(
    window.HTMLElement.prototype,
    'scrollIntoView',
  );
  window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
  return {
    scrollIntoView,
    restore: () => {
      if (descriptor) {
        Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', descriptor);
      } else {
        Reflect.deleteProperty(window.HTMLElement.prototype, 'scrollIntoView');
      }
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('LogTerminal group windowing', () => {
  it('keeps zebra striping stable when the sliding window drops a group', () => {
    const allLogs = makeStartingLogs(LOG_GROUP_WINDOW_SIZE + 2);
    const { rerender } = render(<LogTerminal logs={allLogs.slice(0, LOG_GROUP_WINDOW_SIZE + 1)} />);

    // p/3 is absolute index 2 (even → striped), p/4 is absolute index 3 (odd → plain).
    const stripedBefore = rowClassFor('https://example.com/p/3');
    const plainBefore = rowClassFor('https://example.com/p/4');
    expect(stripedBefore).toContain(ZEBRA_CLASS);
    expect(plainBefore).not.toContain(ZEBRA_CLASS);

    // The window slides by one: both rows shift one window-relative position.
    rerender(<LogTerminal logs={allLogs} />);

    expect(rowClassFor('https://example.com/p/3')).toBe(stripedBefore);
    expect(rowClassFor('https://example.com/p/4')).toBe(plainBefore);
  });

  it('reveals a windowed-out group when jumping to it from the timeline', async () => {
    const { scrollIntoView, restore } = stubScrollIntoView();
    try {
      render(<LogTerminal logs={makeStartingLogs(LOG_GROUP_WINDOW_SIZE + 10)} />);

      expect(screen.queryAllByTitle('https://example.com/p/1')).toHaveLength(0);

      const firstTick = screen.getAllByRole('button', { name: /^Jump to / })[0];
      fireEvent.click(firstTick);

      await waitFor(() =>
        expect(screen.getAllByTitle('https://example.com/p/1').length).toBeGreaterThan(0),
      );
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
      expect(screen.queryByRole('button', { name: 'Show earlier groups' })).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('reveals a windowed-out issue group via triage navigation', async () => {
    const { scrollIntoView, restore } = stubScrollIntoView();
    try {
      const logs = makeStartingLogs(LOG_GROUP_WINDOW_SIZE + 10);
      logs.splice(1, 0, {
        id: 10_000,
        level: 'error',
        message: '[url:https://example.com/p/1] processing failed for https://example.com/p/1',
        created_at: new Date(Date.parse('2026-04-08T10:00:00Z') + 500).toISOString(),
      });
      render(<LogTerminal logs={logs} />);

      expect(screen.queryAllByTitle('https://example.com/p/1')).toHaveLength(0);

      fireEvent.click(screen.getByRole('button', { name: 'Next' }));

      await waitFor(() =>
        expect(screen.getAllByTitle('https://example.com/p/1').length).toBeGreaterThan(0),
      );
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    } finally {
      restore();
    }
  });
});
