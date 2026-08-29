import { apiClient, getApiBaseUrl } from '@/api/client';
import type { ApiRequestOptions } from '@/api/client';

import { definedQuery, withQuery } from './shared';
import type { SelectorRecord } from './types';

export type SelectorTestResponse = {
  matched_value: string | null;
  count: number;
  selector_used?: string | null;
};

type SelectorSuggestion = {
  field_name?: string | null;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  sample_value?: string | null;
  source?: string | null;
};

export type SelectorSuggestResponse = {
  surface: string;
  suggestions: Record<string, SelectorSuggestion[]>;
  preview_url?: string | null;
  iframe_promoted?: boolean;
};

export const selectorsApi = {
  listSelectors: (params?: { domain?: string; surface?: string }, options?: ApiRequestOptions) => {
    const query = definedQuery({
      domain: params?.domain || undefined,
      surface: params?.surface || undefined,
    });
    return apiClient.get<SelectorRecord[]>(withQuery('/api/selectors', query), options);
  },
  suggestSelectors: (payload: { url: string; expected_columns: string[]; surface?: string }) =>
    apiClient.post<SelectorSuggestResponse>('/api/selectors/suggest', payload),
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
};
