import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../../lib/api';

// Report-level root-cause fold for one run (runs/{id}/report.json, B1).
export function useRunReport(runId: number | null) {
  return useQuery({
    queryKey: queryKeys.diagnostics.report(runId ?? 0),
    queryFn: () => api.getRunReport(runId as number),
    enabled: Boolean(runId),
    staleTime: 60_000,
    retry: false,
  });
}

// Per-URL self-contained diagnose.json, fetched lazily when a root cause is
// expanded. `enabled` lets the caller defer the request until the drill-down opens.
export function useResultDiagnosis(
  runId: number | null,
  urlResultId: number | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.diagnostics.result(runId ?? 0, urlResultId ?? 0),
    queryFn: () => api.getResultDiagnosis(runId as number, urlResultId as number),
    enabled: enabled && Boolean(runId) && Boolean(urlResultId),
    staleTime: 60_000,
    retry: false,
  });
}

// diagnose_links are repo-relative paths: runs/{run}/results/{url_result_id}/diagnose.json.
// The drill-down needs the numeric url_result_id to call the per-result endpoint.
export function parseUrlResultId(diagnoseLink: string): number | null {
  const match = diagnoseLink.match(/\/results\/(\d+)\/diagnose\.json$/);
  if (!match) return null;
  const parsed = Number.parseInt(match[1], 10);
  return Number.isNaN(parsed) ? null : parsed;
}
