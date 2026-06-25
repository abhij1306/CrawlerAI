import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getApiWebSocketBaseUrl } from '@/api/client';
import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlLog } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { POLLING_INTERVALS } from '../../lib/constants/timing';
import { mergeLogs, scrollViewportToBottom } from './shared';

type UseRunLogStreamOptions = {
  runId: number;
  enabled: boolean;
  live: boolean;
  refetchRun: () => Promise<unknown>;
};

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

  const {
    data: queryData,
    error: queryError,
    isFetched: hasFetchedInitialLogs,
    isLoading: isQueryLoading,
    refetch,
  } = useQuery({
    queryKey: queryKeys.runs.logs(runId),
    queryFn: ({ signal }) =>
      api.getCrawlLogs(runId, { limit: CRAWL_DEFAULTS.MAX_LIVE_LOGS }, { signal }),
    enabled,
    refetchInterval: live && enabled && !socketConnected ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
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
    const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
    if (
      !enabled ||
      !live ||
      !hasFetchedInitialLogs ||
      typeof window === 'undefined' ||
      typeof WebSocket === 'undefined' ||
      isJsdom
    ) {
      return;
    }

    const search = new URLSearchParams();
    if (cursorRef.current !== undefined) {
      search.set('after_id', String(cursorRef.current));
    }
    const queryString = search.toString();
    const socket = new WebSocket(
      `${getApiWebSocketBaseUrl()}/api/crawls/${runId}/logs/ws${queryString ? `?${queryString}` : ''}`,
    );

    socket.onopen = () => setSocketConnected(true);
    socket.onclose = () => {
      setSocketConnected(false);
      void refetchRun();
      void refetch();
    };
    socket.onerror = () => setSocketConnected(false);
    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as CrawlLog;
        if (!parsed || typeof parsed.id !== 'number') {
          return;
        }
        cursorRef.current = parsed.id;
        setSocketLogItems((current) => mergeLogs(current, [parsed]));
      } catch {
        // Polling remains the fallback for malformed websocket payloads.
      }
    };

    return () => socket.close();
  }, [enabled, hasFetchedInitialLogs, live, refetch, refetchRun, runId]);

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
  }, [live, logs]);

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
