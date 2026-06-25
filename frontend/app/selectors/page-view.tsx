import { AlertCircle, Check, CheckCircle2, Plus, Search, Sparkles, Trash2 } from 'lucide-react';
import { EmptyPanel, InlineAlert, PageHeader, SectionCard } from '../../components/ui/patterns';
import { Badge, Button, Dropdown, Field, Input, Textarea } from '../../components/ui/primitives';
import { cn } from '../../lib/utils';
import { type RowState, type SelectorKind, type SelectorRow } from './selector-page-utils';
import { type RowMessage, useSelectorsWorkspace } from './use-selectors-workspace';


// skipcq: JS-0067
export default function SelectorsPage() {
  const {
    state,
    dispatch,
    loadPageAndSuggestions,
    updateRow,
    addFieldRow,
    removeFieldRow,
    redetectRow,
    testRow,
    saveAcceptedRows,
  } = useSelectorsWorkspace();

  const {
    url,
    loadedUrl,
    previewHtml,
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

  return (
    <div className="page-stack-lg">
      <PageHeader title="CSS / XPath Selector" />

      <SelectorInputsCard
        url={url}
        expectedColumns={expectedColumns}
        loadingSuggestions={loadingSuggestions}
        loadError={loadError}
        onUrlChange={(value) => dispatch({ type: 'urlChanged', value })}
        onExpectedColumnsChange={(value) => dispatch({ type: 'expectedColumnsChanged', value })}
        onLoadPage={() => void loadPageAndSuggestions()}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
        <PagePreviewCard
          loadedUrl={loadedUrl}
          resolvedSurface={resolvedSurface}
          iframePromoted={iframePromoted}
          previewHtml={previewHtml}
        />

        <FieldRowsCard
          rows={rows}
          rowMessages={rowMessages}
          activeDetectKey={activeDetectKey}
          activeTestKey={activeTestKey}
          savingAccepted={savingAccepted}
          onAddFieldRow={addFieldRow}
          onUpdateRow={updateRow}
          onRedetectRow={(row) => void redetectRow(row)}
          onTestRow={(row) => void testRow(row)}
          onRemoveFieldRow={removeFieldRow}
          onSaveAcceptedRows={() => void saveAcceptedRows()}
        />
      </div>
    </div>
  );
}

interface SelectorInputsCardProps {
  url: string;
  expectedColumns: string;
  loadingSuggestions: boolean;
  loadError: string;
  onUrlChange: (value: string) => void;
  onExpectedColumnsChange: (value: string) => void;
  onLoadPage: () => void;
}

function SelectorInputsCard({
  url,
  expectedColumns,
  loadingSuggestions,
  loadError,
  onUrlChange,
  onExpectedColumnsChange,
  onLoadPage,
}: Readonly<SelectorInputsCardProps>) {
  return (
    <SectionCard
      title="Selector Inputs"
      description="Enter a page URL and expected column names, then let the LLM suggest selectors for each field."
    >
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)_auto] xl:items-end">
        <Field label="Page URL">
          <Input
            value={url}
            onChange={(event) => onUrlChange(event.target.value)}
            placeholder="https://example.com/products/oak-chair"
            className="font-mono text-sm leading-relaxed"
          />
        </Field>
        <Field label="Expected Columns">
          <Textarea
            value={expectedColumns}
            onChange={(event) => onExpectedColumnsChange(event.target.value)}
            placeholder="price, sku, availability, brand"
            className="min-h-[80px] text-sm leading-relaxed"
          />
        </Field>
        <Button
          type="button"
          variant="action"
          onClick={onLoadPage}
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
  );
}

interface PagePreviewCardProps {
  loadedUrl: string;
  resolvedSurface: string;
  iframePromoted: boolean;
  previewHtml: string;
}

function PagePreviewCard({
  loadedUrl,
  resolvedSurface,
  iframePromoted,
  previewHtml,
}: Readonly<PagePreviewCardProps>) {
  return (
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
        {previewHtml ? (
          <iframe
            key={loadedUrl}
            srcDoc={previewHtml}
            title="Selector page preview"
            className="bg-panel h-[760px] w-full"
            loading="lazy"
            referrerPolicy="no-referrer"
            sandbox="allow-same-origin"
          />
        ) : (
          <div className="text-muted grid h-[760px] place-items-center text-sm leading-relaxed">
            {loadedUrl ? 'Preview fetch failed.' : 'No page loaded.'}
          </div>
        )}
      </div>
    </SectionCard>
  );
}

interface FieldRowsCardProps {
  rows: SelectorRow[];
  rowMessages: Record<string, RowMessage>;
  activeDetectKey: string | null;
  activeTestKey: string | null;
  savingAccepted: boolean;
  onAddFieldRow: () => void;
  onUpdateRow: (key: string, patch: Partial<SelectorRow>) => void;
  onRedetectRow: (row: SelectorRow) => void;
  onTestRow: (row: SelectorRow) => void;
  onRemoveFieldRow: (key: string) => void;
  onSaveAcceptedRows: () => void;
}

function FieldRowsCard({
  rows,
  rowMessages,
  activeDetectKey,
  activeTestKey,
  savingAccepted,
  onAddFieldRow,
  onUpdateRow,
  onRedetectRow,
  onTestRow,
  onRemoveFieldRow,
  onSaveAcceptedRows,
}: Readonly<FieldRowsCardProps>) {
  return (
    <SectionCard
      title="Field Rows"
      description="Review LLM suggestions, edit selectors manually, test arbitrary XPath/CSS/regex, then accept the rows you want to save."
      action={
        <Button type="button" variant="quiet" onClick={onAddFieldRow}>
          <Plus className="size-3.5" />
          Add Field
        </Button>
      }
    >
      {rows.length ? (
        <div className="space-y-5">
          {rows.map((row) => {
            const message = rowMessages[row.key];
            return (
              <SelectorFieldRow
                key={row.key}
                row={row}
                message={message}
                activeDetectKey={activeDetectKey}
                activeTestKey={activeTestKey}
                onUpdate={onUpdateRow}
                onRedetect={() => onRedetectRow(row)}
                onTest={() => onTestRow(row)}
                onRemove={() => onRemoveFieldRow(row.key)}
              />
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
          onClick={onSaveAcceptedRows}
          disabled={savingAccepted || !rows.some((row) => row.state === 'accepted')}
        >
          <Check className="size-3.5" />
          {savingAccepted ? 'Saving...' : 'Save Accepted Selectors'}
        </Button>
      </div>
    </SectionCard>
  );
}

function selectorPlaceholder(kind: SelectorKind) {
  if (kind === 'xpath') return "//span[@class='price']";
  if (kind === 'css_selector') return '.price';
  return '\\$[\\d,.]+';
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

// ── SelectorFieldRow sub-component ────────────────────────────────────────────────────

interface SelectorFieldRowProps {
  row: SelectorRow;
  message: RowMessage | undefined;
  activeDetectKey: string | null;
  activeTestKey: string | null;
  onUpdate: (key: string, patch: Partial<SelectorRow>) => void;
  onRedetect: () => void;
  onTest: () => void;
  onRemove: () => void;
}

function SelectorFieldRow({
  row,
  message,
  activeDetectKey,
  activeTestKey,
  onUpdate,
  onRedetect,
  onTest,
  onRemove,
}: Readonly<SelectorFieldRowProps>) {
  const selectorInputId = `selector-value-${row.key}`;
  return (
    <div className="border-border bg-background-elevated rounded-lg border p-5">
      <div className="grid gap-4">
        <div className="grid gap-4 xl:grid-cols-[160px_130px_minmax(0,1fr)_auto] xl:items-end">
          <Field label="Field Name">
            <Input
              value={row.fieldName}
              onChange={(event) =>
                onUpdate(row.key, {
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
              onChange={(kind) => onUpdate(row.key, { kind, state: nextEditedState(row.state) })}
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
                  onUpdate(row.key, {
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
              onClick={onRemove}
              aria-label="Delete field row"
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </div>

        <Field label="Extracted Value Preview">
          <Input
            value={row.extractedValue}
            onChange={(event) => onUpdate(row.key, { extractedValue: event.target.value })}
            placeholder="Extracted value"
            className="font-mono text-sm leading-relaxed"
          />
        </Field>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="neutral"
            onClick={onRedetect}
            disabled={activeDetectKey === row.key}
          >
            <Sparkles className="size-3.5" />
            {activeDetectKey === row.key ? 'Detecting…' : 'Auto-detect'}
          </Button>
          <Button
            type="button"
            variant="neutral"
            onClick={onTest}
            disabled={activeTestKey === row.key}
          >
            <Search className="size-3.5" />
            {activeTestKey === row.key ? 'Testing...' : 'Test'}
          </Button>
          <Button
            type="button"
            variant={row.state === 'accepted' || row.state === 'saved' ? 'neutral' : 'quiet'}
            onClick={() => onUpdate(row.key, { state: nextSelectorRowState(row.state) })}
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
}
