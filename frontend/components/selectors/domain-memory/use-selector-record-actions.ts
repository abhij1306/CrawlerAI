import type { Dispatch, SetStateAction } from 'react';

import { api } from '../../../lib/api';
import type { SelectorDomainSummary, SelectorUpdatePayload } from '../../../lib/api/types';
import type { EditDraft, LocalRecord } from './types';

type SelectorRecordActionsInput = {
  cancelEdit: () => void;
  draft: EditDraft | null;
  editingId: string | null;
  setDraft: Dispatch<SetStateAction<EditDraft | null>>;
  setEditingId: Dispatch<SetStateAction<string | null>>;
  setError: Dispatch<SetStateAction<string>>;
  setRecords: Dispatch<SetStateAction<LocalRecord[]>>;
  setSelectorSummaries: Dispatch<SetStateAction<SelectorDomainSummary[]>>;
};

export function useSelectorRecordActions({
  cancelEdit,
  draft,
  editingId,
  setDraft,
  setEditingId,
  setError,
  setRecords,
  setSelectorSummaries,
}: SelectorRecordActionsInput) {
  function startEdit(record: LocalRecord) {
    const selectorFields = [
      ['xpath', record.xpath],
      ['css_selector', record.css_selector],
      ['regex', record.regex],
    ] as const;
    const activeSelector = selectorFields.find(([, value]) => String(value || '').trim());
    if (!activeSelector) {
      setError(`Selector ${record.id} has no editable selector value.`);
      return;
    }
    const [kind, value] = activeSelector;
    setEditingId(record._uid);
    setDraft({
      field_name: record.field_name,
      kind,
      selectorValue: String(value || '').trim(),
      source: record.source,
      is_active: record.is_active,
    });
  }

  async function saveEdit(record: LocalRecord) {
    if (!draft) return;
    const payload: SelectorUpdatePayload = {
      field_name: draft.field_name,
      xpath: draft.kind === 'xpath' ? draft.selectorValue : null,
      css_selector: draft.kind === 'css_selector' ? draft.selectorValue : null,
      regex: draft.kind === 'regex' ? draft.selectorValue : null,
      source: draft.source,
      is_active: draft.is_active,
    };
    try {
      const updated = await api.updateSelector(record.id, payload);
      setRecords((current) =>
        current.map((entry) =>
          entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry,
        ),
      );
      cancelEdit();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to save selector.');
    }
  }

  async function toggleActive(record: LocalRecord) {
    try {
      const updated = await api.updateSelector(record.id, { is_active: !record.is_active });
      setRecords((current) =>
        current.map((entry) =>
          entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry,
        ),
      );
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to update selector state.');
    }
  }

  async function deleteRecord(record: LocalRecord) {
    try {
      await api.deleteSelector(record.id);
      setRecords((current) => current.filter((entry) => entry._uid !== record._uid));
      setSelectorSummaries((current) =>
        current.map((entry) =>
          entry.domain === record.domain && entry.surface === record.surface
            ? { ...entry, selector_count: Math.max(0, entry.selector_count - 1) }
            : entry,
        ),
      );
      if (editingId === record._uid) cancelEdit();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to delete selector.');
    }
  }

  async function deleteDomainSelectors(domain: string) {
    try {
      await api.deleteSelectorsByDomain(domain);
      let removedEditingRecord = false;
      setRecords((current) => {
        const editingRecord =
          editingId === null ? null : current.find((record) => record._uid === editingId);
        removedEditingRecord = editingRecord?.domain === domain;
        return current.filter((entry) => entry.domain !== domain);
      });
      if (removedEditingRecord) cancelEdit();
      setSelectorSummaries((current) => current.filter((entry) => entry.domain !== domain));
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : 'Unable to clear domain selectors.',
      );
    }
  }

  return { deleteDomainSelectors, deleteRecord, saveEdit, startEdit, toggleActive };
}
