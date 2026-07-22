import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { adminApi } from '@lib/api/admin';
import type { LlmConfigCreatePayload, LlmProviderCatalogItem } from '@lib/api/types';

export const INITIAL_LLM_FORM: LlmConfigCreatePayload = {
  provider: 'mistral',
  model: 'mistral-small-latest',
  task_type: 'data_enrichment_semantic',
  api_key: '',
  per_domain_daily_budget_usd: '0',
  global_session_budget_usd: '0',
  is_active: true,
};

function alignFormToProviders(
  current: LlmConfigCreatePayload,
  providers: LlmProviderCatalogItem[],
): LlmConfigCreatePayload {
  if (providers.length === 0) {
    return current;
  }
  const fallbackProvider = providers[0];
  const matchingProvider = providers.find((provider) => provider.provider === current.provider);
  if (matchingProvider) {
    if (current.model.trim()) {
      return current;
    }
    return {
      ...current,
      model: matchingProvider.recommended_models[0] ?? current.model,
    };
  }
  return {
    ...current,
    provider: fallbackProvider?.provider ?? current.provider,
    model: fallbackProvider?.recommended_models[0] ?? current.model,
  };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useAdminLlm() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<LlmConfigCreatePayload>(INITIAL_LLM_FORM);
  const [customModelSelected, setCustomModelSelected] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const providersQuery = useQuery({
    queryKey: queryKeys.admin.llmProviders(),
    queryFn: () => adminApi.listLlmProviders(),
  });
  const providers = providersQuery.data ?? [];

  const configsQuery = useQuery({
    queryKey: queryKeys.admin.llmConfigs(),
    queryFn: () => adminApi.listLlmConfigs({ include_unsupported: true }),
  });
  const configs = configsQuery.data ?? [];

  const costsQuery = useQuery({
    queryKey: queryKeys.admin.llmCosts(),
    queryFn: () => adminApi.listLlmCostLog(),
  });
  const costLog = costsQuery.data ?? [];

  // Align the form with the provider catalog once it first arrives (mirrors the
  // reducer's initialLoaded branch; later refetches must not clobber edits).
  const alignedRef = useRef(false);
  useEffect(() => {
    if (alignedRef.current || !providersQuery.data) return;
    alignedRef.current = true;
    setCustomModelSelected(false);
    setForm((current) => alignFormToProviders(current, providersQuery.data));
  }, [providersQuery.data]);

  const invalidateRuntimeQueries = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.llmConfigs() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.llmCosts() });
  };

  const createMutation = useMutation({
    mutationFn: adminApi.createLlmConfig,
    onMutate: () => {
      setError('');
      setMessage('');
    },
    onSuccess: () => {
      setMessage('LLM config saved.');
      setForm((current) => ({ ...current, api_key: '' }));
      invalidateRuntimeQueries();
    },
    onError: (nextError) => {
      setError(errorMessage(nextError, 'Unable to save LLM config.'));
    },
  });

  const testMutation = useMutation({
    mutationFn: adminApi.testLlmConnection,
    onMutate: () => {
      setError('');
      setMessage('');
    },
    onSuccess: (response) => {
      setMessage(response.message);
    },
    onError: (nextError) => {
      setError(errorMessage(nextError, 'Connection test failed.'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: adminApi.deleteLlmConfig,
    onMutate: () => {
      setError('');
      setMessage('');
    },
    onSuccess: () => {
      setMessage('LLM config removed.');
      invalidateRuntimeQueries();
    },
    onError: (nextError) => {
      setError(errorMessage(nextError, 'Unable to delete LLM config.'));
    },
  });

  const loadError = providersQuery.error ?? configsQuery.error ?? costsQuery.error;

  const patchForm = (patch: Partial<LlmConfigCreatePayload>) => {
    setForm((current) => ({ ...current, ...patch }));
  };

  const handleSave = () => {
    createMutation.mutate(form);
  };

  const handleTest = () => {
    testMutation.mutate({
      provider: form.provider,
      model: form.model,
      api_key: form.api_key,
    });
  };

  const handleDelete = (configId: number) => {
    deleteMutation.mutate(configId);
  };

  return {
    // queries
    providers,
    configs,
    costLog,
    // form state
    form,
    patchForm,
    customModelSelected,
    setCustomModelSelected,
    // feedback
    error: error || (loadError ? errorMessage(loadError, 'Unable to load LLM settings.') : ''),
    message,
    // actions
    handleSave,
    handleTest,
    handleDelete,
    saving: createMutation.isPending,
    testing: testMutation.isPending,
  };
}
