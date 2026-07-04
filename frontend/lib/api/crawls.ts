import { apiClient, getApiBaseUrl } from '@/api/client';
import type { ApiRequestOptions } from '@/api/client';

import { crawlRecordSchema, crawlRunSchema, strictValidate } from './schemas';
import { definedQuery, paginationQuery, withQuery } from './shared';
import type {
  CrawlCreatePayload,
  CrawlLog,
  CrawlRecord,
  CrawlRecordProvenance,
  CrawlRun,
  CrawlSurface,
  FieldCommitPayload,
  FieldCommitResponse,
  GroundedCorrectionPayload,
  GroundedCorrectionResponse,
  Paginated,
  ResultDiagnosis,
  ReviewPayload,
  ReviewSelection,
  RunReport,
} from './types';

type CategoryDiscoveryPayload = {
  url?: string;
  urls?: string[];
  limit?: number;
  max_depth?: number;
  max_pages?: number;
  strategy?: 'static_then_rendered' | 'static_only' | 'rendered_only';
  validate_candidates?: boolean;
};

type CategoryDiscoveryResponse = {
  status: string;
  source: string;
  urls: string[];
  groups: Record<string, string[]>;
  sources: Record<string, string>;
  errors: Record<string, string>;
  trees: Record<string, Array<Record<string, unknown>>>;
  diagnostics: Record<string, unknown>;
  total_found: number;
  limit: number;
};

export const crawlsApi = {
  createCrawl: (payload: CrawlCreatePayload) =>
    apiClient.post<{ run_id: number }>('/api/crawls', payload),
  discoverCategoryUrls: (payload: CategoryDiscoveryPayload) =>
    apiClient.post<CategoryDiscoveryResponse>('/api/crawls/category-discovery', payload),
  createCsvCrawl: (payload: {
    file: File;
    surface: CrawlSurface;
    additionalFields: string[];
    settings: Record<string, unknown>;
  }) => {
    const form = new FormData();
    form.append('file', payload.file);
    form.append('surface', payload.surface);
    form.append('additional_fields', payload.additionalFields.join(','));
    form.append('settings_json', JSON.stringify(payload.settings));
    return apiClient.postForm<{ run_id: number; url_count: number }>('/api/crawls/csv', form);
  },
  listCrawls: async (
    params?: {
      status?: string;
      run_type?: string;
      url_search?: string;
      page?: number;
      limit?: number;
    },
    options?: ApiRequestOptions,
  ) => {
    const query = definedQuery({
      page: params?.page,
      limit: params?.limit,
      status: params?.status || undefined,
      run_type: params?.run_type || undefined,
      url_search: params?.url_search || undefined,
    });
    const res = await apiClient.get<Paginated<CrawlRun>>(withQuery('/api/crawls', query), options);
    if (res?.items) {
      res.items = res.items.map((item) => strictValidate(crawlRunSchema, item, 'listCrawls'));
    }
    return res;
  },
  getCrawl: async (runId: number, options?: ApiRequestOptions) => {
    const res = await apiClient.get<CrawlRun>(`/api/crawls/${runId}`, options);
    return strictValidate(crawlRunSchema, res, `getCrawl(${runId})`);
  },
  deleteCrawl: (runId: number) => apiClient.delete<void>(`/api/crawls/${runId}`),
  pauseCrawl: (runId: number) =>
    apiClient.post<{ run_id: number; status: CrawlRun['status'] }>(
      `/api/crawls/${runId}/pause`,
      {},
    ),
  resumeCrawl: (runId: number) =>
    apiClient.post<{ run_id: number; status: CrawlRun['status'] }>(
      `/api/crawls/${runId}/resume`,
      {},
    ),
  killCrawl: (runId: number) =>
    apiClient.post<{ run_id: number; status: CrawlRun['status'] }>(`/api/crawls/${runId}/kill`, {}),
  commitSelectedFields: (runId: number, items: FieldCommitPayload[]) =>
    apiClient.post<FieldCommitResponse>(`/api/crawls/${runId}/commit-fields`, { items }),
  getRecords: async (
    runId: number,
    params?: { page?: number; limit?: number },
    options?: ApiRequestOptions,
  ) => {
    const query = paginationQuery(params);
    const res = await apiClient.get<Paginated<CrawlRecord>>(
      withQuery(`/api/crawls/${runId}/records`, query),
      options,
    );
    if (res?.items) {
      res.items = res.items.map((item) =>
        strictValidate(crawlRecordSchema, item, `getRecords(${runId})`),
      );
    }
    return res;
  },
  getRecordProvenance: (recordId: number) =>
    apiClient.get<CrawlRecordProvenance>(`/api/records/${recordId}/provenance`),
  getCrawlLogs: (
    runId: number,
    params?: { afterId?: number; limit?: number },
    options?: ApiRequestOptions,
  ) => {
    const query = definedQuery({ after_id: params?.afterId, limit: params?.limit });
    return apiClient.get<CrawlLog[]>(withQuery(`/api/crawls/${runId}/logs`, query), options);
  },
  downloadCsv: (runId: number) => apiClient.getBlob(`/api/crawls/${runId}/export/csv`),
  downloadJson: (runId: number) => apiClient.getBlob(`/api/crawls/${runId}/export/json`),
  exportCsv: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/csv`,
  exportJson: (runId: number) => `${getApiBaseUrl()}/api/crawls/${runId}/export/json`,
  getReview: async (runId: number) => {
    const res = await apiClient.get<ReviewPayload>(`/api/review/${runId}`);
    if (res?.run) {
      res.run = strictValidate(crawlRunSchema, res.run, `getReview(${runId}).run`);
    }
    if (res?.records) {
      res.records = res.records.map((item) =>
        strictValidate(crawlRecordSchema, item, `getReview(${runId}).records`),
      );
    }
    return res;
  },
  reviewHtml: (runId: number) => `${getApiBaseUrl()}/api/review/${runId}/artifact-html`,
  saveReview: (runId: number, payload: { selections: ReviewSelection[]; extra_fields: string[] }) =>
    apiClient.post(`/api/review/${runId}/save`, payload),
  getRunReport: (runId: number) => apiClient.get<RunReport>(`/api/crawls/${runId}/report.json`),
  getResultDiagnosis: (runId: number, urlResultId: number) =>
    apiClient.get<ResultDiagnosis>(`/api/crawls/${runId}/results/${urlResultId}/diagnose.json`),
  saveGroundedCorrection: (runId: number, payload: GroundedCorrectionPayload) =>
    apiClient.post<GroundedCorrectionResponse>(`/api/crawls/${runId}/corrections`, payload),
};
