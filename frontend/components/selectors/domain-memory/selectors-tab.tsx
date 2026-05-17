import { Pencil, Save, Trash2, X } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';

import {
  DataRegionEmpty,
  DataRegionLoading,
  DetailRow,
  MutedPanelMessage,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge, Button, Input, Toggle } from '../../ui/primitives';
import type { DomainWorkspace, EditDraft, LocalRecord } from './types';
import { selectorValue, surfaceLabel, titleCaseToken } from './utils';

type SelectorsTabProps = {
  cancelEdit: () => void;
  deleteRecord: (record: LocalRecord) => Promise<void>;
  draft: EditDraft | null;
  editingId: string | null;
  loadedSelectorDomain: string;
  saveEdit: (record: LocalRecord) => Promise<void>;
  selectedWorkspace: DomainWorkspace;
  selectorLoading: boolean;
  setDraft: Dispatch<SetStateAction<EditDraft | null>>;
  startEdit: (record: LocalRecord) => void;
  toggleActive: (record: LocalRecord) => Promise<void>;
};

export function SelectorsTab({
  cancelEdit,
  deleteRecord,
  draft,
  editingId,
  loadedSelectorDomain,
  saveEdit,
  selectedWorkspace,
  selectorLoading,
  setDraft,
  startEdit,
  toggleActive,
}: SelectorsTabProps) {
  return (
    <SurfaceSection
      title="Selector Memory"
      description="Review and edit the selectors currently saved for this domain."
      bodyClassName="space-y-4"
    >
      {selectorLoading && loadedSelectorDomain !== selectedWorkspace.domain ? (
        <DataRegionLoading count={6} className="px-0" />
      ) : selectedWorkspace.surfaces.some((surface) => surface.selectorCount) ? (
        selectedWorkspace.surfaces.map((surfaceWorkspace) => (
          <div
            key={`${selectedWorkspace.domain}:${surfaceWorkspace.surface}`}
            className="border-subtle-panel-border bg-subtle-panel space-y-3 rounded-[var(--radius-xl)] border p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-foreground text-sm font-medium">
                  {surfaceLabel(surfaceWorkspace.surface)}
                </div>
                <div className="text-muted text-xs">
                  {surfaceWorkspace.selectorCount} selector
                  {surfaceWorkspace.selectorCount === 1 ? '' : 's'}
                </div>
              </div>
              {surfaceWorkspace.profile ? <Badge tone="info">profile saved</Badge> : null}
            </div>
            {surfaceWorkspace.selectors.length ? (
              <div className="space-y-3">
                {surfaceWorkspace.selectors.map((record) => (
                  <SelectorRow
                    key={record._uid}
                    cancelEdit={cancelEdit}
                    deleteRecord={deleteRecord}
                    draft={draft}
                    editingId={editingId}
                    record={record}
                    saveEdit={saveEdit}
                    setDraft={setDraft}
                    startEdit={startEdit}
                    toggleActive={toggleActive}
                  />
                ))}
              </div>
            ) : (
              <MutedPanelMessage
                title="No selectors"
                description="No selectors saved for this surface yet."
              />
            )}
          </div>
        ))
      ) : (
        <DataRegionEmpty
          title="No saved selector memory"
          description="Selectors promoted from completed runs will appear here once they are saved."
        />
      )}
    </SurfaceSection>
  );
}

type SelectorRowProps = Omit<
  SelectorsTabProps,
  'loadedSelectorDomain' | 'selectedWorkspace' | 'selectorLoading'
> & {
  record: LocalRecord;
};

function SelectorRow({
  cancelEdit,
  deleteRecord,
  draft,
  editingId,
  record,
  saveEdit,
  setDraft,
  startEdit,
  toggleActive,
}: SelectorRowProps) {
  const isEditing = editingId === record._uid && draft !== null;
  return (
    <DetailRow className={isEditing ? 'bg-subtle-panel' : undefined}>
      {isEditing ? (
        <SelectorEditForm
          cancelEdit={cancelEdit}
          draft={draft}
          record={record}
          saveEdit={saveEdit}
          setDraft={setDraft}
        />
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-foreground font-medium">{record.field_name}</span>
              <Toggle
                checked={record.is_active}
                onChange={() => void toggleActive(record)}
                ariaLabel={record.is_active ? 'Disable selector' : 'Enable selector'}
              />
              <span className="text-muted text-xs">{titleCaseToken(record.source)}</span>
            </div>
            <code className="text-secondary mt-2 block text-xs break-all">
              {selectorValue(record)}
            </code>
            {record.sample_value ? (
              <div className="text-muted mt-2 text-xs">Sample: {record.sample_value}</div>
            ) : null}
          </div>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => startEdit(record)}
              aria-label="Edit selector"
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="danger"
              size="icon"
              onClick={() => void deleteRecord(record)}
              aria-label="Delete selector"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </DetailRow>
  );
}

type SelectorEditFormProps = {
  cancelEdit: () => void;
  draft: EditDraft;
  record: LocalRecord;
  saveEdit: (record: LocalRecord) => Promise<void>;
  setDraft: Dispatch<SetStateAction<EditDraft | null>>;
};

function SelectorEditForm({
  cancelEdit,
  draft,
  record,
  saveEdit,
  setDraft,
}: SelectorEditFormProps) {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1.5">
          <span className="field-label">Field</span>
          <Input
            value={draft.field_name}
            onChange={(event) =>
              setDraft((current) =>
                current ? { ...current, field_name: event.target.value } : current,
              )
            }
          />
        </label>
        <label className="grid gap-1.5">
          <span className="field-label">Source</span>
          <Input
            value={draft.source}
            onChange={(event) =>
              setDraft((current) =>
                current ? { ...current, source: event.target.value } : current,
              )
            }
          />
        </label>
      </div>
      <label className="grid gap-1.5">
        <span className="field-label">Selector Kind</span>
        <select
          value={draft.kind}
          onChange={(event) =>
            setDraft((current) =>
              current ? { ...current, kind: event.target.value as EditDraft['kind'] } : current,
            )
          }
          className="border-divider bg-background rounded-[var(--radius-md)] border px-3 py-2 text-sm"
        >
          <option value="css_selector">CSS Selector</option>
          <option value="xpath">XPath</option>
          <option value="regex">Regex</option>
        </select>
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Selector</span>
        <Input
          value={draft.selectorValue}
          onChange={(event) =>
            setDraft((current) =>
              current ? { ...current, selectorValue: event.target.value } : current,
            )
          }
        />
      </label>
      <label className="text-secondary flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.is_active}
          onChange={(event) =>
            setDraft((current) =>
              current ? { ...current, is_active: event.target.checked } : current,
            )
          }
        />
        Active selector
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="accent" onClick={() => void saveEdit(record)}>
          <Save className="size-3.5" />
          Save
        </Button>
        <Button type="button" variant="ghost" onClick={cancelEdit}>
          <X className="size-3.5" />
          Cancel
        </Button>
      </div>
    </div>
  );
}
