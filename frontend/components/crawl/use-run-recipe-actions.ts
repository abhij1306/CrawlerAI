import { useState } from 'react';

import { api } from '../../lib/api';
import type { DomainRecipeFieldLearningItem } from '../../lib/api/types';

export type RecipeActionPendingKey = `field:${string}:activate`;

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

  async function activateGroundedCorrection(item: DomainRecipeFieldLearningItem) {
    const selector = item.selector_value?.trim();
    const representativeIds = item.representative_url_result_ids;
    if (item.selector_kind !== 'css_selector' || !selector || !representativeIds.length) {
      setError('Grounded CSS evidence and representative run results are required.');
      return;
    }

    setPendingKey(`field:${item.field_name}:activate`);
    setError('');
    try {
      await api.saveGroundedCorrection(runId, {
        activate: true,
        representative_url_result_ids: representativeIds,
        labels: [
          {
            target_kind: 'field',
            subject_id: `run:${runId}:field:${item.field_name}`,
            record_id: item.source_record_ids[0] ? String(item.source_record_ids[0]) : null,
            field_name: item.field_name,
            canonical_value: item.value,
            semantic_role: 'observed_field_value',
            locale_interpretation: 'as_rendered',
            grounding: [
              {
                kind: 'node',
                artifact_id: `url-result:${representativeIds[0]}:page.html`,
                locator: `css:${selector}`,
              },
            ],
          },
        ],
      });
      await refetchRecipe();
    } catch (actionError) {
      setError(
        actionError instanceof Error
          ? actionError.message
          : 'Unable to activate this grounded correction.',
      );
    } finally {
      setPendingKey(null);
    }
  }

  return {
    pendingKey,
    error,
    activateGroundedCorrection,
  };
}
