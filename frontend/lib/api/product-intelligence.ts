import { apiClient } from '@/api/client';

import { paginationQuery, withQuery } from './shared';

export type ProductIntelligenceOptions = {
  max_source_products: number;
  max_candidates_per_product: number;
  search_provider: 'serpapi' | 'google_native';
  private_label_mode: 'include' | 'flag' | 'exclude';
  confidence_threshold: number;
  allowed_domains: string[];
  excluded_domains: string[];
  llm_enrichment_enabled: boolean;
};

export type ProductIntelligenceSourceRecordInput = {
  id?: number | null;
  run_id?: number | null;
  source_url?: string;
  data: Record<string, unknown>;
};

export type ProductIntelligenceJobCreatePayload = {
  source_run_id?: number | null;
  source_record_ids?: number[];
  source_records?: ProductIntelligenceSourceRecordInput[];
  options: ProductIntelligenceOptions;
};

export type ProductIntelligenceDiscoveryPayload = ProductIntelligenceJobCreatePayload;

export type ProductIntelligenceJob = {
  id: number;
  user_id: number;
  source_run_id: number | null;
  status: string;
  options: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

type ProductIntelligenceSourceProduct = {
  id: number;
  job_id: number;
  source_run_id: number | null;
  source_record_id: number | null;
  source_url: string;
  brand: string;
  normalized_brand: string;
  title: string;
  sku: string;
  mpn: string;
  gtin: string;
  price: number | null;
  currency: string;
  image_url: string;
  is_private_label: boolean;
  payload: Record<string, unknown>;
  created_at: string;
};

type ProductIntelligenceCandidate = {
  id: number;
  job_id: number;
  source_product_id: number;
  candidate_crawl_run_id: number | null;
  url: string;
  domain: string;
  source_type: string;
  query_used: string;
  search_rank: number;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type ProductIntelligenceMatch = {
  id: number;
  job_id: number;
  source_product_id: number;
  candidate_id: number;
  candidate_record_id: number | null;
  score: number;
  score_label: string;
  review_status: string;
  source_price: number | null;
  candidate_price: number | null;
  currency: string;
  availability: string;
  candidate_url: string;
  candidate_domain: string;
  score_reasons: Record<string, unknown>;
  llm_enrichment: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProductIntelligenceJobDetail = {
  job: ProductIntelligenceJob;
  source_products: ProductIntelligenceSourceProduct[];
  candidates: ProductIntelligenceCandidate[];
  matches: ProductIntelligenceMatch[];
};

type ProductIntelligenceDiscoveryCandidate = {
  source_record_id: number | null;
  source_run_id: number | null;
  source_url: string;
  source_title: string;
  source_brand: string;
  source_price: number | null;
  source_currency: string;
  source_index: number;
  url: string;
  domain: string;
  source_type: string;
  query_used: string;
  search_rank: number;
  payload: Record<string, unknown>;
  intelligence?: Record<string, unknown>;
};

export type ProductIntelligenceDiscoveryResponse = {
  job_id: number;
  options: Record<string, unknown>;
  source_count: number;
  candidate_count: number;
  search_provider?: string;
  candidates: ProductIntelligenceDiscoveryCandidate[];
};

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
