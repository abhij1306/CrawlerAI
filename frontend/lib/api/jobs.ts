import { apiClient } from '@/api/client';

import type { ActiveJob } from './types';

export const jobsApi = {
  listJobs: () => apiClient.get<ActiveJob[]>('/api/jobs/active'),
};
