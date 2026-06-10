'use client';

// Next.js App Router entrypoint for `/selectors`; invoked by file-system routing.
import { AlertCircle, Check, CheckCircle2, Plus, Search, Sparkles, Trash2 } from 'lucide-react';
import { useReducer } from 'react';

import { EmptyPanel, InlineAlert, PageHeader, SectionCard } from '../../components/ui/patterns';
import { Badge, Button, Dropdown, Field, Input, Textarea } from '../../components/ui/primitives';
import { api } from '../../lib/api';
import { httpErrorStatus } from '../../lib/api/client';
import type {
  SelectorCreatePayload,
  SelectorRecord,
  SelectorSuggestion,
} from '../../lib/api/types';
import { getNormalizedDomain } from '../../lib/format/domain';
import { cn } from '../../lib/utils';
import {
  inferSelectorSurface,
  mergeSelectorRows,
  normalizeField,
  selectRelevantSelectorRecords,
  type RowState,
  type SelectorKind,
  type SelectorRow,
} from './selector-page-utils';

type StatusTone = 'success' | 'warning' | 'danger';

type RowMessage = {
  tone: StatusTone;
  message: string;
};

type SelectorsPageState = {
  url: string;
  loadedUrl: string;
  previewUrl: string;
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

type SelectorsPageAction =
  | { type: 'urlChanged'; value: string }
  | { type: 'expectedColumnsChanged'; value: string }
  | { type: 'loadFailed'; message: string }
  | { type: 'suggestionsStarted' }
  | {
      type: 'suggestionsLoaded';
      loadedUrl: string;
      previewUrl: string;
      resolvedSurface: string;
      iframePromoted: boolean;
      rows: SelectorRow[];
    }
  | { type: 'suggestionsFinished' }
  | { type: 'rowPatched'; key: string; patch: Partial<SelectorRow> }
  | { type: 'rowAdded' }
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
  previewUrl: '',
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
        previewUrl: action.previewUrl,
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
    case 'rowRemoved': {
      const nextMessages = { ...state.rowMessages };
      delete nextMessages[action.key];
      return {
        ...state,
        rows: state.rows.filter((row) => row.key !== action.key),
        rowMessages: nextMessages,
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
        rows: state.rows.map((entry) =>
          action.savedRows.has(entry.key)
            ? {
                ...entry,
                selectorId: action.savedRows.get(entry.key) ?? entry.selectorId,
                surface: action.resolvedSurface,
                state: 'saved',
              }
            : entry,
        ),
        rowMessages: { ...remainingMessages, ...action.nextMessages },
      };
    }
  }
}

// skipcq: JS-0067
export default function SelectorsPage() {
  const [state, dispatch] = useReducer(selectorsPageReducer, INITIAL_SELECTORS_PAGE_STATE);
  const {
    url,
    loadedUrl,
    previewUrl,
    resolvedSurface,
    iframePromoted,
    expectedColumns,
    rows,
    rowMessages,
    loadError,
    loadingSuggestions,
    savingAccepted,
    activeTestKey,
    activeDetectKey,
  } = state;

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
      const savedRecords = selectorDomain
        ? await api.listSelectors({ domain: selectorDomain, surface: nextSurface })
        : [];
      const savedRows = selectRelevantSelectorRecords(savedRecords, nextSurface).map(
        buildRowFromSelectorRecord,
      );
      const suggestedRows = parsedColumns.map((field) => {
        const suggestion = response.suggestions[field]?.[0];
        return buildRowFromSuggestion(field, suggestion, nextSurface);
      });
      dispatch({
        type: 'suggestionsLoaded',
        loadedUrl: previewTargetUrl,
        previewUrl: api.selectorPreviewHtml(previewTargetUrl),
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

  function addFieldRow() {
    dispatch({ type: 'rowAdded' });
  }

  function removeFieldRow(key: string) {
    dispatch({ type: 'rowRemoved', key });
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
      const response = await api.suggestSelectors({
        url: loadedUrl,
        expected_columns: [normalizeField(row.fieldName)],
      });
      const suggestion = response.suggestions[normalizeField(row.fieldName)]?.[0];
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
        xpath: row.kind === 'xpath' ? row.selectorValue.trim() : undefined,
        css_selector: row.kind === 'css_selector' ? row.selectorValue.trim() : undefined,
        regex: row.kind === 'regex' ? row.selectorValue.trim() : undefined,
      });
      updateRow(row.key, {
        extractedValue: response.matched_value ?? '',
      });
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
        acceptedRows.map(async (row) => {
          const fieldName = normalizeField(row.fieldName);
          const payload: SelectorCreatePayload = {
            domain,
            surface: resolvedSurface,
            field_name: fieldName,
            xpath: row.kind === 'xpath' ? row.selectorValue.trim() : undefined,
            css_selector: row.kind === 'css_selector' ? row.selectorValue.trim() : undefined,
            regex: row.kind === 'regex' ? row.selectorValue.trim() : undefined,
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
            const duplicateRecord =
              existingByField.get(fieldName) ??
              selectRelevantSelectorRecords(
                await api.listSelectors({ domain, surface: resolvedSurface }),
                resolvedSurface,
              ).find((record) => normalizeField(record.field_name) === fieldName);
            if (!duplicateRecord) {
              throw error;
            }
            existingByField.set(fieldName, duplicateRecord);
            const updated = await api.updateSelector(duplicateRecord.id, payload);
            return { key: row.key, selectorId: updated.id };
          }
        }),
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

  return (
    <div className="page-stack-lg">
      <PageHeader title="CSS / XPath Selector" />

      <SectionCard
        title="Selector Inputs"
        description="Enter a page URL and expected column names, then let the LLM suggest selectors for each field."
      >
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)_auto] xl:items-end">
          <Field label="Page URL">
            <Input
              value={url}
              onChange={(event) => dispatch({ type: 'urlChanged', value: event.target.value })}
              placeholder="https://example.com/products/oak-chair"
              className="font-mono text-sm leading-relaxed"
            />
          </Field>
          <Field label="Expected Columns">
            <Textarea
              value={expectedColumns}
              onChange={(event) =>
                dispatch({ type: 'expectedColumnsChanged', value: event.target.value })
              }
              placeholder="price, sku, availability, brand"
              className="min-h-[80px] text-sm leading-relaxed"
            />
          </Field>
          <Button
            type="button"
            variant="action"
            onClick={() => void loadPageAndSuggestions()}
            disabled={loadingSuggestions}
            className="w-full xl:w-auto"
          >
            <Sparkles className="size-3.5" />
            {loadingSuggestions ? 'Loading…' : 'Load Page'}
          </Button>
        </div>
        {loadError ? (
          <div className="mt-4">
            <InlineAlert message={loadError} />
          </div>
        ) : null}
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
        <SectionCard
          title="Page Preview"
          description={loadedUrl || 'Load a page to preview its DOM context.'}
          action={
            loadedUrl ? (
              <div className="flex items-center gap-2">
                <Badge tone="info">{resolvedSurface}</Badge>
                {iframePromoted ? <Badge tone="warning">iframe promoted</Badge> : null}
              </div>
            ) : null
          }
        >
          <div className="bg-panel shadow-card overflow-hidden rounded-none p-0 backdrop-blur-md">
            {previewUrl ? (
              <iframe
                key={previewUrl}
                src={previewUrl}
                title="Selector page preview"
                className="bg-panel h-[760px] w-full"
                loading="lazy"
                referrerPolicy="no-referrer"
                sandbox="allow-same-origin"
              />
            ) : (
              <div className="text-muted grid h-[760px] place-items-center text-sm leading-relaxed">
                No page loaded.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard
          title="Field Rows"
          description="Review LLM suggestions, edit selectors manually, test arbitrary XPath/CSS/regex, then accept the rows you want to save."
          action={
            <Button type="button" variant="quiet" onClick={addFieldRow}>
              <Plus className="size-3.5" />
              Add Field
            </Button>
          }
        >
          {rows.length ? (
            <div className="space-y-5">
              {rows.map((row) => {
                const message = rowMessages[row.key];
                const selectorInputId = `selector-value-${row.key}`;
                return (
                  <div
                    key={row.key}
                    className="border-border bg-background-elevated rounded-lg border p-5"
                  >
                    <div className="grid gap-4">
                      <div className="grid gap-4 xl:grid-cols-[160px_130px_minmax(0,1fr)_auto] xl:items-end">
                        <Field label="Field Name">
                          <Input
                            value={row.fieldName}
                            onChange={(event) =>
                              updateRow(row.key, {
                                fieldName: event.target.value,
                                state: nextEditedState(row.state),
                              })
                            }
                            placeholder="price"
                          />
                        </Field>

                        <Field label="Type">
                          <Dropdown<SelectorKind>
                            value={row.kind}
                            onChange={(kind) =>
                              updateRow(row.key, { kind, state: nextEditedState(row.state) })
                            }
                            options={[
                              { value: 'xpath', label: 'XPath' },
                              { value: 'css_selector', label: 'CSS' },
                              { value: 'regex', label: 'Regex' },
                            ]}
                            ariaLabel="Selector type"
                          />
                        </Field>

                        <label className="grid gap-2" htmlFor={selectorInputId}>
                          <span className="field-label">XPath / CSS / Regex</span>
                          <div className="relative">
                            <Input
                              id={selectorInputId}
                              value={row.selectorValue}
                              onChange={(event) =>
                                updateRow(row.key, {
                                  selectorValue: event.target.value,
                                  state: nextEditedState(row.state),
                                })
                              }
                              placeholder={selectorPlaceholder(row.kind)}
                              className="pr-10 font-mono text-sm leading-relaxed"
                            />
                            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                              {row.selectorValue.trim() ? (
                                <CheckCircle2 className="text-success size-4" />
                              ) : (
                                <AlertCircle className="text-muted size-4" />
                              )}
                            </div>
                          </div>
                        </label>

                        <div className="flex items-center justify-end xl:h-[40px]">
                          <Button
                            type="button"
                            variant="destructive"
                            size="icon"
                            onClick={() => removeFieldRow(row.key)}
                            aria-label="Delete field row"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </div>

                      <Field label="Extracted Value Preview">
                        <Input
                          value={row.extractedValue}
                          onChange={(event) =>
                            updateRow(row.key, { extractedValue: event.target.value })
                          }
                          placeholder="Extracted value"
                          className="font-mono text-sm leading-relaxed"
                        />
                      </Field>

                      <div className="flex flex-wrap items-center gap-3">
                        <Button
                          type="button"
                          variant="neutral"
                          onClick={() => void redetectRow(row)}
                          disabled={activeDetectKey === row.key}
                        >
                          <Sparkles className="size-3.5" />
                          {activeDetectKey === row.key ? 'Detecting…' : 'Auto-detect'}
                        </Button>
                        <Button
                          type="button"
                          variant="neutral"
                          onClick={() => void testRow(row)}
                          disabled={activeTestKey === row.key}
                        >
                          <Search className="size-3.5" />
                          {activeTestKey === row.key ? 'Testing...' : 'Test'}
                        </Button>
                        <Button
                          type="button"
                          variant={
                            row.state === 'accepted' || row.state === 'saved' ? 'neutral' : 'quiet'
                          }
                          onClick={() =>
                            updateRow(row.key, { state: nextSelectorRowState(row.state) })
                          }
                          disabled={row.state === 'saved'}
                        >
                          <Check className="size-3.5" />
                          {selectorStateLabel(row.state)}
                        </Button>
                        <Badge tone={selectorStateTone(row.state)}>{row.state}</Badge>
                      </div>

                      {message ? (
                        <div
                          className={cn(
                            'alert-surface',
                            message.tone === 'success' && 'alert-success',
                            message.tone === 'warning' && 'alert-warning',
                            message.tone === 'danger' && 'alert-danger',
                          )}
                        >
                          {message.message}
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyPanel
              title="No field rows yet"
              description="Load a page with expected columns to generate LLM suggestions."
            />
          )}

          <div className="border-border flex justify-end border-t pt-4">
            <Button
              type="button"
              variant="action"
              onClick={() => void saveAcceptedRows()}
              disabled={savingAccepted || !rows.some((row) => row.state === 'accepted')}
            >
              <Check className="size-3.5" />
              {savingAccepted ? 'Saving...' : 'Save Accepted Selectors'}
            </Button>
          </div>
        </SectionCard>
      </div>
    </div>
  );
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

function selectorPlaceholder(kind: SelectorKind) {
  if (kind === 'xpath') return "//span[@class='price']";
  if (kind === 'css_selector') return '.price';
  return '\\$[\\d,.]+';
}

function selectorSource(kind: SelectorKind) {
  if (kind === 'xpath') return 'llm_xpath';
  if (kind === 'css_selector') return 'llm_css';
  return 'llm_regex';
}

function formatSelectorMatchMessage(count: number) {
  if (count <= 0) {
    return 'No matches.';
  }
  const suffix = count === 1 ? '' : 's';
  return `Matched ${count} result${suffix}.`;
}

function nextSelectorRowState(state: RowState): RowState {
  if (state === 'saved') return 'saved';
  if (state === 'accepted') return 'idle';
  return 'accepted';
}

function selectorStateLabel(state: RowState) {
  if (state === 'saved') return 'Saved';
  if (state === 'accepted') return 'Accepted';
  return 'Accept';
}

function selectorStateTone(state: RowState) {
  if (state === 'saved') return 'success' as const;
  if (state === 'accepted') return 'warning' as const;
  return 'neutral' as const;
}

function nextEditedState(state: RowState): RowState {
  if (state === 'saved') return 'accepted';
  if (state === 'idle') return 'idle';
  return state;
}

function buildRowFromSelectorRecord(record: SelectorRecord): SelectorRow {
  if (record.xpath) {
    return {
      key: `selector:${record.id}`,
      selectorId: record.id,
      surface: record.surface,
      fieldName: record.field_name,
      kind: 'xpath',
      selectorValue: record.xpath,
      extractedValue: record.sample_value || '',
      source: record.source || 'domain_memory',
      state: 'saved',
    };
  }
  if (record.css_selector) {
    return {
      key: `selector:${record.id}`,
      selectorId: record.id,
      surface: record.surface,
      fieldName: record.field_name,
      kind: 'css_selector',
      selectorValue: record.css_selector,
      extractedValue: record.sample_value || '',
      source: record.source || 'domain_memory',
      state: 'saved',
    };
  }
  return {
    key: `selector:${record.id}`,
    selectorId: record.id,
    surface: record.surface,
    fieldName: record.field_name,
    kind: 'regex',
    selectorValue: record.regex || '',
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
  if (suggestion?.xpath) {
    return {
      key: createRowKey(),
      selectorId: null,
      surface: surface ?? null,
      fieldName,
      kind: 'xpath',
      selectorValue: suggestion.xpath,
      extractedValue: suggestion.sample_value || '',
      source: suggestion.source || 'llm_xpath',
      state: 'idle',
    };
  }
  if (suggestion?.css_selector) {
    return {
      key: createRowKey(),
      selectorId: null,
      surface: surface ?? null,
      fieldName,
      kind: 'css_selector',
      selectorValue: suggestion.css_selector,
      extractedValue: suggestion.sample_value || '',
      source: suggestion.source || 'llm_css',
      state: 'idle',
    };
  }
  if (suggestion?.regex) {
    return {
      key: createRowKey(),
      selectorId: null,
      surface: surface ?? null,
      fieldName,
      kind: 'regex',
      selectorValue: suggestion.regex,
      extractedValue: suggestion.sample_value || '',
      source: suggestion.source || 'llm_regex',
      state: 'idle',
    };
  }
  return {
    key: createRowKey(),
    selectorId: null,
    surface: surface ?? null,
    fieldName,
    kind: 'xpath',
    selectorValue: '',
    extractedValue: '',
    source: 'manual',
    state: 'idle',
  };
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

function createRowKey() {
  return `selector:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function isDuplicateSelectorError(error: unknown): boolean {
  if (httpErrorStatus(error) === 409) {
    return true;
  }
  const fragments = [];
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
