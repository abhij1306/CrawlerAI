import { useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, RefObject, SetStateAction } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getApiWebSocketBaseUrl } from '@/api/client';
import { queryKeys } from '@/api/query-keys';
import { crawlsApi } from '../../lib/api/crawls';
import type { CrawlLog } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { POLLING_INTERVALS, WEBSOCKET_RECONNECT } from '../../lib/constants/timing';
import { appendLiveLog, mergeLogs, scrollViewportToBottom } from './shared';

type UseRunLogStreamOptions = {
  runId: number;
  enabled: boolean;
  live: boolean;
  refetchRun: () => Promise<unknown>;
};

type LogSocketConnectionOptions = {
  enabled: boolean;
  hasFetchedInitialLogs: boolean;
  live: boolean;
  runId: number;
  refetch: () => Promise<unknown>;
  refetchRun: () => Promise<unknown>;
  cursorRef: RefObject<number | undefined>;
  reconnectAttemptRef: RefObject<number>;
  setSocketConnected: Dispatch<SetStateAction<boolean>>;
  setSocketLogItems: Dispatch<SetStateAction<CrawlLog[]>>;
};

function activeLogPollingInterval(liveStartedAt: number) {
  return Date.now() - liveStartedAt < POLLING_INTERVALS.ACTIVE_JOB_FAST_WINDOW_MS
    ? POLLING_INTERVALS.ACTIVE_JOB_MS
    : POLLING_INTERVALS.ACTIVE_JOB_SLOW_MS;
}

function logPollingInterval({
  enabled,
  live,
  socketConnected,
  liveStartedAtRef,
}: {
  enabled: boolean;
  live: boolean;
  socketConnected: boolean;
  liveStartedAtRef: RefObject<number>;
}) {
  if (!live || !enabled || socketConnected) {
    return false;
  }
  return () => activeLogPollingInterval(liveStartedAtRef.current);
}

function shouldOpenLogSocket({
  enabled,
  live,
  hasFetchedInitialLogs,
}: {
  enabled: boolean;
  live: boolean;
  hasFetchedInitialLogs: boolean;
}) {
  const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
  return (
    enabled &&
    live &&
    hasFetchedInitialLogs &&
    typeof window !== 'undefined' &&
    typeof WebSocket !== 'undefined' &&
    !isJsdom
  );
}

function logSocketUrl(runId: number, cursor: number | undefined) {
  const search = new URLSearchParams();
  if (cursor !== undefined) {
    search.set('after_id', String(cursor));
  }
  const queryString = search.toString();
  return `${getApiWebSocketBaseUrl()}/api/crawls/${runId}/logs/ws${queryString ? `?${queryString}` : ''}`;
}

function reconnectDelayMs(attempt: number) {
  const baseDelay = Math.min(
    WEBSOCKET_RECONNECT.MAX_DELAY_MS,
    WEBSOCKET_RECONNECT.MIN_DELAY_MS * 2 ** attempt,
  );
  return baseDelay + Math.floor(baseDelay * WEBSOCKET_RECONNECT.JITTER_RATIO * Math.random());
}

function parseSocketLog(data: string) {
  const parsed = JSON.parse(data) as CrawlLog;
  return parsed && typeof parsed.id === 'number' ? parsed : null;
}

function useLiveLogAutoScroll({
  live,
  logs,
  setLiveJumpAvailable,
  viewportRef,
}: {
  live: boolean;
  logs: CrawlLog[];
  setLiveJumpAvailable: (available: boolean) => void;
  viewportRef: RefObject<HTMLDivElement | null>;
}) {
  useEffect(() => {
    if (!live || !viewportRef.current) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const node = viewportRef.current;
      if (!node) {
        return;
      }
      const atBottom =
        node.scrollHeight - node.scrollTop - node.clientHeight < CRAWL_DEFAULTS.SCROLL_THRESHOLD_PX;
      if (atBottom) {
        node.scrollTop = node.scrollHeight;
        setLiveJumpAvailable(false);
      } else {
        setLiveJumpAvailable(true);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [live, logs, setLiveJumpAvailable, viewportRef]);
}

function useLogSocketConnection({
  enabled,
  hasFetchedInitialLogs,
  live,
  runId,
  refetch,
  refetchRun,
  cursorRef,
  reconnectAttemptRef,
  setSocketConnected,
  setSocketLogItems,
}: LogSocketConnectionOptions) {
  const [reconnectToken, setReconnectToken] = useState(0);

  useEffect(() => {
    let shouldReconnect = true;
    let reconnectTimer: number | undefined;
    if (!shouldOpenLogSocket({ enabled, live, hasFetchedInitialLogs })) {
      return;
    }

    const socket = new WebSocket(logSocketUrl(runId, cursorRef.current));

    socket.onopen = () => {
      reconnectAttemptRef.current = 0;
      setSocketConnected(true);
    };
    socket.onclose = () => {
      setSocketConnected(false);
      void refetchRun();
      void refetch();
      if (!shouldReconnect) {
        return;
      }
      const attempt = reconnectAttemptRef.current;
      reconnectAttemptRef.current = attempt + 1;
      reconnectTimer = window.setTimeout(() => {
        setReconnectToken((current) => current + 1);
      }, reconnectDelayMs(attempt));
    };
    socket.onerror = () => setSocketConnected(false);
    socket.onmessage = (event) => {
      try {
        const parsed = parseSocketLog(event.data);
        if (!parsed) return;
        cursorRef.current = parsed.id;
        setSocketLogItems((current) => appendLiveLog(current, parsed));
      } catch {
        // Polling remains the fallback for malformed websocket payloads.
      }
    };

    return () => {
      shouldReconnect = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socket.close();
    };
  }, [
    cursorRef,
    enabled,
    hasFetchedInitialLogs,
    live,
    reconnectAttemptRef,
    reconnectToken,
    refetch,
    refetchRun,
    runId,
    setSocketConnected,
    setSocketLogItems,
  ]);
}

export function useRunLogStream({
  runId,
  enabled,
  live,
  refetchRun,
}: Readonly<UseRunLogStreamOptions>) {
  const [socketLogItems, setSocketLogItems] = useState<CrawlLog[]>([]);
  const [socketConnected, setSocketConnected] = useState(false);
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const cursorRef = useRef<number | undefined>(undefined);
  const reconnectAttemptRef = useRef(0);
  const liveStartedAtRef = useRef(-1);
  if (liveStartedAtRef.current === -1) {
    liveStartedAtRef.current = Date.now();
  }
  const wasLiveRef = useRef(false);

  const {
    data: queryData,
    error: queryError,
    isFetched: hasFetchedInitialLogs,
    isLoading: isQueryLoading,
    refetch,
  } = useQuery({
    queryKey: queryKeys.runs.logs(runId),
    queryFn: ({ signal }) =>
      crawlsApi.getCrawlLogs(runId, { limit: CRAWL_DEFAULTS.MAX_LIVE_LOGS }, { signal }),
    enabled,
    refetchInterval: logPollingInterval({
      enabled,
      live,
      socketConnected,
      liveStartedAtRef,
    }),
    refetchIntervalInBackground: false,
  });

  const logs = useMemo(
    () => mergeLogs(queryData ?? [], socketLogItems),
    [queryData, socketLogItems],
  );
  const lastLogId = logs.at(-1)?.id;

  useEffect(() => {
    if (!socketLogItems.length) {
      cursorRef.current = lastLogId;
    }
  }, [lastLogId, socketLogItems.length]);

  useEffect(() => {
    const isLive = live && enabled;
    if (isLive && !wasLiveRef.current) {
      liveStartedAtRef.current = Date.now();
      reconnectAttemptRef.current = 0;
    }
    if (!isLive) {
      setSocketConnected(false);
    }
    wasLiveRef.current = isLive;
  }, [enabled, live, runId]);

  useLogSocketConnection({
    enabled,
    hasFetchedInitialLogs,
    live,
    runId,
    refetch,
    refetchRun,
    cursorRef,
    reconnectAttemptRef,
    setSocketConnected,
    setSocketLogItems,
  });

  useLiveLogAutoScroll({ live, logs, setLiveJumpAvailable, viewportRef });

  function jumpToLatest() {
    scrollViewportToBottom(viewportRef);
    setLiveJumpAvailable(false);
  }

  return {
    query: {
      error: queryError,
      refetch,
      isLoading: isQueryLoading,
    },
    logs,
    socketConnected,
    online: enabled && socketConnected,
    liveJumpAvailable,
    viewportRef,
    jumpToLatest,
  };
}
