import { api } from '../../lib/api';
import type { CrawlSurface } from '../../lib/api/types';
import {
  buildFieldRowFromSuggestion,
  mergeFieldRows,
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

  return {
    addManualField,
    generateFieldSelectors,
    testFieldRow,
  };
}
