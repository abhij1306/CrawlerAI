import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vite-plus/test';

import type { RunEvent } from '../../lib/api/types';
import { RunEventTerminal } from './run-event-terminal';
import { RUN_EVENT_GROUP_WINDOW_SIZE } from './run-event-terminal-utils';

const ZEBRA_CLASS = 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]';

function makeUrlEvents(count: number): RunEvent[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    run_id: 101,
    sequence: index + 1,
    kind: 'url.started',
    stage: null,
    url: `https://example.com/p/${index + 1}`,
    url_scope_id: `p${index + 1}`,
    severity: 'info',
    outcome: 'progress',
    reason_code: null,
    facts: { index: index + 1, total: count },
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

describe('RunEventTerminal group windowing', () => {
  it('shows a persistence failure in the collapsed group summary', () => {
    const events: RunEvent[] = [
      {
        ...makeUrlEvents(1)[0],
        stage: 'acquisition',
      },
      {
        ...makeUrlEvents(1)[0],
        id: 2,
        sequence: 2,
        kind: 'persistence.failed',
        stage: 'persistence',
        severity: 'error',
        outcome: 'failed',
        facts: { exception_type: 'IntegrityError' },
      },
    ];

    render(<RunEventTerminal events={events} />);

    expect(screen.getByTitle('persistence.failed')).toHaveTextContent(
      /Persistence Failed:.*IntegrityError/,
    );
  });

  it('keeps zebra striping stable when the sliding window drops a group', () => {
    const allEvents = makeUrlEvents(RUN_EVENT_GROUP_WINDOW_SIZE + 2);
    const { rerender } = render(
      <RunEventTerminal events={allEvents.slice(0, RUN_EVENT_GROUP_WINDOW_SIZE + 1)} />,
    );

    // p/3 is absolute index 2 (even → striped), p/4 is absolute index 3 (odd → plain).
    const stripedBefore = rowClassFor('https://example.com/p/3');
    const plainBefore = rowClassFor('https://example.com/p/4');
    expect(stripedBefore).toContain(ZEBRA_CLASS);
    expect(plainBefore).not.toContain(ZEBRA_CLASS);

    // The window slides by one: both rows shift one window-relative position.
    rerender(<RunEventTerminal events={allEvents} />);

    expect(rowClassFor('https://example.com/p/3')).toBe(stripedBefore);
    expect(rowClassFor('https://example.com/p/4')).toBe(plainBefore);
  });

  it('reveals a windowed-out group when jumping to it from the timeline', async () => {
    const { scrollIntoView, restore } = stubScrollIntoView();
    try {
      render(<RunEventTerminal events={makeUrlEvents(RUN_EVENT_GROUP_WINDOW_SIZE + 10)} />);

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
      const events = makeUrlEvents(RUN_EVENT_GROUP_WINDOW_SIZE + 10);
      events.splice(1, 0, {
        id: 10_000,
        run_id: 101,
        sequence: 10_000,
        kind: 'url.failed',
        stage: 'extraction',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        severity: 'error',
        outcome: 'failed',
        reason_code: 'processing_failed',
        facts: {},
        created_at: new Date(Date.parse('2026-04-08T10:00:00Z') + 500).toISOString(),
      });
      render(<RunEventTerminal events={events} />);

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
