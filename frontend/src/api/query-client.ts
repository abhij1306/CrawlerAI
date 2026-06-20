import { QueryClient } from '@tanstack/react-query';

import { httpErrorStatus, isAbortError } from './errors';

export function shouldRetryQuery(failureCount: number, error: unknown) {
  if (failureCount >= 2 || isAbortError(error)) return false;
  const status = httpErrorStatus(error);
  if (status === undefined) return true;
  return status === 408 || status === 429 || status >= 500;
}

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
