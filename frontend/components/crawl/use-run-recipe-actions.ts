import { useState } from 'react';

import { api } from '../../lib/api';

export type RecipeActionPendingKey = `field:${string}:${'keep' | 'reject'}`;

type UseRunRecipeActionsOptions = {
  runId: number;
  refetchRecipe: () => Promise<unknown>;
};

export function useRunRecipeActions({
  runId,
  refetchRecipe,
}: Readonly<UseRunRecipeActionsOptions>) {
  const [pendingKey, setPendingKey] = useState<RecipeActionPendingKey | null>(null);
  const [error, setError] = useState('');

  async function applyFieldAction(
    fieldName: string,
    action: 'keep' | 'reject',
    selectorKind?: string | null,
    selectorValue?: string | null,
    sourceRecordIds?: number[],
  ) {
    setPendingKey(`field:${fieldName}:${action}`);
    setError('');
    try {
      await api.applyDomainRecipeFieldAction(runId, {
        field_name: fieldName,
        action,
        selector_kind: selectorKind ?? null,
        selector_value: selectorValue ?? null,
        source_record_ids: sourceRecordIds ?? [],
      });
      await refetchRecipe();
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : `Unable to ${action} this field learning signal.`,
      );
    } finally {
      setPendingKey(null);
    }
  }

  return {
    pendingKey,
    error,
    applyFieldAction,
  };
}
