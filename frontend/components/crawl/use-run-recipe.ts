import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';

export function useRunRecipe(runId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.runs.recipe(runId),
    queryFn: ({ signal }) => api.getDomainRecipe(runId, { signal }),
    enabled,
  });
}
