import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';

export const AUTH_SESSION_QUERY_KEY = queryKeys.auth.me();

export function isAuthRoute(pathname: string | null) {
  return pathname === '/login' || pathname === '/register';
}

export function getAuthSessionQueryOptions(pathname?: string | null) {
  return {
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.me({ signal }),
    enabled: pathname === undefined ? true : !isAuthRoute(pathname),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  } as const;
}
