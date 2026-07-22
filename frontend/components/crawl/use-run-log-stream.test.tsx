import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type { CrawlLog } from '../../lib/api/types';
import { LOG_STREAM } from '../../lib/constants/timing';
import { useRunLogStream } from './use-run-log-stream';

const apiMock = vi.hoisted(() => ({
  getCrawlLogs: vi.fn(),
}));

vi.mock('../../lib/api/crawls', () => ({
  crawlsApi: {
    getCrawlLogs: apiMock.getCrawlLogs,
  },
}));

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

function makeLog(id: number, message: string): CrawlLog {
  return {
    id,
    level: 'info',
    message,
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useRunLogStream socket buffering', () => {
  let originalUserAgentDescriptor: PropertyDescriptor | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    originalUserAgentDescriptor = Object.getOwnPropertyDescriptor(window.navigator, 'userAgent');
    vi.clearAllMocks();
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
    Object.defineProperty(window.navigator, 'userAgent', {
      configurable: true,
      value: 'Mozilla/5.0',
    });
    apiMock.getCrawlLogs.mockResolvedValue([makeLog(1, 'First log line')]);
  });

  afterEach(() => {
    if (originalUserAgentDescriptor) {
      Object.defineProperty(window.navigator, 'userAgent', originalUserAgentDescriptor);
    }
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function renderStream() {
    let renderCount = 0;
    const view = renderHook(
      () => {
        renderCount += 1;
        return useRunLogStream({
          runId: 101,
          enabled: true,
          live: true,
          refetchRun: () => Promise.resolve(),
        });
      },
      { wrapper: createWrapper() },
    );
    return { ...view, getRenderCount: () => renderCount };
  }

  async function settleUntilSocketOpen() {
    // React Query's fetch resolution interleaves timer jobs, so bare microtask
    // flushes stall under fake timers; advanceTimersByTimeAsync(0) unblocks it.
    for (let round = 0; round < 10 && MockWebSocket.instances.length === 0; round += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    }
    expect(MockWebSocket.instances).toHaveLength(1);
  }

  function sendLog(socket: MockWebSocket, log: CrawlLog) {
    socket.onmessage?.({ data: JSON.stringify(log) });
  }

  it('coalesces multiple socket messages into one state update per flush window', async () => {
    const { result, getRenderCount } = renderStream();
    await settleUntilSocketOpen();
    const socket = MockWebSocket.instances[0];
    const rendersBefore = getRenderCount();

    act(() => {
      sendLog(socket, makeLog(2, 'Line two'));
      sendLog(socket, makeLog(3, 'Line three'));
      sendLog(socket, makeLog(4, 'Line four'));
    });

    // Messages sit in the pending buffer: no render, no visible lines yet.
    expect(result.current.logs.map((log) => log.message)).toEqual(['First log line']);
    expect(getRenderCount()).toBe(rendersBefore);

    act(() => {
      vi.advanceTimersByTime(LOG_STREAM.FLUSH_INTERVAL_MS);
    });

    expect(result.current.logs.map((log) => log.message)).toEqual([
      'First log line',
      'Line two',
      'Line three',
      'Line four',
    ]);
    // The whole batch folded into a single state update.
    expect(getRenderCount() - rendersBefore).toBe(1);
  });

  it('flushes the buffered logs synchronously when the socket closes', async () => {
    const { result } = renderStream();
    await settleUntilSocketOpen();
    const socket = MockWebSocket.instances[0];

    act(() => {
      sendLog(socket, makeLog(2, 'Line two'));
      sendLog(socket, makeLog(3, 'Line three'));
    });
    expect(result.current.logs.map((log) => log.message)).toEqual(['First log line']);

    await act(async () => {
      socket.onclose?.();
      await vi.advanceTimersByTimeAsync(0);
    });

    // No flush interval elapsed: close delivered the remaining buffer.
    expect(result.current.logs.map((log) => log.message)).toEqual([
      'First log line',
      'Line two',
      'Line three',
    ]);
  });
});
