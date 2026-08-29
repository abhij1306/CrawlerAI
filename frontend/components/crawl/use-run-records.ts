import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { crawlsApi } from '../../lib/api/crawls';
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

function nextPage(lastPage: Paginated<CrawlRecord>) {
  const { page, limit, total } = lastPage.meta;
  return page * limit < total ? page + 1 : undefined;
}

function nextJsonPage(lastPage: Paginated<CrawlRecord>) {
  const { page, limit, total } = lastPage.meta;
  const loaded = page * limit;
  return loaded < total && loaded < CRAWL_DEFAULTS.JSON_RECORD_FETCH_CAP ? page + 1 : undefined;
}

function shouldRefetchTableOnMount(live: boolean, cachedData: unknown): 'always' | false {
  const cachedPage = cachedData as { pages?: { items?: unknown[] }[] } | undefined;
  return live || !cachedPage?.pages?.some((page) => page.items?.length) ? 'always' : false;
}

function activeRunInterval(run: CrawlRun | undefined) {
  const createdAt = Date.parse(run?.created_at ?? '');
  return Number.isFinite(createdAt) &&
    Date.now() - createdAt > POLLING_INTERVALS.ACTIVE_JOB_FAST_WINDOW_MS
    ? POLLING_INTERVALS.ACTIVE_JOB_SLOW_MS
    : POLLING_INTERVALS.ACTIVE_JOB_MS;
}

function recordFetchMode(
  live: boolean,
  terminal: boolean,
  outputTab: OutputTabKey,
  run: CrawlRun | undefined,
): { table: boolean; json: boolean; tableInterval: number | false; jsonInterval: number | false } {
  const table = outputTab === 'table' || outputTab === 'events' || terminal;
  const json = outputTab === 'json';
  const interval = activeRunInterval(run);
  return {
    table,
    json,
    tableInterval: live && table ? interval : false,
    jsonInterval: live && json ? interval : false,
  };
}

function terminalSyncState({
  run,
  terminal,
  verdict,
  tableRecordsSettled,
  knownTableRecordsTotal,
}: {
  run: CrawlRun | undefined;
  terminal: boolean;
  verdict: string;
  tableRecordsSettled: boolean;
  knownTableRecordsTotal: number;
}) {
  const summaryRecordsFromRun = Number(run?.result_summary?.record_count ?? 0) || 0;
  const expectsRecords =
    terminal && (summaryRecordsFromRun > 0 || verdict === 'success' || verdict === 'partial');
  return {
    summaryRecordsFromRun,
    needsSync:
      tableRecordsSettled &&
      expectsRecords &&
      knownTableRecordsTotal < Math.max(1, summaryRecordsFromRun),
  };
}

function deriveRecordView({
  tablePages,
  jsonPages,
  jsonVisibleCount,
  outputTab,
}: {
  tablePages: Paginated<CrawlRecord>[];
  jsonPages: Paginated<CrawlRecord>[];
  jsonVisibleCount: number;
  outputTab: OutputTabKey;
}) {
  const tableRecords = tablePages.flatMap((page) => page.items);
  const flattenedJsonRecords = jsonPages.flatMap((page) => page.items);
  const latestTablePage = tablePages.at(-1);
  const latestJsonPage = jsonPages.at(-1);
  const records =
    outputTab === 'json' ? flattenedJsonRecords : (latestTablePage?.items ?? EMPTY_RECORDS);
  const tableTotal = pageTotal(latestTablePage, tableRecords.length);
  const recordsTotal = pageTotal(latestJsonPage, pageTotal(latestTablePage, records.length));
  const jsonRecords = records.slice(0, Math.min(records.length, jsonVisibleCount));
  const recordsFetchCapReached = records.length >= CRAWL_DEFAULTS.JSON_RECORD_FETCH_CAP;
  const hasMoreJsonRecords =
    jsonRecords.length < records.length ||
    (records.length < recordsTotal && !recordsFetchCapReached);
  return {
    records,
    tableRecords,
    tableTotal,
    recordsTotal,
    jsonRecords,
    recordsFetchCapReached,
    hasMoreTableRecords: tableRecords.length < tableTotal,
    hasMoreJsonRecords,
    recordsJson:
      outputTab === 'json' ? JSON.stringify(jsonRecords.map(cleanRecordForDisplay), null, 2) : '',
    latestTablePage,
  };
}

function pageTotal(page: Paginated<CrawlRecord> | undefined, fallback: number) {
  return page?.meta?.total ?? fallback;
}

export function useRunRecords({
  runId,
  run,
  live,
  terminal,
  outputTab,
  jsonVisibleCount,
  verdict,
}: Readonly<UseRunRecordsOptions>) {
  // The live Run Event terminal derives payload previews, coverage, confidence, and
  // per-URL completion state from persisted records. Keep the lightweight
  // table records query active whenever that terminal is visible.
  const fetchMode = recordFetchMode(live, terminal, outputTab, run);
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
      crawlsApi.getRecords(runId, { page: pageParam, limit: tablePageSize }, { signal }),
    initialPageParam: 1,
    getNextPageParam: nextPage,
    enabled: fetchMode.table,
    refetchInterval: fetchMode.tableInterval,
    refetchIntervalInBackground: false,
    refetchOnMount: (query) => shouldRefetchTableOnMount(live, query.state.data),
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
      crawlsApi.getRecords(runId, { page: pageParam, limit: jsonPageSize }, { signal }),
    initialPageParam: 1,
    getNextPageParam: nextJsonPage,
    enabled: Boolean(run) && fetchMode.json,
    refetchInterval: fetchMode.jsonInterval,
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });

  const tablePages = tableRecordsData?.pages ?? EMPTY_RECORD_PAGES;
  const jsonPages = jsonRecordsData?.pages ?? EMPTY_RECORD_PAGES;
  const {
    records,
    tableRecords,
    tableTotal,
    recordsTotal,
    jsonRecords,
    recordsFetchCapReached,
    hasMoreTableRecords,
    hasMoreJsonRecords,
    recordsJson,
    latestTablePage,
  } = useMemo(
    () => deriveRecordView({ tablePages, jsonPages, jsonVisibleCount, outputTab }),
    [jsonPages, jsonVisibleCount, outputTab, tablePages],
  );

  const knownTableRecordsTotal = Math.max(tableTotal, latestTablePage?.meta?.total ?? 0);
  // Only sync AFTER the initial table fetch has settled. Before it returns,
  // `tableRecordsData` is undefined and `knownTableRecordsTotal` is 0, which would
  // otherwise look like "records are missing" and fire a redundant refetch of the
  // same query while the initial request is still in flight. Failed initial fetches
  // still count as settled so terminal sync can recover completed runs.
  const tableRecordsSettled = tableRecordsData !== undefined || tableRecordsFetched;
  const { summaryRecordsFromRun, needsSync: terminalRecordsNeedSync } = terminalSyncState({
    run,
    terminal,
    verdict,
    tableRecordsSettled,
    knownTableRecordsTotal,
  });

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
