import { apiClient } from '@/api/client';

import { strictValidate, userSchema } from './schemas';
import { definedQuery, withQuery } from './shared';
import type { Paginated, User } from './types';

export type LlmConfigRecord = {
  id: number;
  provider: string;
  model: string;
  api_key_masked: string;
  api_key_set: boolean;
  task_type: string;
  per_domain_daily_budget_usd: string;
  global_session_budget_usd: string;
  is_active: boolean;
  created_at: string;
};

export type LlmConfigCreatePayload = {
  provider: string;
  model: string;
  task_type: string;
  api_key?: string | null;
  per_domain_daily_budget_usd?: string;
  global_session_budget_usd?: string;
  is_active?: boolean;
};

export type LlmConfigUpdatePayload = Partial<LlmConfigCreatePayload>;

export type LlmProviderCatalogItem = {
  provider: string;
  label: string;
  api_key_set: boolean;
  recommended_models: string[];
};

export type LlmConnectionTestResponse = { ok: boolean; message: string };

export type LlmCostLogRecord = {
  id: number;
  run_id: number | null;
  provider: string;
  model: string;
  task_type: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  domain: string;
  created_at: string;
};

export const adminApi = {
  listUsers: async (params?: { search?: string; is_active?: boolean }) => {
    const query = definedQuery({
      search: params?.search || undefined,
      is_active: params?.is_active,
    });
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
  listLlmProviders: () => apiClient.get<LlmProviderCatalogItem[]>('/api/llm/providers'),
  listLlmConfigs: (params?: { include_unsupported?: boolean }) => {
    const query = definedQuery({ include_unsupported: params?.include_unsupported });
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
};
