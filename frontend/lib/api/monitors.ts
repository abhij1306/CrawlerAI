import { apiClient } from './client';
import type {
  MonitorCreatePayload,
  MonitorEvent,
  MonitorEventType,
  MonitorJob,
  MonitorPriority,
  MonitorSnapshot,
  MonitorSnapshotRecord,
  MonitorStatus,
  MonitorUpdatePayload,
  PaginatedResponse,
  RunNowResponse,
} from './types';

function withQuery(path: string, params?: Record<string, string | number | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const queryString = query.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export const monitorsApi = {
  list: (params?: { status?: MonitorStatus; priority?: MonitorPriority }) =>
    apiClient.get<MonitorJob[]>(withQuery('/api/monitors', params)),

  get: (id: number | string) => apiClient.get<MonitorJob>(`/api/monitors/${id}`),

  create: (payload: MonitorCreatePayload) =>
    apiClient.post<MonitorJob>('/api/monitors', payload),

  update: (id: number | string, payload: MonitorUpdatePayload) =>
    apiClient.patch<MonitorJob>(`/api/monitors/${id}`, payload),

  archive: (id: number | string) => apiClient.delete<void>(`/api/monitors/${id}`),

  runNow: (id: number | string) =>
    apiClient.post<RunNowResponse>(`/api/monitors/${id}/run/now`, {}),

  events: (id: number | string, params?: { page?: number; event_type?: MonitorEventType }) =>
    apiClient.get<PaginatedResponse<MonitorEvent>>(
      withQuery(`/api/monitors/${id}/events`, params),
    ),

  history: (id: number | string, params?: { page?: number }) =>
    apiClient.get<PaginatedResponse<MonitorSnapshot>>(
      withQuery(`/api/monitors/${id}/history`, params),
    ),

  currentSnapshot: (id: number | string) =>
    apiClient.get<MonitorSnapshotRecord[]>(`/api/monitors/${id}/snapshot/current`),
};
