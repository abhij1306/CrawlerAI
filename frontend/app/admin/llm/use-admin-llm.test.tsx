import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type { LlmConfigRecord, LlmCostLogRecord, LlmProviderCatalogItem } from '@lib/api/types';
import { INITIAL_LLM_FORM, useAdminLlm } from './use-admin-llm';

const apiMock = vi.hoisted(() => ({
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  listLlmProviders: vi.fn(),
  listLlmConfigs: vi.fn(),
  createLlmConfig: vi.fn(),
  updateLlmConfig: vi.fn(),
  deleteLlmConfig: vi.fn(),
  testLlmConnection: vi.fn(),
  listLlmCostLog: vi.fn(),
}));

vi.mock('@lib/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@lib/api/admin')>();
  return { ...actual, adminApi: apiMock };
});

const PROVIDERS: LlmProviderCatalogItem[] = [
  {
    provider: 'openrouter',
    label: 'OpenRouter',
    api_key_set: true,
    recommended_models: ['openai/gpt-4o-mini'],
  },
  {
    provider: 'gemini',
    label: 'Gemini',
    api_key_set: false,
    recommended_models: ['gemini-2.5-flash'],
  },
];

const CONFIG: LlmConfigRecord = {
  id: 1,
  provider: 'openrouter',
  model: 'openai/gpt-4o-mini',
  api_key_masked: 'sk-…1234',
  api_key_set: true,
  task_type: 'data_enrichment_semantic',
  per_domain_daily_budget_usd: '0',
  global_session_budget_usd: '0',
  is_active: true,
  created_at: '2026-07-01T00:00:00Z',
};

const COST_ENTRY: LlmCostLogRecord = {
  id: 9,
  run_id: 42,
  provider: 'openrouter',
  model: 'openai/gpt-4o-mini',
  task_type: 'data_enrichment_semantic',
  input_tokens: 120,
  output_tokens: 30,
  cost_usd: '0.0004',
  domain: 'example.com',
  created_at: '2026-07-01T00:00:00Z',
};

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

describe('useAdminLlm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listLlmProviders.mockResolvedValue(PROVIDERS);
    apiMock.listLlmConfigs.mockResolvedValue([CONFIG]);
    apiMock.listLlmCostLog.mockResolvedValue([COST_ENTRY]);
  });

  it('loads providers, configs, and cost log through the query-key factories', async () => {
    const { queryClient, wrapper } = createHarness();
    const { result } = renderHook(() => useAdminLlm(), { wrapper });

    await waitFor(() => expect(result.current.configs).toHaveLength(1));
    await waitFor(() => expect(result.current.costLog).toHaveLength(1));

    expect(result.current.providers).toEqual(PROVIDERS);
    expect(result.current.error).toBe('');
    expect(apiMock.listLlmConfigs).toHaveBeenCalledWith({ include_unsupported: true });
    expect(apiMock.listLlmCostLog).toHaveBeenCalledWith();

    const cachedKeys = queryClient
      .getQueryCache()
      .findAll()
      .map((query) => query.queryKey);
    expect(cachedKeys).toContainEqual(['admin', 'llm', 'providers']);
    expect(cachedKeys).toContainEqual(['admin', 'llm', 'configs']);
    expect(cachedKeys).toContainEqual(['admin', 'llm', 'costs']);
  });

  it('aligns the form to the provider catalog once providers arrive', async () => {
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useAdminLlm(), { wrapper });

    // INITIAL_LLM_FORM points at mistral, which the catalog does not list.
    expect(result.current.form.provider).toBe(INITIAL_LLM_FORM.provider);
    await waitFor(() => expect(result.current.form.provider).toBe('openrouter'));
    expect(result.current.form.model).toBe('openai/gpt-4o-mini');
  });

  it('save invalidates configs and costs and clears api_key from the form', async () => {
    const { queryClient, wrapper } = createHarness();
    apiMock.createLlmConfig.mockResolvedValue(CONFIG);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useAdminLlm(), { wrapper });

    await waitFor(() => expect(result.current.configs).toHaveLength(1));

    act(() => result.current.patchForm({ api_key: 'sk-secret' }));
    expect(result.current.form.api_key).toBe('sk-secret');

    act(() => result.current.handleSave());

    await waitFor(() => expect(result.current.message).toBe('LLM config saved.'));
    expect(result.current.form.api_key).toBe('');
    expect(result.current.error).toBe('');
    expect(apiMock.createLlmConfig).toHaveBeenCalledWith(
      expect.objectContaining({ api_key: 'sk-secret' }),
      expect.anything(),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['admin', 'llm', 'configs'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['admin', 'llm', 'costs'] });
  });

  it('failed save surfaces the error message', async () => {
    const { wrapper } = createHarness();
    apiMock.createLlmConfig.mockRejectedValue(new Error('Provider rejected the key'));
    const { result } = renderHook(() => useAdminLlm(), { wrapper });

    await waitFor(() => expect(result.current.configs).toHaveLength(1));

    act(() => result.current.handleSave());

    await waitFor(() => expect(result.current.error).toBe('Provider rejected the key'));
    expect(result.current.message).toBe('');
  });

  it('delete invalidates configs and costs', async () => {
    const { queryClient, wrapper } = createHarness();
    apiMock.deleteLlmConfig.mockResolvedValue(undefined);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useAdminLlm(), { wrapper });

    await waitFor(() => expect(result.current.configs).toHaveLength(1));

    act(() => result.current.handleDelete(1));

    await waitFor(() => expect(result.current.message).toBe('LLM config removed.'));
    expect(apiMock.deleteLlmConfig).toHaveBeenCalledWith(1, expect.anything());
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['admin', 'llm', 'configs'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['admin', 'llm', 'costs'] });
  });
});
