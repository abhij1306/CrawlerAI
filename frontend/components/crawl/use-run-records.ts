import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlRecord, CrawlRun, Paginated } from '../../lib/api/types';
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
  jsonVisibleCount: number;
  verdict: string;
};

const EMPTY_RECORD_PAGES: Paginated<CrawlRecord>[] = [];
const EMPTY_RECORDS: CrawlRecord[] = [];

export function useRunRecords({
  runId,
  run,
  live,
  terminal,
  outputTab,
  jsonVisibleCount,
  verdict,
}: Readonly<UseRunRecordsOptions>) {
  // The live/log terminal derives payload previews, coverage, confidence, and
  // per-URL completion state from persisted records. Keep the lightweight
  // table records query active whenever that terminal is visible.
  const shouldFetchTableRecords = live || outputTab === 'table' || outputTab === 'logs';
  const shouldFetchJsonRecords = outputTab === 'json';
  const tablePageSize = CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4;
  const jsonPageSize = CRAWL_DEFAULTS.TABLE_PAGE_SIZE;

  const {
    data: tableRecordsData,
    error: tableRecordsError,
    isFetched: tableRecordsFetched,
    isLoading: isTableRecordsLoading,
    isFetchingNextPage: isFetchingNextTablePage,
    fetchNextPage: fetchNextTablePage,
    refetch: refetchTableRecords,
  } = useInfiniteQuery({
    queryKey: queryKeys.runs.tableRecords(runId, tablePageSize),
    queryFn: ({ pageParam, signal }) =>
      api.getRecords(runId, { page: pageParam, limit: tablePageSize }, { signal }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const { page, limit, total } = lastPage.meta;
      return page * limit < total ? page + 1 : undefined;
    },
    enabled: shouldFetchTableRecords,
    refetchInterval: live && shouldFetchTableRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: (query) => {
      const cachedPage = query.state.data as { pages?: { items?: unknown[] }[] } | undefined;
      return live || !cachedPage?.pages?.some((page) => page.items?.length) ? 'always' : false;
    },
  });

  const {
    data: jsonRecordsData,
    error: jsonRecordsError,
    isLoading: isJsonRecordsLoading,
    isFetchingNextPage: isFetchingNextJsonPage,
    fetchNextPage: fetchNextJsonPage,
    refetch: refetchJsonRecords,
  } = useInfiniteQuery({
    queryKey: queryKeys.runs.jsonRecords(runId, jsonPageSize),
    queryFn: ({ pageParam, signal }) =>
      api.getRecords(runId, { page: pageParam, limit: jsonPageSize }, { signal }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const { page, limit, total } = lastPage.meta;
      return page * limit < total && page * limit < 800 ? page + 1 : undefined;
    },
    enabled: Boolean(run) && shouldFetchJsonRecords,
    refetchInterval: live && shouldFetchJsonRecords ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });

  const tablePages = tableRecordsData?.pages ?? EMPTY_RECORD_PAGES;
  const jsonPages = jsonRecordsData?.pages ?? EMPTY_RECORD_PAGES;
  const flattenedTableRecords = useMemo(
    () => tablePages.flatMap((page) => page.items),
    [tablePages],
  );
  const flattenedJsonRecords = useMemo(() => jsonPages.flatMap((page) => page.items), [jsonPages]);
  const latestTablePage = tablePages.at(-1);
  const latestJsonPage = jsonPages.at(-1);
  const records = shouldFetchJsonRecords
    ? flattenedJsonRecords
    : (latestTablePage?.items ?? EMPTY_RECORDS);
  const tableRecords = flattenedTableRecords;
  const tableTotal = latestTablePage?.meta?.total ?? tableRecords.length;
  const recordsTotal =
    latestJsonPage?.meta?.total ?? latestTablePage?.meta?.total ?? records.length;
  const jsonRecords = useMemo(
    () => records.slice(0, Math.min(records.length, jsonVisibleCount)),
    [jsonVisibleCount, records],
  );
  const recordsFetchCapReached = records.length >= 800;
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
  const knownTableRecordsTotal = Math.max(tableTotal, latestTablePage?.meta?.total ?? 0);
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
    tableRecordsLimit: tablePageSize,
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
      isLoading: isJsonRecordsLoading && !records.length,
      refetch: refetchJsonRecords,
    },
    records,
    tableRecords,
    tableTotal,
    recordsTotal,
    jsonRecords,
    hasMoreTableRecords,
    fetchNextTablePage,
    fetchNextJsonPage,
    isFetchingNextTablePage,
    isFetchingNextJsonPage,
    hasMoreJsonRecords,
    recordsJson,
    recordsFetchLimit: jsonPageSize,
    recordsFetchCapReached,
    tableRecordsLimit: tablePageSize,
    summaryRecordsFromRun,
  };
}
