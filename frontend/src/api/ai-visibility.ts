import { apiClient } from './client';

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------
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
// API Functions
// --------------------------------------------------------------------------
export async function getProviders() {
  return apiClient.get<AiVisibilityProviderStatus[]>('/api/ai-visibility/providers');
}

export async function getBestAndLessPreset() {
  return apiClient.get<AiVisibilityProjectCreate>('/api/ai-visibility/presets/best-and-less');
}

export async function listProjects(limit = 50) {
  return apiClient.get<AiVisibilityProject[]>(`/api/ai-visibility/projects?limit=${limit}`);
}

export async function getProject(projectId: number) {
  return apiClient.get<AiVisibilityProject>(`/api/ai-visibility/projects/${projectId}`);
}

export async function createProject(payload: AiVisibilityProjectCreate) {
  return apiClient.post<AiVisibilityProject>('/api/ai-visibility/projects', payload);
}

export async function updateProject(projectId: number, payload: AiVisibilityProjectUpdate) {
  return apiClient.patch<AiVisibilityProject>(`/api/ai-visibility/projects/${projectId}`, payload);
}

export async function deleteProject(projectId: number) {
  return apiClient.delete(`/api/ai-visibility/projects/${projectId}`);
}

export async function listRuns(projectId?: number, limit = 50) {
  const params = new URLSearchParams();
  if (projectId !== undefined) params.set('project_id', String(projectId));
  params.set('limit', String(limit));
  const query = params.toString();
  return apiClient.get<AiVisibilityRun[]>(`/api/ai-visibility/runs?${query}`);
}

export async function getRun(runId: number) {
  return apiClient.get<AiVisibilityRunDetail>(`/api/ai-visibility/runs/${runId}`);
}

export async function deleteRun(runId: number) {
  return apiClient.delete(`/api/ai-visibility/runs/${runId}`);
}

export async function cancelRun(runId: number) {
  return apiClient.post<AiVisibilityRun>(`/api/ai-visibility/runs/${runId}/cancel`, {});
}

export async function createRun(payload: AiVisibilityRunCreate) {
  return apiClient.post<AiVisibilityRun>('/api/ai-visibility/runs', payload);
}

export async function getExecution(executionId: number) {
  return apiClient.get<AiVisibilityExecution>(`/api/ai-visibility/executions/${executionId}`);
}

export function getExportCsvUrl(runId: number) {
  return `/api/ai-visibility/runs/${runId}/export.csv`;
}

export function getExportMarkdownUrl(runId: number) {
  return `/api/ai-visibility/runs/${runId}/export.md`;
}
