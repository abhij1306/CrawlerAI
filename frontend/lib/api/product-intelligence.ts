import { apiClient } from '@/api/client';

import { paginationQuery, withQuery } from './shared';
import type {
  ProductIntelligenceDiscoveryPayload,
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceJob,
  ProductIntelligenceJobCreatePayload,
  ProductIntelligenceJobDetail,
} from './types';

export const productIntelligenceApi = {
  discoverProductIntelligence: (payload: ProductIntelligenceDiscoveryPayload) =>
    apiClient.post<ProductIntelligenceDiscoveryResponse>(
      '/api/product-intelligence/discover',
      payload,
    ),
  createProductIntelligenceJob: (payload: ProductIntelligenceJobCreatePayload) =>
    apiClient.post<ProductIntelligenceJob>('/api/product-intelligence/jobs', payload),
  listProductIntelligenceJobs: (params?: { limit?: number }) => {
    const query = paginationQuery(params);
    return apiClient.get<ProductIntelligenceJob[]>(
      withQuery('/api/product-intelligence/jobs', query),
    );
  },
  getProductIntelligenceJob: (jobId: number) =>
    apiClient.get<ProductIntelligenceJobDetail>(`/api/product-intelligence/jobs/${jobId}`),
  reviewProductIntelligenceMatch: (
    jobId: number,
    matchId: number,
    payload: { action: 'pending' | 'accepted' | 'rejected' },
  ) =>
    apiClient.post<{ match_id: number; review_status: string }>(
      `/api/product-intelligence/jobs/${jobId}/matches/${matchId}/review`,
      payload,
    ),
};
