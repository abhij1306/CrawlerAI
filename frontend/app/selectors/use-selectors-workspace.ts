import { useQueryClient } from '@tanstack/react-query';
import { useReducer } from 'react';

import { httpErrorStatus } from '@/api/client';
import { queryKeys } from '@/api/query-keys';
import { api } from '../../lib/api';
import type {
  SelectorCreatePayload,
  SelectorRecord,
  SelectorSuggestion,
} from '../../lib/api/types';
import { getNormalizedDomain } from '../../lib/format/domain';
import {
  inferSelectorSurface,
  mergeSelectorRows,
  normalizeField,
  selectRelevantSelectorRecords,
  type SelectorKind,
  type SelectorRow,
} from './selector-page-utils';

export type StatusTone = 'success' | 'warning' | 'danger';

export type RowMessage = {
  tone: StatusTone;
  message: string;
};

type SelectorsPageState = {
  url: string;
  loadedUrl: string;
  previewHtml: string;
  previewOpen: boolean;
  resolvedSurface: string;
  iframePromoted: boolean;
  expectedColumns: string;
  rows: SelectorRow[];
  rowMessages: Record<string, RowMessage>;
  loadError: string;
  loadingSuggestions: boolean;
  savingAccepted: boolean;
  activeTestKey: string | null;
  activeDetectKey: string | null;
};

export type SelectorsPageAction =
  | { type: 'urlChanged'; value: string }
  | { type: 'expectedColumnsChanged'; value: string }
  | { type: 'loadFailed'; message: string }
  | { type: 'suggestionsStarted' }
  | {
      type: 'suggestionsLoaded';
      loadedUrl: string;
      previewHtml: string;
      resolvedSurface: string;
      iframePromoted: boolean;
      rows: SelectorRow[];
    }
  | { type: 'suggestionsFinished' }
  | { type: 'rowPatched'; key: string; patch: Partial<SelectorRow> }
  | { type: 'rowAdded' }
  | { type: 'previewOpened' }
  | { type: 'rowRemoved'; key: string }
  | { type: 'rowMessageSet'; key: string; message: RowMessage }
  | { type: 'detectStarted'; key: string }
  | { type: 'detectFinished' }
  | { type: 'testStarted'; key: string }
  | { type: 'testFinished' }
  | { type: 'saveStarted' }
  | { type: 'saveFinished' }
  | {
      type: 'rowsSaved';
      savedRows: Map<string, number>;
      resolvedSurface: string;
      nextMessages: Record<string, RowMessage>;
    };

const INITIAL_SELECTORS_PAGE_STATE: SelectorsPageState = {
  url: '',
  loadedUrl: '',
  previewHtml: '',
  previewOpen: false,
  resolvedSurface: 'generic',
  iframePromoted: false,
  expectedColumns: '',
  rows: [],
  rowMessages: {},
  loadError: '',
  loadingSuggestions: false,
  savingAccepted: false,
  activeTestKey: null,
  activeDetectKey: null,
};

function createRowKey() {
  return `selector:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function createEmptyRow(): SelectorRow {
  return {
    key: createRowKey(),
    selectorId: null,
    surface: null,
    fieldName: '',
    kind: 'xpath',
    selectorValue: '',
    extractedValue: '',
    source: 'manual',
    state: 'idle',
  };
}

function selectorsPageReducer(
  state: SelectorsPageState,
  action: SelectorsPageAction,
): SelectorsPageState {
  switch (action.type) {
    case 'urlChanged':
      return { ...state, url: action.value };
    case 'expectedColumnsChanged':
      return { ...state, expectedColumns: action.value };
    case 'loadFailed':
      return { ...state, loadError: action.message };
    case 'suggestionsStarted':
      return { ...state, loadError: '', loadingSuggestions: true };
    case 'suggestionsLoaded':
      return {
        ...state,
        loadedUrl: action.loadedUrl,
        previewHtml: action.previewHtml,
        previewOpen: false,
        resolvedSurface: action.resolvedSurface,
        iframePromoted: action.iframePromoted,
        rows: action.rows,
        rowMessages: {},
      };
    case 'suggestionsFinished':
      return { ...state, loadingSuggestions: false };
    case 'rowPatched':
      return {
        ...state,
        rows: state.rows.map((row) => (row.key === action.key ? { ...row, ...action.patch } : row)),
      };
    case 'rowAdded':
      return { ...state, rows: [...state.rows, createEmptyRow()] };
    case 'previewOpened':
      return { ...state, previewOpen: true };
    case 'rowRemoved': {
      const rowMessages = { ...state.rowMessages };
      delete rowMessages[action.key];
      return {
        ...state,
        rows: state.rows.filter((row) => row.key !== action.key),
        rowMessages,
      };
    }
    case 'rowMessageSet':
      return {
        ...state,
        rowMessages: { ...state.rowMessages, [action.key]: action.message },
      };
    case 'detectStarted':
      return { ...state, activeDetectKey: action.key };
    case 'detectFinished':
      return { ...state, activeDetectKey: null };
    case 'testStarted':
      return { ...state, activeTestKey: action.key };
    case 'testFinished':
      return { ...state, activeTestKey: null };
    case 'saveStarted':
      return { ...state, savingAccepted: true, loadError: '' };
    case 'saveFinished':
      return { ...state, savingAccepted: false };
    case 'rowsSaved': {
      const remainingMessages = Object.fromEntries(
        Object.entries(state.rowMessages).filter(([key]) => !action.savedRows.has(key)),
      ) as Record<string, RowMessage>;
      return {
        ...state,
        rows: state.rows.map((row) =>
          action.savedRows.has(row.key)
            ? {
                ...row,
                selectorId: action.savedRows.get(row.key) ?? row.selectorId,
                surface: action.resolvedSurface,
                state: 'saved',
              }
            : row,
        ),
        rowMessages: { ...remainingMessages, ...action.nextMessages },
      };
    }
  }
}

const PREVIEW_HTML_MAX_CHARS = 500_000;

function capPreviewHtml(value: string) {
  if (value.length <= PREVIEW_HTML_MAX_CHARS) {
    return value;
  }
  return `${value.slice(0, PREVIEW_HTML_MAX_CHARS)}\n<!-- Preview truncated by CrawlerAI. Open source page for full document. -->`;
}

function parseExpectedColumns(value: string) {
  return Array.from(
    new Set(
      value.split(/[\n,]/).flatMap((item) => {
        const field = normalizeField(item);
        return field ? [field] : [];
      }),
    ),
  );
}

function selectorSource(kind: SelectorKind) {
  if (kind === 'xpath') return 'llm_xpath';
  if (kind === 'css_selector') return 'llm_css';
  return 'llm_regex';
}

function selectorExpression(kind: SelectorKind, value: string) {
  const selectorValue = value.trim();
  return {
    xpath: kind === 'xpath' ? selectorValue : undefined,
    css_selector: kind === 'css_selector' ? selectorValue : undefined,
    regex: kind === 'regex' ? selectorValue : undefined,
  };
}

function formatSelectorMatchMessage(count: number) {
  if (count <= 0) {
    return 'No matches.';
  }
  return `Matched ${count} result${count === 1 ? '' : 's'}.`;
}

function buildRowFromSelectorRecord(record: SelectorRecord): SelectorRow {
  const kind: SelectorKind = record.xpath
    ? 'xpath'
    : record.css_selector
      ? 'css_selector'
      : 'regex';
  return {
    key: `selector:${record.id}`,
    selectorId: record.id,
    surface: record.surface,
    fieldName: record.field_name,
    kind,
    selectorValue: record.xpath || record.css_selector || record.regex || '',
    extractedValue: record.sample_value || '',
    source: record.source || 'domain_memory',
    state: 'saved',
  };
}

function buildRowFromSuggestion(
  fieldName: string,
  suggestion?: SelectorSuggestion,
  surface?: string | null,
): SelectorRow {
  const kind: SelectorKind = suggestion?.xpath
    ? 'xpath'
    : suggestion?.css_selector
      ? 'css_selector'
      : suggestion?.regex
        ? 'regex'
        : 'xpath';
  return {
    key: createRowKey(),
    selectorId: null,
    surface: surface ?? null,
    fieldName,
    kind,
    selectorValue: suggestion?.xpath || suggestion?.css_selector || suggestion?.regex || '',
    extractedValue: suggestion?.sample_value || '',
    source: suggestion?.source || (suggestion ? selectorSource(kind) : 'manual'),
    state: 'idle',
  };
}

function isDuplicateSelectorError(error: unknown): boolean {
  if (httpErrorStatus(error) === 409) {
    return true;
  }
  const fragments: string[] = [];
  if (error instanceof Error) {
    fragments.push(error.message);
  }
  if (typeof error === 'object' && error !== null && 'body' in error) {
    const body = (error as { body?: unknown }).body;
    if (typeof body === 'string') {
      fragments.push(body);
    }
  }
  const message = fragments.join('').toLowerCase();
  return message.includes('already exists') || message.includes('duplicate');
}

async function saveSelectorRow(
  row: SelectorRow,
  domain: string,
  surface: string,
  existingByField: Map<string, SelectorRecord>,
) {
  const fieldName = normalizeField(row.fieldName);
  const payload: SelectorCreatePayload = {
    domain,
    surface,
    field_name: fieldName,
    ...selectorExpression(row.kind, row.selectorValue),
    sample_value: row.extractedValue.trim() || undefined,
    source: row.source || selectorSource(row.kind),
    status: 'validated',
    is_active: true,
  };
  const existing = row.selectorId ? { id: row.selectorId } : existingByField.get(fieldName);
  if (existing) {
    const updated = await api.updateSelector(existing.id, payload);
    return { key: row.key, selectorId: updated.id };
  }
  try {
    const created = await api.createSelector(payload);
    existingByField.set(fieldName, created);
    return { key: row.key, selectorId: created.id };
  } catch (error) {
    if (!isDuplicateSelectorError(error)) {
      throw error;
    }
    const duplicate =
      existingByField.get(fieldName) ??
      selectRelevantSelectorRecords(await api.listSelectors({ domain, surface }), surface).find(
        (record) => normalizeField(record.field_name) === fieldName,
      );
    if (!duplicate) {
      throw error;
    }
    existingByField.set(fieldName, duplicate);
    const updated = await api.updateSelector(duplicate.id, payload);
    return { key: row.key, selectorId: updated.id };
  }
}

// skipcq: JS-0067
export function useSelectorsWorkspace() {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(selectorsPageReducer, INITIAL_SELECTORS_PAGE_STATE);
  const { url, loadedUrl, resolvedSurface, expectedColumns, rows } = state;
  const parsedColumns = parseExpectedColumns(expectedColumns);
  const domain = getNormalizedDomain(loadedUrl);

  async function loadPageAndSuggestions() {
    const targetUrl = url.trim();
    if (!targetUrl) {
      dispatch({ type: 'loadFailed', message: 'Enter a page URL.' });
      return;
    }
    if (!parsedColumns.length) {
      dispatch({ type: 'loadFailed', message: 'Enter at least one expected column.' });
      return;
    }
    dispatch({ type: 'suggestionsStarted' });
    try {
      const response = await api.suggestSelectors({
        url: targetUrl,
        expected_columns: parsedColumns,
      });
      const previewTargetUrl = response.preview_url || targetUrl;
      const nextSurface = response.surface || inferSelectorSurface(parsedColumns, targetUrl);
      const selectorDomain =
        getNormalizedDomain(previewTargetUrl) || getNormalizedDomain(targetUrl);
      const [savedRecords, previewHtml] = await Promise.all([
        selectorDomain
          ? api.listSelectors({ domain: selectorDomain, surface: nextSurface })
          : Promise.resolve([]),
        api
          .getPreviewHtml(previewTargetUrl)
          .then(capPreviewHtml)
          .catch((error) => {
            console.error('Failed to load preview HTML:', error);
            return '';
          }),
      ]);
      const savedRows = selectRelevantSelectorRecords(savedRecords, nextSurface).map(
        buildRowFromSelectorRecord,
      );
      const suggestedRows = parsedColumns.map((field) =>
        buildRowFromSuggestion(field, response.suggestions[field]?.[0], nextSurface),
      );
      dispatch({
        type: 'suggestionsLoaded',
        loadedUrl: previewTargetUrl,
        previewHtml,
        resolvedSurface: nextSurface,
        iframePromoted: Boolean(response.iframe_promoted),
        rows: mergeSelectorRows(savedRows, suggestedRows),
      });
    } catch (error) {
      dispatch({
        type: 'loadFailed',
        message: error instanceof Error ? error.message : 'Unable to load selector suggestions.',
      });
    } finally {
      dispatch({ type: 'suggestionsFinished' });
    }
  }

  function updateRow(key: string, patch: Partial<SelectorRow>) {
    dispatch({ type: 'rowPatched', key, patch });
  }

  async function redetectRow(row: SelectorRow) {
    if (!loadedUrl || !row.fieldName.trim()) {
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: { tone: 'warning', message: 'Load a URL and enter a field name first.' },
      });
      return;
    }
    dispatch({ type: 'detectStarted', key: row.key });
    try {
      const fieldName = normalizeField(row.fieldName);
      const response = await api.suggestSelectors({
        url: loadedUrl,
        expected_columns: [fieldName],
      });
      const suggestion = response.suggestions[fieldName]?.[0];
      if (!suggestion) {
        dispatch({
          type: 'rowMessageSet',
          key: row.key,
          message: { tone: 'warning', message: 'No selector suggestion found for this field.' },
        });
        return;
      }
      const next = buildRowFromSuggestion(
        row.fieldName,
        suggestion,
        row.surface ?? resolvedSurface,
      );
      updateRow(row.key, {
        kind: next.kind,
        selectorValue: next.selectorValue,
        extractedValue: next.extractedValue,
        source: next.source,
        state: 'idle',
      });
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: { tone: 'success', message: 'Suggested selector refreshed.' },
      });
    } catch (error) {
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: {
          tone: 'danger',
          message: error instanceof Error ? error.message : 'Auto-detect failed.',
        },
      });
    } finally {
      dispatch({ type: 'detectFinished' });
    }
  }

  async function testRow(row: SelectorRow) {
    if (!loadedUrl || !row.selectorValue.trim()) {
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: { tone: 'warning', message: 'Load a URL and enter a selector to test.' },
      });
      return;
    }
    dispatch({ type: 'testStarted', key: row.key });
    try {
      const response = await api.testSelector({
        url: loadedUrl,
        ...selectorExpression(row.kind, row.selectorValue),
      });
      updateRow(row.key, { extractedValue: response.matched_value ?? '' });
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: {
          tone: response.count > 0 ? 'success' : 'warning',
          message: formatSelectorMatchMessage(response.count),
        },
      });
    } catch (error) {
      dispatch({
        type: 'rowMessageSet',
        key: row.key,
        message: {
          tone: 'danger',
          message: error instanceof Error ? error.message : 'Selector test failed.',
        },
      });
    } finally {
      dispatch({ type: 'testFinished' });
    }
  }

  async function saveAcceptedRows() {
    const acceptedRows = rows.filter(
      (row) => row.state === 'accepted' && row.fieldName.trim() && row.selectorValue.trim(),
    );
    if (!acceptedRows.length || !domain) {
      dispatch({ type: 'loadFailed', message: 'Accept at least one selector row before saving.' });
      return;
    }
    dispatch({ type: 'saveStarted' });
    const failedFields: string[] = [];
    try {
      const existingRecords = selectRelevantSelectorRecords(
        await api.listSelectors({ domain, surface: resolvedSurface }),
        resolvedSurface,
      );
      const existingByField = new Map(
        existingRecords.map((record) => [normalizeField(record.field_name), record] as const),
      );
      const settled = await Promise.allSettled(
        acceptedRows.map((row) => saveSelectorRow(row, domain, resolvedSurface, existingByField)),
      );
      const savedRows = new Map<string, number>();
      const nextMessages: Record<string, RowMessage> = {};
      settled.forEach((result, index) => {
        const row = acceptedRows[index];
        if (result.status === 'fulfilled') {
          savedRows.set(result.value.key, result.value.selectorId);
          return;
        }
        failedFields.push(row.fieldName.trim() || row.key);
        nextMessages[row.key] = {
          tone: 'danger',
          message:
            result.reason instanceof Error ? result.reason.message : 'Unable to save selector.',
        };
      });
      dispatch({ type: 'rowsSaved', savedRows, resolvedSurface, nextMessages });
      if (savedRows.size) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.selectors.list({ domain, surface: resolvedSurface }),
        });
        void queryClient.invalidateQueries({ queryKey: queryKeys.selectors.all });
      }
    } finally {
      dispatch({ type: 'saveFinished' });
    }
    if (failedFields.length) {
      dispatch({
        type: 'loadFailed',
        message: `Unable to save ${failedFields.join(', ')}. Saved rows stay marked as saved; failed rows remain accepted for retry.`,
      });
    }
  }

  return {
    state,
    dispatch,
    loadPageAndSuggestions,
    updateRow,
    addFieldRow: () => dispatch({ type: 'rowAdded' }),
    removeFieldRow: (key: string) => dispatch({ type: 'rowRemoved', key }),
    redetectRow,
    testRow,
    saveAcceptedRows,
  };
}
