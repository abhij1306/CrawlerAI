import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';

export const AUTH_SESSION_QUERY_KEY = queryKeys.auth.me();

export function getAuthSessionQueryOptions() {
  return {
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: api.me,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  } as const;
}
