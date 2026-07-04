import { apiClient } from '@/api/client';

import type { Dashboard } from './types';

export const dashboardApi = {
  dashboard: () => apiClient.get<Dashboard>('/api/dashboard'),
  resetApplicationData: () =>
    apiClient.post<Record<string, number | boolean>>('/api/dashboard/reset-data', {}),
  resetDomainMemory: () =>
    apiClient.post<Record<string, number | boolean>>('/api/dashboard/reset-domain-memory', {}),
};
