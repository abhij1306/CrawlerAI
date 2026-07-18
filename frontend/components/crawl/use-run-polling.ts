import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import type { CrawlRun } from '../../lib/api/types';
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from '../../lib/constants/crawl-statuses';

type RefetchableQuery = {
  refetch: () => Promise<unknown>;
};

type TerminalRecordSyncOptions = {
  enabled: boolean;
  intervalMs: number;
  retryLimit: number;
  runId: number;
  summaryRecordsFromRun: number;
  tableRecordsLimit: number;
  updatedAt: string | null;
  refetchTableRecords: () => Promise<unknown>;
};

export function useRunStatusFlags(run: CrawlRun | undefined) {
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const terminal = Boolean(run && TERMINAL_STATUSES.has(run.status));
  return { live, terminal };
}

export function useLiveClock(live: boolean) {
  const [localNow, setLocalNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return;
    const interval = window.setInterval(() => setLocalNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [live]);

  return localNow;
}

export function useTerminalSync(
  run: CrawlRun | undefined,
  terminal: boolean,
  queries: ReadonlyArray<RefetchableQuery>,
) {
  const terminalSyncRef = useRef<string | null>(null);
  const liveRunIdRef = useRef<number | null>(null);
  const queriesRef = useRef(queries);
  queriesRef.current = queries;

  useEffect(() => {
    if (!run) {
      liveRunIdRef.current = null;
      terminalSyncRef.current = null;
      return;
    }
    if (ACTIVE_STATUSES.has(run.status)) {
      liveRunIdRef.current = run.id;
      terminalSyncRef.current = null;
      return;
    }
    if (!terminal || liveRunIdRef.current !== run.id) {
      return;
    }

    const syncKey = `${run.id}:${run.status}:${run.completed_at ?? ''}:${run.updated_at}`;
    if (terminalSyncRef.current === syncKey) {
      return;
    }
    terminalSyncRef.current = syncKey;

    void Promise.allSettled(queriesRef.current.map((query) => query.refetch()));
  }, [run, terminal]);
}

export function useTerminalRecordSync({
  enabled,
  intervalMs,
  retryLimit,
  runId,
  summaryRecordsFromRun,
  tableRecordsLimit,
  updatedAt,
  refetchTableRecords,
}: Readonly<TerminalRecordSyncOptions>) {
  const [retryState, setRetryState] = useState<{
    attempts: number;
    key: string | null;
  }>({ attempts: 0, key: null });

  const syncKey = enabled
    ? [runId, updatedAt ?? '', summaryRecordsFromRun, tableRecordsLimit].join(':')
    : null;
  const retryAttempts = retryState.key === syncKey ? retryState.attempts : 0;
  const retryEnabled = enabled && retryAttempts < retryLimit;

  useQuery({
    queryKey: queryKeys.runs.terminalRecordSync(syncKey),
    queryFn: async () => {
      setRetryState((current) => ({
        key: syncKey,
        attempts: current.key === syncKey ? current.attempts + 1 : 1,
      }));
      await refetchTableRecords();
      return null;
    },
    enabled: retryEnabled,
    refetchInterval: retryEnabled ? intervalMs : false,
    refetchIntervalInBackground: false,
    refetchOnMount: true,
    staleTime: 0,
    gcTime: 0,
  });
}
