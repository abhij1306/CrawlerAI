import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import { getDomain } from '../../lib/format/domain';
import type { HistoryItem } from '../ui/history-drawer';

const HISTORY_LIMIT = 20;

export function useRunHistory() {
  const query = useQuery({
    queryKey: queryKeys.runs.list({ limit: HISTORY_LIMIT }),
    queryFn: ({ signal }) => api.listCrawls({ limit: HISTORY_LIMIT }, { signal }),
  });

  const items: HistoryItem[] = useMemo(
    () =>
      (query.data?.items ?? []).map((run) => ({
        id: run.id,
        status: run.status,
        created_at: run.created_at,
        label: run.url ? getDomain(run.url) : 'Untitled Run',
        meta: `${run.run_type} · ${run.result_summary?.record_count ?? 0} records`,
      })),
    [query.data?.items],
  );

  return { query, items };
}
