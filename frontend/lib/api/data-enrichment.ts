import { apiClient } from '@/api/client';

import { paginationQuery, withQuery } from './shared';

export type DataEnrichmentOptions = {
  max_source_records: number;
  llm_enabled: boolean;
};

export type DataEnrichmentSourceRecordInput = {
  id?: number | null;
  run_id?: number | null;
  source_url?: string;
  data: Record<string, unknown>;
};

export type DataEnrichmentJobCreatePayload = {
  source_run_id?: number | null;
  source_record_ids?: number[];
  source_records?: DataEnrichmentSourceRecordInput[];
  options: DataEnrichmentOptions;
};

export type DataEnrichmentJob = {
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

export type EnrichedProduct = {
  id: number;
  job_id: number;
  source_run_id: number | null;
  source_record_id: number | null;
  source_url: string;
  status: string;
  price_normalized: Record<string, unknown> | null;
  color_family: string | null;
  size_normalized: string[] | null;
  size_system: string | null;
  gender_normalized: string | null;
  materials_normalized: string[] | null;
  availability_normalized: string | null;
  seo_keywords: string[] | null;
  category_path: string | null;
  taxonomy_version: string | null;
  intent_attributes: string[] | null;
  audience: string[] | null;
  style_tags: string[] | null;
  ai_discovery_tags: string[] | null;
  suggested_bundles: string[] | null;
  diagnostics: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DataEnrichmentJobDetail = {
  job: DataEnrichmentJob;
  enriched_products: EnrichedProduct[];
};

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
