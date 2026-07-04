import { apiClient } from '@/api/client';
import type { ApiRequestOptions } from '@/api/client';

import { domainRunProfileSchema, strictValidate } from './schemas';
import { definedQuery, withQuery } from './shared';
import type {
  CrawlSurface,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRecipe,
  DomainRunProfile,
  DomainRunProfileLookup,
  DomainRunProfileRecord,
} from './types';

export const domainMemoryApi = {
  getDomainRunProfile: async (
    params: { url: string; surface: CrawlSurface },
    options?: ApiRequestOptions,
  ) => {
    const query = definedQuery({ url: params.url, surface: params.surface });
    const res = await apiClient.get<DomainRunProfileLookup>(
      withQuery('/api/crawls/domain-run-profile', query),
      options,
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
    const query = definedQuery({
      domain: params?.domain || undefined,
      surface: params?.surface || undefined,
    });
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
    const query = definedQuery({ domain: params?.domain || undefined });
    return apiClient.get<DomainCookieMemoryRecord[]>(
      withQuery('/api/crawls/domain-memory/cookies', query),
    );
  },
  listDomainFieldFeedback: (params?: { domain?: string; surface?: string; limit?: number }) => {
    const query = definedQuery({
      domain: params?.domain || undefined,
      surface: params?.surface || undefined,
      limit: params?.limit,
    });
    return apiClient.get<DomainFieldFeedbackRecord[]>(
      withQuery('/api/crawls/domain-memory/field-feedback', query),
    );
  },
  getDomainRecipe: (runId: number, options?: ApiRequestOptions) =>
    apiClient.get<DomainRecipe>(`/api/crawls/${runId}/domain-recipe`, options),
  saveDomainRunProfile: async (runId: number, payload: { profile: DomainRunProfile }) => {
    const res = await apiClient.post<DomainRunProfile>(
      `/api/crawls/${runId}/domain-recipe/save-run-profile`,
      payload,
    );
    return strictValidate(domainRunProfileSchema, res, `saveDomainRunProfile(${runId})`);
  },
};
