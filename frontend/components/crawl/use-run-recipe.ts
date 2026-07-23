import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { domainMemoryApi } from '../../lib/api/domain-memory';

export function useRunRecipe(runId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.runs.recipe(runId),
    queryFn: ({ signal }) => domainMemoryApi.getDomainRecipe(runId, { signal }),
    enabled,
  });
}
