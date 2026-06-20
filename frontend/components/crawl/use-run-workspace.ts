import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlRun } from '../../lib/api/types';
import { ACTIVE_STATUSES } from '../../lib/constants/crawl-statuses';
import { POLLING_INTERVALS } from '../../lib/constants/timing';
import { useRunStatusFlags } from './use-run-polling';

export function useRunWorkspace(runId: number) {
  const runQuery = useQuery({
    queryKey: queryKeys.runs.detail(runId),
    queryFn: ({ signal }) => api.getCrawl(runId, { signal }),
    refetchInterval: (query) => {
      const currentRun = query.state.data as CrawlRun | undefined;
      return currentRun && ACTIVE_STATUSES.has(currentRun.status)
        ? POLLING_INTERVALS.ACTIVE_JOB_MS
        : false;
    },
    refetchIntervalInBackground: false,
    refetchOnMount: 'always',
  });
  const run = runQuery.data;
  const { live, terminal } = useRunStatusFlags(run);

  return {
    runQuery,
    run,
    live,
    terminal,
  };
}
