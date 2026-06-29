import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlRun } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { POLLING_INTERVALS, RETRY_LIMITS } from '../../lib/constants/timing';
import { cleanRecordForDisplay, type OutputTabKey } from './shared';
import { useTerminalRecordSync } from './use-run-polling';

type UseRunRecordsOptions = {
  runId: number;
  run: CrawlRun | undefined;
  live: boolean;
  terminal: boolean;
  outputTab: OutputTabKey;
  tablePage: number;
  jsonVisibleCount: number;
  verdict: string;
};

export function useRunRecords({
  runId,
  run,
  live,
  terminal,
  outputTab,
  tablePage,
  jsonVisibleCount,
  verdict,
}: Readonly<UseRunRecordsOptions>) {
  // The live/log terminal derives payload previews, coverage, confidence, and
  // per-URL completion state from persisted records. Keep the lightweight
  // table records query active whenever that terminal is visible.
  const shouldFetchTableRecords = live || outputTab === 'table' || outputTab === 'logs';
  const shouldFetchJsonRecords = outputTab === 'json';
  const recordsFetchLimit = Math.min(
    800,
    Math.max(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 2, jsonVisibleCount),
  );
  const tableRecordsLimit = CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4 * tablePage;

  const {
    data: tableRecordsData,
    error: tableRecordsError,
    isFetched: tableRecordsFetched,
    isLoading: isTableRecordsLoading,
    refetch: refetchTableRecords,
  } = useQuery({
    queryKey: queryKeys.runs.tableRecords(runId, tableRecordsLimit),
    queryFn: ({ signal }) =>
      api.getRecords(runId, { page: 1, limit: tableRecordsLimit }, { signal }),
    enabled: shouldFetchTableRecords,
    refetchInterval: live && shouldFetchTableRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: (query) => {
      const cachedPage = query.state.data as { items?: unknown[] } | undefined;
      return live || !cachedPage?.items?.length ? 'always' : false;
    },
  });

  const {
    data: jsonRecordsData,
    error: jsonRecordsError,
    isLoading: isJsonRecordsLoading,
    refetch: refetchJsonRecords,
  } = useQuery({
    queryKey: queryKeys.runs.jsonRecords(runId, recordsFetchLimit),
    queryFn: ({ signal }) => api.getRecords(runId, { limit: recordsFetchLimit }, { signal }),
    enabled: Boolean(run) && shouldFetchJsonRecords,
    refetchInterval: live && shouldFetchJsonRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });

  const jsonRecordsSource = jsonRecordsData ?? tableRecordsData;
  const records = useMemo(() => jsonRecordsSource?.items ?? [], [jsonRecordsSource?.items]);
  const tableRecords = useMemo(() => tableRecordsData?.items ?? [], [tableRecordsData?.items]);
  const tableTotal = tableRecordsData?.meta?.total ?? tableRecords.length;
  const recordsTotal = jsonRecordsSource?.meta?.total ?? records.length;
  const jsonRecords = useMemo(
    () => records.slice(0, Math.min(records.length, jsonVisibleCount)),
    [jsonVisibleCount, records],
  );
  const recordsFetchCapReached = records.length >= recordsFetchLimit && recordsFetchLimit >= 800;
  const hasMoreTableRecords = tableRecords.length < tableTotal;
  const hasMoreJsonRecords =
    jsonRecords.length < records.length ||
    (records.length < recordsTotal && !recordsFetchCapReached);
  const recordsJson = useMemo(
    () =>
      outputTab === 'json' ? JSON.stringify(jsonRecords.map(cleanRecordForDisplay), null, 2) : '',
    [jsonRecords, outputTab],
  );

  const summaryRecordsFromRun = Number(run?.result_summary?.record_count ?? 0) || 0;
  const knownTableRecordsTotal = Math.max(tableTotal, tableRecordsData?.meta?.total ?? 0);
  const terminalRecordsExpected =
    terminal && (summaryRecordsFromRun > 0 || verdict === 'success' || verdict === 'partial');
  // Only sync AFTER the initial table fetch has settled. Before it returns,
  // `tableRecordsData` is undefined and `knownTableRecordsTotal` is 0, which would
  // otherwise look like "records are missing" and fire a redundant refetch of the
  // same query while the initial request is still in flight. Failed initial fetches
  // still count as settled so terminal sync can recover completed runs.
  const tableRecordsSettled = tableRecordsData !== undefined || tableRecordsFetched;
  const terminalRecordsNeedSync =
    tableRecordsSettled &&
    terminalRecordsExpected &&
    knownTableRecordsTotal < Math.max(1, summaryRecordsFromRun);

  useTerminalRecordSync({
    enabled: terminalRecordsNeedSync,
    intervalMs: POLLING_INTERVALS.RECORDS_MS,
    retryLimit: RETRY_LIMITS.TERMINAL_RECORDS_RETRY_LIMIT,
    runId,
    summaryRecordsFromRun,
    tableRecordsLimit,
    updatedAt: run?.updated_at ?? null,
    refetchTableRecords,
  });

  return {
    tableRecordsQuery: {
      error: tableRecordsError,
      isLoading: isTableRecordsLoading,
      refetch: refetchTableRecords,
    },
    jsonRecordsQuery: {
      error: jsonRecordsError,
      isLoading: isJsonRecordsLoading && !jsonRecordsSource,
      refetch: refetchJsonRecords,
    },
    records,
    tableRecords,
    tableTotal,
    recordsTotal,
    jsonRecords,
    hasMoreTableRecords,
    hasMoreJsonRecords,
    recordsJson,
    recordsFetchLimit,
    recordsFetchCapReached,
    tableRecordsLimit,
    summaryRecordsFromRun,
  };
}
