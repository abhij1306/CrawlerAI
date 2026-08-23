import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { crawlsApi } from '../../lib/api/crawls';
import type { CrawlRun } from '../../lib/api/types';
import { parseApiDate } from '../../lib/format/date';
import { ACTIVE_STATUSES } from '../../lib/constants/crawl-statuses';
import { POLLING_INTERVALS } from '../../lib/constants/timing';
import { useRunStatusFlags } from './use-run-polling';

function isFailedWithoutRecords(run: CrawlRun | undefined) {
  if (!run) return false;
  const failedStatus = run.status === 'failed' || run.status === 'proxy_exhausted';
  return failedStatus && Number(run.result_summary?.record_count ?? 0) === 0;
}

export function workspaceRunState(
  run: CrawlRun | undefined,
  terminal: boolean,
  sessionStartMs: number,
) {
  const createdMs = run?.created_at ? parseApiDate(run.created_at).getTime() : null;
  return {
    effectiveStartMs: createdMs ?? sessionStartMs,
    failedRunWithoutRecords: isFailedWithoutRecords(run),
    showLearningTab: Boolean(run?.run_type === 'crawl' && terminal),
    requestedFields: run?.requested_fields ?? [],
  };
}

export function followUpVisibility({
  listingRun,
  ecommerceDetailRun,
  batchCount,
  productIntelligenceCount,
  dataEnrichmentCount,
}: {
  listingRun: boolean;
  ecommerceDetailRun: boolean;
  batchCount: number;
  productIntelligenceCount: number;
  dataEnrichmentCount: number;
}) {
  return {
    showBatch: listingRun && batchCount > 0,
    showProductIntelligence: (listingRun || ecommerceDetailRun) && productIntelligenceCount > 0,
    showDataEnrichment: ecommerceDetailRun && dataEnrichmentCount > 0,
  };
}

export function useRunWorkspace(runId: number) {
  const {
    data: run,
    error,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: queryKeys.runs.detail(runId),
    queryFn: ({ signal }) => crawlsApi.getCrawl(runId, { signal }),
    refetchInterval: (query) => {
      const currentRun = query.state.data as CrawlRun | undefined;
      if (!currentRun || !ACTIVE_STATUSES.has(currentRun.status)) {
        return false;
      }
      const createdAt = Date.parse(currentRun.created_at);
      return Number.isFinite(createdAt) &&
        Date.now() - createdAt > POLLING_INTERVALS.ACTIVE_JOB_FAST_WINDOW_MS
        ? POLLING_INTERVALS.ACTIVE_JOB_SLOW_MS
        : POLLING_INTERVALS.ACTIVE_JOB_MS;
    },
    refetchIntervalInBackground: false,
    refetchOnMount: (query) => {
      const cachedRun = query.state.data as CrawlRun | undefined;
      return !cachedRun || ACTIVE_STATUSES.has(cachedRun.status) ? 'always' : false;
    },
  });
  const { live, terminal } = useRunStatusFlags(run);

  return {
    runQuery: {
      error,
      isLoading,
      refetch,
    },
    run,
    live,
    terminal,
  };
}
