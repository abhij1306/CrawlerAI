import { Plus, Sparkles } from 'lucide-react';

import { InlineAlert } from '../ui/patterns';
import { Button, Card } from '../ui/primitives';
import { FieldEditorHeader, ManualFieldEditor, type FieldRow } from './form-fields';
import type { FieldRowMessageTone } from './shared';

type FieldMessages = Record<string, { tone: FieldRowMessageTone; message: string }>;
type SetFieldRows = (next: FieldRow[] | ((current: FieldRow[]) => FieldRow[])) => void;

type CrawlFieldConfigCardProps = {
  fieldRows: FieldRow[];
  fieldMessages: FieldMessages;
  targetUrl: string;
  activeFieldTestId: string | null;
  generatingSelectors: boolean;
  message: string;
  error: string;
  setFieldRows: SetFieldRows;
  clearFieldMessage: (rowId: string) => void;
  onGenerate: () => void;
  onAddField: () => void;
  onTest: (row: FieldRow) => void;
};

export function CrawlFieldConfigCard({
  fieldRows,
  fieldMessages,
  targetUrl,
  activeFieldTestId,
  generatingSelectors,
  message,
  error,
  setFieldRows,
  clearFieldMessage,
  onGenerate,
  onAddField,
  onTest,
}: Readonly<CrawlFieldConfigCardProps>) {
  return (
    <Card className="section-card overflow-hidden p-0 xl:col-span-2">
      <header className="flex h-[38px] items-center justify-between border-b border-border bg-background px-5">
        <span className="text-sm font-semibold">Field Configuration</span>
        <div className="flex items-center gap-2">
          <Button
            variant="quiet"
            type="button"
            size="sm"
            onClick={onGenerate}
            disabled={generatingSelectors}
          >
            <Sparkles className="size-3" />
            {generatingSelectors ? 'Generating...' : 'Generate'}
          </Button>
          <Button variant="quiet" type="button" size="sm" onClick={onAddField}>
            <Plus className="size-3" />
            New Field
          </Button>
        </div>
      </header>
      <div className="space-y-4 px-6 pt-6 pb-6">
        {message ? <p className="type-body leading-relaxed text-success">{message}</p> : null}
        {error ? <InlineAlert message={error} /> : null}
        <div className="flex flex-col gap-2">
          {fieldRows.length ? (
            <>
              <FieldEditorHeader />
              {fieldRows.map((row) => (
                <ManualFieldEditor
                  key={row.id}
                  row={row}
                  showLabels={false}
                  message={fieldMessages[row.id]?.message}
                  messageTone={fieldMessages[row.id]?.tone}
                  onChange={(patch) => {
                    setFieldRows((current) =>
                      current.map((entry) =>
                        entry.id === row.id ? { ...entry, ...patch } : entry,
                      ),
                    );
                    clearFieldMessage(row.id);
                  }}
                  onDelete={() => {
                    setFieldRows((current) => current.filter((entry) => entry.id !== row.id));
                    clearFieldMessage(row.id);
                  }}
                  onTest={() => onTest(row)}
                  testing={activeFieldTestId === row.id}
                  testDisabled={
                    !targetUrl.trim() ||
                    (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim())
                  }
                />
              ))}
            </>
          ) : (
            <div className="surface-muted type-body rounded-md border-dashed px-4 py-6 leading-relaxed text-secondary">
              No selector rows yet.
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
