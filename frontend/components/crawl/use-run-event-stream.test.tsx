import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type { RunEvent } from '../../lib/api/types';
import { RUN_EVENT_STREAM } from '../../lib/constants/timing';
import { apiMock, makeRunEvent } from './crawl-run-screen.test-support';
import { useRunEventStream } from './use-run-event-stream';

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

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useRunEventStream socket buffering', () => {
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
    apiMock.getRunEvents.mockResolvedValue([makeRunEvent(1, { kind: 'run.started' })]);
  });

  afterEach(() => {
    if (originalUserAgentDescriptor) {
      Object.defineProperty(window.navigator, 'userAgent', originalUserAgentDescriptor);
    } else {
      Reflect.deleteProperty(window.navigator, 'userAgent');
    }
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function renderStream() {
    let renderCount = 0;
    const view = renderHook(
      () => {
        renderCount += 1;
        return useRunEventStream({
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

  async function settleUntilSocketCount(count = 1) {
    // React Query's fetch resolution interleaves timer jobs, so bare microtask
    // flushes stall under fake timers; advanceTimersByTimeAsync(0) unblocks it.
    for (let round = 0; round < 10 && MockWebSocket.instances.length < count; round += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    }
    expect(MockWebSocket.instances).toHaveLength(count);
  }

  function sendEvent(socket: MockWebSocket, event: RunEvent) {
    socket.onmessage?.({ data: JSON.stringify(event) });
  }

  it('coalesces multiple socket messages into one state update per flush window', async () => {
    const { result, getRenderCount } = renderStream();
    await settleUntilSocketCount();
    const socket = MockWebSocket.instances[0];
    const rendersBefore = getRenderCount();

    act(() => {
      sendEvent(socket, makeRunEvent(2, { kind: 'run.progress' }));
      sendEvent(socket, makeRunEvent(3, { kind: 'run.resumed' }));
      sendEvent(socket, makeRunEvent(4, { kind: 'run.completed' }));
    });

    // Messages sit in the pending buffer: no render, no visible lines yet.
    expect(result.current.events.map((event) => event.kind)).toEqual(['run.started']);
    expect(getRenderCount()).toBe(rendersBefore);

    act(() => {
      vi.advanceTimersByTime(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS);
    });

    expect(result.current.events.map((event) => event.kind)).toEqual([
      'run.started',
      'run.progress',
      'run.resumed',
      'run.completed',
    ]);
    // The whole batch folded into a single state update.
    expect(getRenderCount() - rendersBefore).toBe(1);
  });

  it('flushes buffered Run Events synchronously when the socket closes', async () => {
    const { result } = renderStream();
    await settleUntilSocketCount();
    const socket = MockWebSocket.instances[0];

    act(() => {
      sendEvent(socket, makeRunEvent(2, { kind: 'run.progress' }));
      sendEvent(socket, makeRunEvent(3, { kind: 'run.completed' }));
    });
    expect(result.current.events.map((event) => event.kind)).toEqual(['run.started']);

    await act(async () => {
      socket.onclose?.();
      await vi.advanceTimersByTimeAsync(0);
    });

    // No flush interval elapsed: close delivered the remaining buffer.
    expect(result.current.events.map((event) => event.kind)).toEqual([
      'run.started',
      'run.progress',
      'run.completed',
    ]);
  });

  it('discards malformed WebSocket payloads without moving the sequence cursor', async () => {
    const { result } = renderStream();
    await settleUntilSocketCount();

    act(() => {
      MockWebSocket.instances[0].onmessage?.({ data: JSON.stringify({ id: 2, sequence: 2 }) });
      vi.advanceTimersByTime(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS);
    });

    expect(result.current.events.map((event) => event.sequence)).toEqual([1]);
  });

  it('resets run-scoped socket state and rejects events from the prior run', async () => {
    apiMock.getRunEvents.mockImplementation((runId: number) =>
      Promise.resolve([{ ...makeRunEvent(1, { kind: 'run.started' }), run_id: runId }]),
    );
    const view = renderHook(
      ({ runId }: { runId: number }) =>
        useRunEventStream({
          runId,
          enabled: true,
          live: true,
          refetchRun: () => Promise.resolve(),
        }),
      { initialProps: { runId: 101 }, wrapper: createWrapper() },
    );
    await settleUntilSocketCount();
    const firstSocket = MockWebSocket.instances[0];

    act(() => {
      firstSocket.onopen?.();
      sendEvent(firstSocket, makeRunEvent(2, { kind: 'run.progress' }));
      vi.advanceTimersByTime(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS);
    });
    expect(view.result.current.events.map((event) => event.run_id)).toEqual([101, 101]);
    expect(view.result.current.socketConnected).toBe(true);

    const socketCountBeforeSwitch = MockWebSocket.instances.length;
    view.rerender({ runId: 202 });
    expect(view.result.current.events.every((event) => event.run_id === 202)).toBe(true);
    expect(view.result.current.socketConnected).toBe(false);
    await settleUntilSocketCount(socketCountBeforeSwitch + 1);
    const secondSocket = MockWebSocket.instances.at(-1)!;
    expect(secondSocket.url).toContain('/api/crawls/202/events/ws');
    expect(secondSocket.url).not.toContain('after_sequence=2');

    act(() => {
      sendEvent(secondSocket, { ...makeRunEvent(3), run_id: 101 });
      sendEvent(secondSocket, { ...makeRunEvent(2), run_id: 202 });
      vi.advanceTimersByTime(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS);
    });
    expect(view.result.current.events.map((event) => event.run_id)).toEqual([202, 202]);
  });

  it('preserves the pre-append bottom-pinned viewport state', async () => {
    function StreamHarness() {
      const { liveJumpAvailable, viewportRef } = useRunEventStream({
        runId: 101,
        enabled: true,
        live: true,
        refetchRun: () => Promise.resolve(),
      });
      return (
        <>
          <div ref={viewportRef} data-testid="viewport" />
          <span>{liveJumpAvailable ? 'jump available' : 'bottom pinned'}</span>
        </>
      );
    }

    render(<StreamHarness />, { wrapper: createWrapper() });
    await settleUntilSocketCount();
    const socket = MockWebSocket.instances[0];
    const viewport = screen.getByTestId('viewport');
    let scrollHeight = 100;
    Object.defineProperty(viewport, 'scrollHeight', {
      configurable: true,
      get: () => scrollHeight,
    });
    Object.defineProperty(viewport, 'clientHeight', { configurable: true, value: 50 });
    viewport.scrollTop = 50;
    viewport.dispatchEvent(new Event('scroll'));

    scrollHeight = 150;
    await act(async () => {
      sendEvent(socket, makeRunEvent(2));
      await vi.advanceTimersByTimeAsync(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS + 20);
    });
    expect(viewport.scrollTop).toBe(150);
    expect(screen.getByText('bottom pinned')).toBeInTheDocument();

    viewport.scrollTop = 20;
    viewport.dispatchEvent(new Event('scroll'));
    scrollHeight = 200;
    await act(async () => {
      sendEvent(socket, makeRunEvent(3));
      await vi.advanceTimersByTimeAsync(RUN_EVENT_STREAM.FLUSH_INTERVAL_MS + 20);
    });
    expect(viewport.scrollTop).toBe(20);
    expect(screen.getByText('jump available')).toBeInTheDocument();
  });
});
