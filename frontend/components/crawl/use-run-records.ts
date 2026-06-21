import { useDeferredValue, useMemo } from 'react';
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
  const shouldFetchTableRecords = Boolean(run) && outputTab === 'table';
  const shouldFetchJsonRecords = Boolean(run) && outputTab === 'json';
  const recordsFetchLimit = Math.min(
    800,
    Math.max(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 2, jsonVisibleCount),
  );
  const tableRecordsLimit = CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4 * tablePage;

  const tableRecordsQuery = useQuery({
    queryKey: queryKeys.runs.tableRecords(runId, tableRecordsLimit),
    queryFn: ({ signal }) =>
      api.getRecords(runId, { page: 1, limit: tableRecordsLimit }, { signal }),
    enabled: shouldFetchTableRecords,
    refetchInterval: live && shouldFetchTableRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });

  const jsonRecordsQuery = useQuery({
    queryKey: queryKeys.runs.jsonRecords(runId, recordsFetchLimit),
    queryFn: ({ signal }) => api.getRecords(runId, { limit: recordsFetchLimit }, { signal }),
    enabled: shouldFetchJsonRecords,
    refetchInterval: live && shouldFetchJsonRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });

  const records = useMemo(() => jsonRecordsQuery.data?.items ?? [], [jsonRecordsQuery.data?.items]);
  const tableRecords = useMemo(
    () => tableRecordsQuery.data?.items ?? [],
    [tableRecordsQuery.data?.items],
  );
  const tableTotal = tableRecordsQuery.data?.meta?.total ?? tableRecords.length;
  const recordsTotal = jsonRecordsQuery.data?.meta?.total ?? records.length;
  const jsonRecords = useMemo(
    () => records.slice(0, Math.min(records.length, jsonVisibleCount)),
    [jsonVisibleCount, records],
  );
  const deferredJsonRecords = useDeferredValue(jsonRecords);
  const recordsFetchCapReached = records.length >= recordsFetchLimit && recordsFetchLimit >= 800;
  const hasMoreTableRecords = tableRecords.length < tableTotal;
  const hasMoreJsonRecords =
    jsonRecords.length < records.length ||
    (records.length < recordsTotal && !recordsFetchCapReached);
  const recordsJson = useMemo(
    () =>
      outputTab === 'json'
        ? JSON.stringify(deferredJsonRecords.map(cleanRecordForDisplay), null, 2)
        : '',
    [deferredJsonRecords, outputTab],
  );

  const summaryRecordsFromRun = Number(run?.result_summary?.record_count ?? 0) || 0;
  const knownTableRecordsTotal = Math.max(tableTotal, tableRecordsQuery.data?.meta?.total ?? 0);
  const terminalRecordsExpected =
    terminal && (summaryRecordsFromRun > 0 || verdict === 'success' || verdict === 'partial');
  const terminalRecordsNeedSync =
    terminalRecordsExpected && knownTableRecordsTotal < Math.max(1, summaryRecordsFromRun);

  useTerminalRecordSync({
    enabled: terminalRecordsNeedSync,
    intervalMs: POLLING_INTERVALS.RECORDS_MS,
    retryLimit: RETRY_LIMITS.TERMINAL_RECORDS_RETRY_LIMIT,
    runId,
    summaryRecordsFromRun,
    recordsFetchLimit,
    tableRecordsLimit,
    updatedAt: run?.updated_at ?? null,
    refetchJsonRecords: jsonRecordsQuery.refetch,
    refetchTableRecords: tableRecordsQuery.refetch,
  });

  return {
    tableRecordsQuery,
    jsonRecordsQuery,
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
