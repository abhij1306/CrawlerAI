import { useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlRun } from '../../lib/api/types';
import { getDomain } from '../../lib/format/domain';
import type { HistoryItem } from '../ui/history-drawer';

const HISTORY_LIMIT = 20;

export function useRunHistory(enabled = true) {
  const queryClient = useQueryClient();
  const { data: queryData } = useQuery({
    queryKey: queryKeys.runs.list({ limit: HISTORY_LIMIT }),
    queryFn: ({ signal }) => api.listCrawls({ limit: HISTORY_LIMIT }, { signal }),
    enabled,
  });

  const items: HistoryItem[] = useMemo(
    () =>
      (queryData?.items ?? []).map((run) => ({
        id: run.id,
        status: run.status,
        created_at: run.created_at,
        label: run.url ? getDomain(run.url) : 'Untitled Run',
        meta: `${run.run_type} · ${run.result_summary?.record_count ?? 0} records`,
      })),
    [queryData?.items],
  );
  const prepareRun = useCallback(
    (runId: number) => {
      const run = queryData?.items.find((candidate) => candidate.id === runId);
      if (!run) return;
      queryClient.setQueryData<CrawlRun>(queryKeys.runs.detail(runId), (current) => current ?? run);
    },
    [queryClient, queryData?.items],
  );

  return { items, prepareRun };
}
