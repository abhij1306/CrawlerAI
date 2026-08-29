import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getApiWebSocketBaseUrl } from '@/api/client';
import { queryKeys } from '@/api/query-keys';
import { crawlsApi } from '../../lib/api/crawls';
import { runEventSchema } from '../../lib/api/schemas';
import type { RunEvent } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import {
  POLLING_INTERVALS,
  RUN_EVENT_STREAM,
  WEBSOCKET_RECONNECT,
} from '../../lib/constants/timing';
import { appendLiveRunEvent, mergeRunEvents, scrollViewportToBottom } from './shared';
import { useLiveRunEventAutoScroll } from './use-live-run-event-auto-scroll';

type UseRunEventStreamOptions = {
  runId: number;
  enabled: boolean;
  live: boolean;
  refetchRun: () => Promise<unknown>;
};

type RunEventSocketConnectionOptions = {
  enabled: boolean;
  hasFetchedInitialEvents: boolean;
  live: boolean;
  runId: number;
  refetch: () => Promise<unknown>;
  refetchRun: () => Promise<unknown>;
  cursorRef: RefObject<number | undefined>;
  reconnectAttemptRef: RefObject<number>;
  appendSocketEvents: (events: RunEvent[]) => void;
  setSocketConnected: (connected: boolean) => void;
};

function activeRunEventPollingInterval(liveStartedAt: number) {
  return Date.now() - liveStartedAt < POLLING_INTERVALS.ACTIVE_JOB_FAST_WINDOW_MS
    ? POLLING_INTERVALS.ACTIVE_JOB_MS
    : POLLING_INTERVALS.ACTIVE_JOB_SLOW_MS;
}

function runEventPollingInterval({
  enabled,
  live,
  socketConnected,
  liveStartedAt,
}: {
  enabled: boolean;
  live: boolean;
  socketConnected: boolean;
  liveStartedAt: number;
}) {
  if (!live || !enabled || socketConnected) {
    return false;
  }
  return () => activeRunEventPollingInterval(liveStartedAt);
}

function shouldOpenRunEventSocket({
  enabled,
  live,
  hasFetchedInitialEvents,
}: {
  enabled: boolean;
  live: boolean;
  hasFetchedInitialEvents: boolean;
}) {
  const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
  return (
    enabled &&
    live &&
    hasFetchedInitialEvents &&
    typeof window !== 'undefined' &&
    typeof WebSocket !== 'undefined' &&
    !isJsdom
  );
}

function runEventSocketUrl(runId: number, cursor: number | undefined) {
  const search = new URLSearchParams();
  if (cursor !== undefined) {
    search.set('after_sequence', String(cursor));
  }
  const queryString = search.toString();
  return `${getApiWebSocketBaseUrl()}/api/crawls/${runId}/events/ws${queryString ? `?${queryString}` : ''}`;
}

function reconnectDelayMs(attempt: number) {
  const baseDelay = Math.min(
    WEBSOCKET_RECONNECT.MAX_DELAY_MS,
    WEBSOCKET_RECONNECT.MIN_DELAY_MS * 2 ** attempt,
  );
  return baseDelay + Math.floor(baseDelay * WEBSOCKET_RECONNECT.JITTER_RATIO * Math.random());
}

function parseSocketRunEvent(data: string): RunEvent | null {
  const parsed: unknown = JSON.parse(data);
  const result = runEventSchema.safeParse(parsed);
  return result.success ? result.data : null;
}

function useRunEventSocketConnection({
  enabled,
  hasFetchedInitialEvents,
  live,
  runId,
  refetch,
  refetchRun,
  cursorRef,
  reconnectAttemptRef,
  appendSocketEvents,
  setSocketConnected,
}: RunEventSocketConnectionOptions) {
  const [reconnectState, setReconnectState] = useState(() => ({ runId, token: 0 }));
  const reconnectToken = reconnectState.runId === runId ? reconnectState.token : 0;

  useEffect(() => {
    let shouldReconnect = true;
    let reconnectTimer: number | undefined;
    if (!shouldOpenRunEventSocket({ enabled, live, hasFetchedInitialEvents })) {
      return;
    }

    const socket = new WebSocket(runEventSocketUrl(runId, cursorRef.current));
    // Buffer incoming Run Events and fold them into a single state update per
    // flush window so bursty streams don't trigger a render per message.
    const pendingEvents: RunEvent[] = [];
    const flushPendingEvents = () => {
      if (!pendingEvents.length) {
        return;
      }
      const batch = pendingEvents.splice(0, pendingEvents.length);
      appendSocketEvents(batch);
    };
    const flushTimer = window.setInterval(flushPendingEvents, RUN_EVENT_STREAM.FLUSH_INTERVAL_MS);

    socket.onopen = () => {
      reconnectAttemptRef.current = 0;
      setSocketConnected(true);
    };
    socket.onclose = () => {
      window.clearInterval(flushTimer);
      flushPendingEvents();
      setSocketConnected(false);
      if (!shouldReconnect) return;
      void refetchRun();
      void refetch();
      const attempt = reconnectAttemptRef.current;
      reconnectAttemptRef.current = attempt + 1;
      reconnectTimer = window.setTimeout(() => {
        setReconnectState((current) => ({
          runId,
          token: (current.runId === runId ? current.token : 0) + 1,
        }));
      }, reconnectDelayMs(attempt));
    };
    socket.onerror = () => setSocketConnected(false);
    socket.onmessage = (event) => {
      if (!shouldReconnect) return;
      try {
        const parsed = parseSocketRunEvent(event.data);
        if (!parsed || parsed.run_id !== runId) return;
        cursorRef.current = parsed.sequence;
        pendingEvents.push(parsed);
      } catch {
        // Polling remains the fallback for malformed websocket payloads.
      }
    };

    return () => {
      shouldReconnect = false;
      window.clearInterval(flushTimer);
      flushPendingEvents();
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socket.close();
    };
  }, [
    appendSocketEvents,
    cursorRef,
    enabled,
    hasFetchedInitialEvents,
    live,
    reconnectAttemptRef,
    reconnectToken,
    refetch,
    refetchRun,
    runId,
    setSocketConnected,
  ]);
}

export function useRunEventStream({
  runId,
  enabled,
  live,
  refetchRun,
}: Readonly<UseRunEventStreamOptions>) {
  const [socketEventState, setSocketEventState] = useState<{
    runId: number;
    items: RunEvent[];
  }>(() => ({ runId, items: [] }));
  const [socketConnectionState, setSocketConnectionState] = useState(() => ({
    runId,
    connected: false,
  }));
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const cursorRef = useRef<number | undefined>(undefined);
  const reconnectAttemptRef = useRef(0);
  const [liveStartedAt] = useState(() => Date.now());
  const socketConnected = socketConnectionState.runId === runId && socketConnectionState.connected;
  const appendSocketEvents = useCallback(
    (batch: RunEvent[]) => {
      setSocketEventState((current) => {
        const currentItems = current.runId === runId ? current.items : [];
        return { runId, items: batch.reduce(appendLiveRunEvent, currentItems) };
      });
    },
    [runId],
  );
  const setSocketConnected = useCallback(
    (connected: boolean) => setSocketConnectionState({ runId, connected }),
    [runId],
  );

  useEffect(() => {
    cursorRef.current = undefined;
    reconnectAttemptRef.current = 0;
  }, [runId]);

  const {
    data: queryData,
    error: queryError,
    isFetched: hasFetchedInitialEvents,
    isLoading: isQueryLoading,
    refetch,
  } = useQuery({
    queryKey: queryKeys.runs.events(runId),
    queryFn: ({ signal }) =>
      crawlsApi.getRunEvents(runId, { limit: CRAWL_DEFAULTS.MAX_LIVE_EVENTS }, { signal }),
    enabled,
    refetchInterval: runEventPollingInterval({
      enabled,
      live,
      socketConnected,
      liveStartedAt,
    }),
    refetchIntervalInBackground: false,
  });

  const activeSocketEventItems = useMemo(
    () =>
      (socketEventState.runId === runId ? socketEventState.items : []).filter(
        (event) => event.run_id === runId,
      ),
    [runId, socketEventState],
  );
  const activeQueryEvents = useMemo(
    () => (queryData ?? []).filter((event) => event.run_id === runId),
    [queryData, runId],
  );
  const events = useMemo(
    () => mergeRunEvents(activeQueryEvents, activeSocketEventItems),
    [activeQueryEvents, activeSocketEventItems],
  );
  const lastEventSequence = events.at(-1)?.sequence;

  useEffect(() => {
    if (!activeSocketEventItems.length) {
      cursorRef.current = lastEventSequence;
    }
  }, [activeSocketEventItems.length, lastEventSequence]);

  useRunEventSocketConnection({
    enabled,
    hasFetchedInitialEvents,
    live,
    runId,
    refetch,
    refetchRun,
    cursorRef,
    reconnectAttemptRef,
    appendSocketEvents,
    setSocketConnected,
  });

  const bottomPinnedRef = useLiveRunEventAutoScroll({
    live,
    events,
    setLiveJumpAvailable,
    viewportRef,
  });

  function jumpToLatest() {
    scrollViewportToBottom(viewportRef);
    bottomPinnedRef.current = true;
    setLiveJumpAvailable(false);
  }

  const connected = enabled && live && socketConnected;
  return {
    query: {
      error: queryError,
      refetch,
      isLoading: isQueryLoading,
    },
    events,
    socketConnected: connected,
    online: connected,
    liveJumpAvailable,
    viewportRef,
    jumpToLatest,
  };
}
