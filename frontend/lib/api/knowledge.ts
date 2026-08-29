import { apiClient } from '@/api/client';

import { withQuery } from './shared';

export type KnowledgeSiteRecord = {
  id: string;
  domain: string;
  current_version: number;
  projection_status: string;
  last_projected_run_id?: number | null;
  last_projected_at?: string | null;
};

type KnowledgeEntity = {
  id: string;
  entity_type: string;
  canonical_key: string;
  canonical_name: string;
  properties: Record<string, unknown>;
  status: string;
};

type KnowledgeRelationship = {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  properties: Record<string, unknown>;
  confidence: number;
  status: string;
};

export type KnowledgeGraphResponse = {
  bounds: { depth: number; limit: number };
  nodes: KnowledgeEntity[];
  relationships: KnowledgeRelationship[];
};

export type KnowledgeContract = {
  id: string;
  template_id: string;
  surface: string;
  canonical_field: string;
  candidates: Array<Record<string, unknown>>;
  latest_values: Array<Record<string, unknown>>;
  success_count: number;
  rejection_count: number;
  resolver_rule: string;
  selected_source: string;
  selection_origin: string;
  selection_history: Array<Record<string, unknown>>;
  status: string;
};

export type KnowledgeSelectorContractPayload = {
  domain: string;
  url: string;
  surface: string;
  field_name: string;
  css_selector: string;
  sample_value?: string | null;
  source?: string | null;
};

export type KnowledgeContractSelectionPayload = {
  selected_source: string;
  expected_version?: number | null;
  template_id?: string;
  surface?: string;
  canonical_field?: string;
};

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
