import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type { CrawlSurface } from '../../lib/api/types';
import { getNormalizedDomain } from '../../lib/format/domain';
import {
  buildFieldRowFromSuggestion,
  mergeFieldRows,
  selectRelevantSelectorRecords,
  selectorGenerationFields,
} from './crawl-config-logic';
import type { bindCrawlConfigLocalDispatch } from './crawl-config-state';
import { testCrawlFieldRow } from './crawl-field-test';
import { createManualFieldRowId } from './use-crawl-config';
import { normalizeField, type FieldRow } from './shared';

type LocalDispatch = Pick<
  ReturnType<typeof bindCrawlConfigLocalDispatch>,
  | 'setActiveFieldTestId'
  | 'setFieldConfigError'
  | 'setFieldConfigMessage'
  | 'setFieldRowMessages'
  | 'setGeneratingSelectors'
  | 'setSavingDomainMemory'
>;

type SetFieldRows = (next: FieldRow[] | ((current: FieldRow[]) => FieldRow[])) => void;

type UseCrawlFieldActionsOptions = {
  targetUrl: string;
  surface: CrawlSurface;
  fieldRows: FieldRow[];
  additionalFields: string[];
  setFieldRows: SetFieldRows;
  localDispatch: LocalDispatch;
};

export function useCrawlFieldActions({
  targetUrl,
  surface,
  fieldRows,
  additionalFields,
  setFieldRows,
  localDispatch,
}: Readonly<UseCrawlFieldActionsOptions>) {
  const queryClient = useQueryClient();

  function addManualField() {
    setFieldRows((current) => [
      ...current,
      {
        id: createManualFieldRowId(),
        fieldName: '',
        cssSelector: '',
        xpath: '',
        regex: '',
        cssState: 'idle',
        xpathState: 'idle',
        regexState: 'idle',
      },
    ]);
  }

  async function generateFieldSelectors() {
    const target = targetUrl.trim();
    if (!target) {
      localDispatch.setFieldConfigError('Enter a target URL before generating selectors.');
      return;
    }
    const expectedColumns = selectorGenerationFields(surface, fieldRows, additionalFields);
    if (!expectedColumns.length) {
      localDispatch.setFieldConfigError(
        'Add at least one field or additional field before generating selectors.',
      );
      return;
    }

    localDispatch.setGeneratingSelectors(true);
    localDispatch.setFieldConfigError('');
    try {
      const response = await api.suggestSelectors({
        url: target,
        expected_columns: expectedColumns,
        surface,
      });
      const incomingRows = expectedColumns.map((fieldName) =>
        buildFieldRowFromSuggestion(
          fieldName,
          response.suggestions[normalizeField(fieldName)]?.[0],
        ),
      );
      setFieldRows((current) => mergeFieldRows(current, incomingRows));
      localDispatch.setFieldRowMessages({});
      localDispatch.setFieldConfigMessage(
        `Generated selector suggestions for ${expectedColumns.length} field${expectedColumns.length === 1 ? '' : 's'}.`,
      );
    } catch (error) {
      localDispatch.setFieldConfigError(
        error instanceof Error ? error.message : 'Unable to generate selectors.',
      );
    } finally {
      localDispatch.setGeneratingSelectors(false);
    }
  }

  async function testFieldRow(row: FieldRow) {
    await testCrawlFieldRow({
      row,
      targetUrl,
      setActiveId: localDispatch.setActiveFieldTestId,
      setMessage: (rowId, tone, message) =>
        localDispatch.setFieldRowMessages((current) => ({
          ...current,
          [rowId]: { tone, message },
        })),
    });
  }

  async function saveToDomainMemory() {
    const target = targetUrl.trim();
    const domain = getNormalizedDomain(target);
    if (!target || !domain) {
      localDispatch.setFieldConfigError('Enter a target URL before saving domain memory.');
      return;
    }

    const dedupedRows = dedupeSelectorRows(fieldRows);
    if (!dedupedRows.length) {
      localDispatch.setFieldConfigError(
        'Add at least one selector row before saving domain memory.',
      );
      return;
    }

    localDispatch.setSavingDomainMemory(true);
    localDispatch.setFieldConfigError('');
    try {
      const existingRecords = selectRelevantSelectorRecords(
        await api.listSelectors({ domain }),
        surface,
      );
      const existingByField = new Map(
        existingRecords.map((record) => [normalizeField(record.field_name), record] as const),
      );
      const settled = await Promise.allSettled(
        dedupedRows.map(async (row) => {
          const fieldName = normalizeField(row.fieldName);
          const payload = {
            field_name: fieldName,
            css_selector: row.cssSelector.trim() || undefined,
            xpath: row.xpath.trim() || undefined,
            regex: row.regex.trim() || undefined,
            source: 'crawl_config',
            status: 'validated' as const,
            is_active: true,
          };
          const existing = existingByField.get(fieldName);
          if (existing) {
            await api.updateSelector(existing.id, payload);
          } else {
            await api.createSelector({ domain, surface, ...payload });
          }
          if (row.id.startsWith('generated-') && row.cssSelector.trim()) {
            await api
              .upsertKnowledgeSelectorContract({
                domain,
                url: target,
                surface,
                field_name: fieldName,
                css_selector: row.cssSelector.trim(),
                source: 'selector_suggestion',
              })
              .catch(() => undefined);
          }
        }),
      );
      const failedCount = settled.filter((result) => result.status === 'rejected').length;
      const savedCount = settled.length - failedCount;
      if (failedCount) {
        localDispatch.setFieldConfigError(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'}, ${failedCount} failed.`,
        );
      } else {
        localDispatch.setFieldConfigMessage(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'} to domain memory.`,
        );
      }
      if (savedCount) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.selectors.list({ domain, surface }),
        });
      }
    } catch (error) {
      localDispatch.setFieldConfigError(
        error instanceof Error ? error.message : 'Unable to save domain memory.',
      );
    } finally {
      localDispatch.setSavingDomainMemory(false);
    }
  }

  return {
    addManualField,
    generateFieldSelectors,
    testFieldRow,
    saveToDomainMemory,
    canSaveDomainMemory: dedupeSelectorRows(fieldRows).length > 0,
  };
}

function dedupeSelectorRows(fieldRows: FieldRow[]) {
  const deduped = new Map<string, FieldRow>();
  for (const row of fieldRows) {
    const field = normalizeField(row.fieldName);
    if (
      field &&
      !deduped.has(field) &&
      (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim())
    ) {
      deduped.set(field, row);
    }
  }
  return Array.from(deduped.values());
}
