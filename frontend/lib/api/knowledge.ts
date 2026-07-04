import { apiClient } from '@/api/client';

import { withQuery } from './shared';
import type {
  KnowledgeContract,
  KnowledgeContractSelectionPayload,
  KnowledgeGraphResponse,
  KnowledgeSelectorContractPayload,
  KnowledgeSiteRecord,
} from './types';

export const knowledgeApi = {
  listKnowledgeSites: () => apiClient.get<{ sites: KnowledgeSiteRecord[] }>('/api/knowledge/sites'),
  getKnowledgeGraph: (params?: {
    domain?: string;
    root_entity_id?: string;
    depth?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.domain) query.set('domain', params.domain);
    if (params?.root_entity_id) query.set('root_entity_id', params.root_entity_id);
    if (params?.depth !== undefined) query.set('depth', String(params.depth));
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    return apiClient.get<KnowledgeGraphResponse>(withQuery('/api/knowledge/graph', query));
  },
  listKnowledgeContractsByDomain: (domain: string, surface?: string) => {
    const query = new URLSearchParams({ domain });
    if (surface) query.set('surface', surface);
    return apiClient.get<{ domain: string; contracts: KnowledgeContract[] }>(
      withQuery('/api/knowledge/contracts', query),
    );
  },
  listKnowledgeContracts: (templateId: string) =>
    apiClient.get<{ contracts: KnowledgeContract[] }>(
      `/api/knowledge/contracts/${encodeURIComponent(templateId)}`,
    ),
  selectKnowledgeContractSource: (contractId: string, payload: KnowledgeContractSelectionPayload) =>
    apiClient.put<{ contract: KnowledgeContract }>(
      `/api/knowledge/contracts/${encodeURIComponent(contractId)}/selection`,
      payload,
    ),
  upsertKnowledgeSelectorContract: (payload: KnowledgeSelectorContractPayload) =>
    apiClient.post<{ contract: KnowledgeContract }>('/api/knowledge/contracts/selector', payload),
};
