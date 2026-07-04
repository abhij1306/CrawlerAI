import { apiClient } from '@/api/client';

import { paginationQuery, withQuery } from './shared';
import type {
  DataEnrichmentJob,
  DataEnrichmentJobCreatePayload,
  DataEnrichmentJobDetail,
} from './types';

export const dataEnrichmentApi = {
  createDataEnrichmentJob: (payload: DataEnrichmentJobCreatePayload) =>
    apiClient.post<DataEnrichmentJob>('/api/data-enrichment/jobs', payload),
  listDataEnrichmentJobs: (params?: { limit?: number }) => {
    const query = paginationQuery(params);
    return apiClient.get<DataEnrichmentJob[]>(withQuery('/api/data-enrichment/jobs', query));
  },
  getDataEnrichmentJob: (jobId: number) =>
    apiClient.get<DataEnrichmentJobDetail>(`/api/data-enrichment/jobs/${jobId}`),
};
