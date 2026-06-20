import { apiClient, getApiBaseUrl } from '@/api/client';
import {
  userSchema,
  crawlRunSchema,
  crawlRecordSchema,
  domainRunProfileSchema,
  strictValidate,
} from './schemas';
import type {
  ActiveJob,
  CrawlCreatePayload,
  CrawlLog,
  CrawlRecord,
  CrawlRecordProvenance,
  CrawlRun,
  CrawlSurface,
  DataEnrichmentJob,
  DataEnrichmentJobCreatePayload,
  DataEnrichmentJobDetail,
  Dashboard,
  DomainRecipe,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfileLookup,
  DomainRunProfileRecord,
  DomainRunProfile,
  FieldCommitPayload,
  FieldCommitResponse,
  LlmConfigCreatePayload,
  LoginResponse,
  Paginated,
  ProductIntelligenceJob,
  ProductIntelligenceDiscoveryPayload,
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceJobCreatePayload,
  ProductIntelligenceJobDetail,
  ReviewPayload,
  ReviewSelection,
  SelectorCreatePayload,
  SelectorDomainSummary,
  SelectorRecord,
  SelectorSuggestResponse,
  SelectorTestResponse,
  SelectorUpdatePayload,
  User,
  LlmConfigRecord,
  LlmConfigUpdatePayload,
  LlmProviderCatalogItem,
  LlmConnectionTestResponse,
  LlmCostLogRecord,
  RunObservability,
} from './types';

function withQuery(path: string, query: URLSearchParams) {
  const queryString = query.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export type CategoryDiscoveryPayload = {
  url?: string;
  urls?: string[];
  limit?: number;
  max_depth?: number;
  max_pages?: number;
  strategy?: 'static_then_rendered' | 'static_only' | 'rendered_only';
  validate_candidates?: boolean;
};
export type CategoryDiscoveryResponse = {
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

export const api = {
  register: async (email: string, password: string) => {
    const res = await apiClient.post<User>('/api/auth/register', { email, password });
    return strictValidate(userSchema, res, 'register');
  },
  login: async (email: string, password: string) => {
    const response = await apiClient.post<LoginResponse>('/api/auth/login', { email, password });
    if (response?.user) {
      response.user = strictValidate(userSchema, response.user, 'login');
    }
    return response;
  },
  me: async () => {
    const res = await apiClient.get<User>('/api/auth/me');
    return strictValidate(userSchema, res, 'me');
  },
  dashboard: () => apiClient.get<Dashboard>('/api/dashboard'),
  resetApplicationData: () =>
    apiClient.post<Record<string, number | boolean>>('/api/dashboard/reset-data', {}),
  resetDomainMemory: () =>
    apiClient.post<Record<string, number | boolean>>('/api/dashboard/reset-domain-memory', {}),
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
  listCrawls: async (params?: {
    status?: string;
    run_type?: string;
    url_search?: string;
    page?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.run_type) query.set('run_type', params.run_type);
    if (params?.url_search) query.set('url_search', params.url_search);
    if (params?.page !== undefined) query.set('page', String(params.page));
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    const res = await apiClient.get<Paginated<CrawlRun>>(withQuery('/api/crawls', query));
    if (res?.items) {
      res.items = res.items.map((item) => strictValidate(crawlRunSchema, item, 'listCrawls'));
    }
    return res;
  },
  getCrawl: async (runId: number) => {
    const res = await apiClient.get<CrawlRun>(`/api/crawls/${runId}`);
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
  getRecords: async (runId: number, params?: { page?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.page !== undefined) query.set('page', String(params.page));
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    const res = await apiClient.get<Paginated<CrawlRecord>>(
      withQuery(`/api/crawls/${runId}/records`, query),
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
  getRunObservability: (runId: number) =>
    apiClient.get<RunObservability>(`/api/runs/${runId}/observability`),
  getCrawlLogs: (runId: number, params?: { afterId?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.afterId !== undefined) query.set('after_id', String(params.afterId));
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    return apiClient.get<CrawlLog[]>(withQuery(`/api/crawls/${runId}/logs`, query));
  },
  discoverProductIntelligence: (payload: ProductIntelligenceDiscoveryPayload) =>
    apiClient.post<ProductIntelligenceDiscoveryResponse>(
      '/api/product-intelligence/discover',
      payload,
    ),
  createProductIntelligenceJob: (payload: ProductIntelligenceJobCreatePayload) =>
    apiClient.post<ProductIntelligenceJob>('/api/product-intelligence/jobs', payload),
  listProductIntelligenceJobs: (params?: { limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    return apiClient.get<ProductIntelligenceJob[]>(
      withQuery('/api/product-intelligence/jobs', query),
    );
  },
  getProductIntelligenceJob: (jobId: number) =>
    apiClient.get<ProductIntelligenceJobDetail>(`/api/product-intelligence/jobs/${jobId}`),
  createDataEnrichmentJob: (payload: DataEnrichmentJobCreatePayload) =>
    apiClient.post<DataEnrichmentJob>('/api/data-enrichment/jobs', payload),
  listDataEnrichmentJobs: (params?: { limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    return apiClient.get<DataEnrichmentJob[]>(withQuery('/api/data-enrichment/jobs', query));
  },
  getDataEnrichmentJob: (jobId: number) =>
    apiClient.get<DataEnrichmentJobDetail>(`/api/data-enrichment/jobs/${jobId}`),
  reviewProductIntelligenceMatch: (
    jobId: number,
    matchId: number,
    payload: { action: 'pending' | 'accepted' | 'rejected' },
  ) =>
    apiClient.post<{ match_id: number; review_status: string }>(
      `/api/product-intelligence/jobs/${jobId}/matches/${matchId}/review`,
      payload,
    ),
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
  getDomainRunProfile: async (params: { url: string; surface: CrawlSurface }) => {
    const query = new URLSearchParams();
    query.set('url', params.url);
    query.set('surface', params.surface);
    const res = await apiClient.get<DomainRunProfileLookup>(
      withQuery('/api/crawls/domain-run-profile', query),
    );
    if (res?.saved_run_profile) {
      res.saved_run_profile = strictValidate(
        domainRunProfileSchema,
        res.saved_run_profile,
        `getDomainRunProfile(${params.url})`,
      );
    }
    return res;
  },
  listDomainRunProfiles: async (params?: { domain?: string; surface?: string }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set('domain', params.domain);
    if (params?.surface) query.set('surface', params.surface);
    const res = await apiClient.get<DomainRunProfileRecord[]>(
      withQuery('/api/crawls/domain-memory/run-profiles', query),
    );
    if (Array.isArray(res)) {
      res.forEach((item) => {
        if (item?.profile) {
          item.profile = strictValidate(
            domainRunProfileSchema,
            item.profile,
            `listDomainRunProfiles(${params?.domain})`,
          );
        }
      });
    }
    return res;
  },
  listDomainCookieMemory: (params?: { domain?: string }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set('domain', params.domain);
    return apiClient.get<DomainCookieMemoryRecord[]>(
      withQuery('/api/crawls/domain-memory/cookies', query),
    );
  },
  listDomainFieldFeedback: (params?: { domain?: string; surface?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set('domain', params.domain);
    if (params?.surface) query.set('surface', params.surface);
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    return apiClient.get<DomainFieldFeedbackRecord[]>(
      withQuery('/api/crawls/domain-memory/field-feedback', query),
    );
  },
  getDomainRecipe: (runId: number) =>
    apiClient.get<DomainRecipe>(`/api/crawls/${runId}/domain-recipe`),
  promoteDomainRecipeSelectors: (
    runId: number,
    payload: {
      selectors: Array<{
        candidate_key: string;
        field_name: string;
        selector_kind: string;
        selector_value: string;
        sample_value?: string | null;
      }>;
    },
  ) =>
    apiClient.post<SelectorRecord[]>(
      `/api/crawls/${runId}/domain-recipe/promote-selectors`,
      payload,
    ),
  saveDomainRunProfile: async (runId: number, payload: { profile: DomainRunProfile }) => {
    const res = await apiClient.post<DomainRunProfile>(
      `/api/crawls/${runId}/domain-recipe/save-run-profile`,
      payload,
    );
    return strictValidate(domainRunProfileSchema, res, `saveDomainRunProfile(${runId})`);
  },
  applyDomainRecipeFieldAction: (
    runId: number,
    payload: {
      field_name: string;
      action: 'keep' | 'reject';
      selector_kind?: string | null;
      selector_value?: string | null;
      source_record_ids?: number[];
    },
  ) =>
    apiClient.post<Record<string, unknown>>(
      `/api/crawls/${runId}/domain-recipe/field-action`,
      payload,
    ),
  listUsers: async (params?: { search?: string; is_active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.search) query.set('search', params.search);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const res = await apiClient.get<Paginated<User>>(withQuery('/api/users', query));
    if (res?.items) {
      res.items = res.items.map((item) => strictValidate(userSchema, item, 'listUsers'));
    }
    return res;
  },
  updateUser: async (userId: number, payload: Partial<Pick<User, 'role' | 'is_active'>>) => {
    const res = await apiClient.patch<User>(`/api/users/${userId}`, payload);
    return strictValidate(userSchema, res, `updateUser(${userId})`);
  },
  listSelectors: (params?: { domain?: string; surface?: string }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set('domain', params.domain);
    if (params?.surface) query.set('surface', params.surface);
    return apiClient.get<SelectorRecord[]>(withQuery('/api/selectors', query));
  },
  listSelectorSummaries: () => apiClient.get<SelectorDomainSummary[]>('/api/selectors/summary'),
  suggestSelectors: (payload: { url: string; expected_columns: string[]; surface?: string }) =>
    apiClient.post<SelectorSuggestResponse>('/api/selectors/suggest', payload),
  createSelector: (payload: SelectorCreatePayload) =>
    apiClient.post<SelectorRecord>('/api/selectors', payload),
  updateSelector: (selectorId: number, payload: SelectorUpdatePayload) =>
    apiClient.put<SelectorRecord>(`/api/selectors/${selectorId}`, payload),
  deleteSelector: (selectorId: number) => apiClient.delete<void>(`/api/selectors/${selectorId}`),
  deleteSelectorsByDomain: (domain: string) =>
    apiClient.delete<{ deleted: number }>(`/api/selectors/domain/${encodeURIComponent(domain)}`),
  testSelector: (payload: {
    url: string;
    css_selector?: string | null;
    xpath?: string | null;
    regex?: string | null;
  }) => apiClient.post<SelectorTestResponse>('/api/selectors/test', payload),
  selectorPreviewHtml: (url: string) =>
    `${getApiBaseUrl()}/api/selectors/preview-html?url=${encodeURIComponent(url)}`,
  getPreviewHtml: (url: string) =>
    apiClient.getText(`/api/selectors/preview-html?url=${encodeURIComponent(url)}`),
  listLlmProviders: () => apiClient.get<LlmProviderCatalogItem[]>('/api/llm/providers'),
  listLlmConfigs: (params?: { include_unsupported?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.include_unsupported !== undefined) {
      query.set('include_unsupported', String(params.include_unsupported));
    }
    return apiClient.get<LlmConfigRecord[]>(withQuery('/api/llm/configs', query));
  },
  createLlmConfig: (payload: LlmConfigCreatePayload) =>
    apiClient.post<LlmConfigRecord>('/api/llm/configs', payload),
  updateLlmConfig: (configId: number, payload: LlmConfigUpdatePayload) =>
    apiClient.put<LlmConfigRecord>(`/api/llm/configs/${configId}`, payload),
  deleteLlmConfig: (configId: number) => apiClient.delete<void>(`/api/llm/configs/${configId}`),
  testLlmConnection: (payload: { provider: string; model: string; api_key?: string | null }) =>
    apiClient.post<LlmConnectionTestResponse>('/api/llm/test-connection', payload),
  listLlmCostLog: () => apiClient.get<LlmCostLogRecord[]>('/api/llm/cost-log'),
  listJobs: () => apiClient.get<ActiveJob[]>('/api/jobs/active'),
};
