import { apiClient } from '@/api/client';
import { queryKeys } from '@/api/query-keys';

import { definedQuery, withQuery } from './shared';

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------
// AI Visibility types are module-local (the shared lib/api/types.ts owner is
// maintained separately). Keep them colocated here until they are promoted.
export type AiVisibilityProviderId =
  | 'gemini'
  | 'anthropic'
  | 'openrouter_openai'
  | 'openrouter_anthropic';

export type CompetitorInput = {
  name: string;
  aliases: string[];
  domains: string[];
};

export type PromptInput = {
  text: string;
  theme?: string;
  intent?: string;
};

export type AiVisibilityProject = {
  id: number;
  user_id?: number;
  name: string;
  brand_name: string;
  brand_aliases: string[];
  owned_domains: string[];
  unintended_domains: string[];
  competitors: CompetitorInput[];
  country_code: string;
  language_code: string;
  benchmark_mode: 'consumer_like' | 'controlled_localized' | 'forced_grounded';
  prompts: PromptInput[];
  default_repetitions: number;
  created_at: string;
  updated_at: string;
};

export type AiVisibilityProjectCreate = {
  name: string;
  brand_name: string;
  brand_aliases?: string[];
  owned_domains?: string[];
  unintended_domains?: string[];
  competitors?: CompetitorInput[];
  country_code?: string;
  language_code?: string;
  benchmark_mode?: 'consumer_like' | 'controlled_localized' | 'forced_grounded';
  prompts?: PromptInput[];
  default_repetitions?: number;
};

export type AiVisibilityProjectUpdate = Partial<AiVisibilityProjectCreate>;

export type AiVisibilityRun = {
  id: number;
  project_id: number;
  user_id?: number;
  status: string;
  provider: AiVisibilityProviderId;
  model: string;
  repetitions: number;
  random_seed: string;
  configuration: Record<string, unknown>;
  summary: Record<string, unknown>;
  requested_count: number;
  completed_count: number;
  failed_count: number;
  error_message: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
};

export type AiVisibilityRunCreate = {
  project_id: number;
  provider?: AiVisibilityProviderId;
  repetitions?: number;
  prompt_indices?: number[];
};

export type AiVisibilityExecution = {
  id: number;
  run_id: number;
  prompt_index: number;
  prompt_text_snapshot: string;
  prompt_theme_snapshot: string;
  prompt_intent_snapshot: string;
  repetition: number;
  randomized_position: number;
  status: string;
  answer_text: string;
  search_used: boolean;
  search_events: Array<{ sequence?: number; query?: string }>;
  citations: Array<Record<string, unknown>>;
  score: Record<string, unknown>;
  request_snapshot: Record<string, unknown>;
  provider_metadata: Record<string, unknown>;
  error_code: string;
  error_message: string;
  latency_ms: number;
};

export type AiVisibilityRunDetail = {
  run: AiVisibilityRun;
  executions: AiVisibilityExecution[];
};

export type AiVisibilityProviderStatus = {
  provider: string;
  label: string;
  surface: string;
  configured: boolean;
  model: string;
  supports_search_fanout: boolean;
  supports_citations: boolean;
};

// --------------------------------------------------------------------------
// Query keys
// --------------------------------------------------------------------------
// Routes every AI Visibility key through the central queryKeys factory in
// src/api/query-keys.ts; module-only keys extend it here instead of handing
// call sites raw arrays.
export const aiVisibilityQueryKeys = {
  ...queryKeys.aiVisibility,
  bestAndLessPreset: () => [...queryKeys.aiVisibility.all, 'presets', 'best-and-less'] as const,
} as const;

// --------------------------------------------------------------------------
// API
// --------------------------------------------------------------------------
export const aiVisibilityApi = {
  listAiVisibilityProviders: () =>
    apiClient.get<AiVisibilityProviderStatus[]>('/api/ai-visibility/providers'),

  getBestAndLessPreset: () =>
    apiClient.get<AiVisibilityProjectCreate>('/api/ai-visibility/presets/best-and-less'),

  listAiVisibilityProjects: (params?: { limit?: number }) =>
    apiClient.get<AiVisibilityProject[]>(
      withQuery('/api/ai-visibility/projects', definedQuery({ limit: params?.limit ?? 50 })),
    ),

  createAiVisibilityProject: (payload: AiVisibilityProjectCreate) =>
    apiClient.post<AiVisibilityProject>('/api/ai-visibility/projects', payload),

  updateAiVisibilityProject: (projectId: number, payload: AiVisibilityProjectUpdate) =>
    apiClient.patch<AiVisibilityProject>(`/api/ai-visibility/projects/${projectId}`, payload),

  listAiVisibilityRuns: (params?: { projectId?: number; limit?: number }) =>
    apiClient.get<AiVisibilityRun[]>(
      withQuery(
        '/api/ai-visibility/runs',
        definedQuery({ project_id: params?.projectId, limit: params?.limit ?? 50 }),
      ),
    ),

  getAiVisibilityRun: (runId: number) =>
    apiClient.get<AiVisibilityRunDetail>(`/api/ai-visibility/runs/${runId}`),

  deleteAiVisibilityRun: (runId: number) => apiClient.delete(`/api/ai-visibility/runs/${runId}`),

  cancelAiVisibilityRun: (runId: number) =>
    apiClient.post<AiVisibilityRun>(`/api/ai-visibility/runs/${runId}/cancel`, {}),

  createAiVisibilityRun: (payload: AiVisibilityRunCreate) =>
    apiClient.post<AiVisibilityRun>('/api/ai-visibility/runs', payload),

  getAiVisibilityExecution: (executionId: number) =>
    apiClient.get<AiVisibilityExecution>(`/api/ai-visibility/executions/${executionId}`),

  getAiVisibilityExportCsvUrl: (runId: number) => `/api/ai-visibility/runs/${runId}/export.csv`,

  getAiVisibilityExportMarkdownUrl: (runId: number) => `/api/ai-visibility/runs/${runId}/export.md`,
};
