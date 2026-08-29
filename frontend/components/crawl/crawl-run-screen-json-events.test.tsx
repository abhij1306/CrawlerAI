import {
  apiMock,
  makeRunEvent,
  makeRecord,
  MockWebSocket,
  registerCrawlRunScreenTestLifecycle,
  renderRunScreen,
  runningRun,
} from './crawl-run-screen.test-support';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vite-plus/test';
import { WEBSOCKET_RECONNECT } from '../../lib/constants/timing';

describe('CrawlRunScreen', () => {
  registerCrawlRunScreenTestLifecycle();

  it('keeps payload peek limited to the cleaned JSON record', async () => {
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          data: {
            title: 'Item 1',
            url: 'https://example.com/p/1',
            _internal_metric: 'hidden',
          },
          raw_data: {
            _confidence: { score: 0.4 },
          },
          source_trace: {
            acquisition: { final_url: 'https://example.com/p/1' },
          },
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });
    apiMock.getRunEvents.mockResolvedValue([
      makeRunEvent(1, { kind: 'url.started', url: 'https://example.com/p/1', url_scope_id: 'p1' }),
      makeRunEvent(2, {
        kind: 'persistence.succeeded',
        stage: 'persistence',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
    ]);

    renderRunScreen();

    fireEvent.click(await screen.findByRole('button', { name: 'Run Events' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Peek' }));

    expect(await screen.findByText('Payload Peek')).toBeInTheDocument();
    expect(screen.getByText(/"title": "Item 1"/)).toBeInTheDocument();
    expect(screen.queryByText(/raw_data/)).not.toBeInTheDocument();
    expect(screen.queryByText(/source_trace/)).not.toBeInTheDocument();
    expect(screen.queryByText(/_confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/_internal_metric/)).not.toBeInTheDocument();
  });

  it('does not reopen the Run Event websocket when incoming events advance the sequence cursor', async () => {
    apiMock.getCrawl.mockResolvedValue(runningRun(101));
    apiMock.getRunEvents.mockResolvedValue([makeRunEvent(1, { kind: 'run.started' })]);

    renderRunScreen();

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });
    expect(MockWebSocket.instances[0].url).toContain('after_sequence=1');

    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify(makeRunEvent(2, { kind: 'run.resumed' })),
    });

    expect(await screen.findByText('Run Resumed')).toBeInTheDocument();
    vi.spyOn(Math, 'random').mockReturnValue(0);
    vi.useFakeTimers();
    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].onclose?.();
    });
    await act(async () => {
      vi.advanceTimersByTime(WEBSOCKET_RECONNECT.MIN_DELAY_MS);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toContain('after_sequence=2');
  });

  it('reconnects the Run Event websocket after a transient close while polling remains available', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    apiMock.getCrawl.mockResolvedValue(runningRun(101));
    apiMock.getRunEvents.mockResolvedValue([makeRunEvent(1, { kind: 'run.started' })]);

    renderRunScreen();

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    vi.useFakeTimers();
    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].onclose?.();
    });

    expect(apiMock.getRunEvents).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(WEBSOCKET_RECONNECT.MIN_DELAY_MS);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toContain('after_sequence=1');
  });

  it('does not reconnect the Run Event websocket after unmount', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    apiMock.getCrawl.mockResolvedValue(runningRun(101));
    apiMock.getRunEvents.mockResolvedValue([makeRunEvent(1, { kind: 'run.started' })]);

    const { unmount } = renderRunScreen();

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    vi.useFakeTimers();
    unmount();
    act(() => {
      MockWebSocket.instances[0].onclose?.();
      vi.advanceTimersByTime(WEBSOCKET_RECONNECT.MAX_DELAY_MS);
    });

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('keeps final per-url duration from the latest persisted record timestamp', async () => {
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          data: {
            title: 'Item 1',
            url: 'https://example.com/p/1',
          },
          raw_data: {
            _confidence: { score: 0.4 },
          },
          source_trace: {
            acquisition: {
              final_url: 'https://example.com/p/1',
              browser_diagnostics: {
                phase_timings_ms: { total: 9000 },
              },
            },
          },
          created_at: new Date('2026-04-08T10:00:42Z').toISOString(),
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });
    apiMock.getRunEvents.mockResolvedValue([
      makeRunEvent(1, { kind: 'url.started', url: 'https://example.com/p/1', url_scope_id: 'p1' }),
      makeRunEvent(2, {
        kind: 'persistence.succeeded',
        stage: 'persistence',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
    ]);

    renderRunScreen();

    fireEvent.click(await screen.findByRole('button', { name: 'Run Events' }));

    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(screen.getByText('0m 42s')).toBeInTheDocument();
  });
});
