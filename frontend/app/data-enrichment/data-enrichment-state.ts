import { useReducer } from 'react';

import type { DataEnrichmentSourceRecordInput } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';

export type PrefillPayload = {
  source_run_id?: number | null;
  records?: DataEnrichmentSourceRecordInput[];
};

export type DataEnrichmentState = {
  llmEnabled: boolean;
  activeJobId: number | null;
  error: string;
  historyOpen: boolean;
  selectedProductId: number | null;
};

export type DataEnrichmentAction =
  | { type: 'llmChanged'; enabled: boolean }
  | { type: 'jobCreated'; jobId: number }
  | { type: 'failed'; message: string }
  | { type: 'historyChanged'; open: boolean }
  | { type: 'productSelected'; productId: number | null }
  | { type: 'historyJobSelected'; jobId: number }
  | { type: 'initialJobResolved'; jobId: number };

export const INITIAL_DATA_ENRICHMENT_STATE: DataEnrichmentState = {
  llmEnabled: false,
  activeJobId: null,
  error: '',
  historyOpen: false,
  selectedProductId: null,
};

export function dataEnrichmentReducer(
  state: DataEnrichmentState,
  action: DataEnrichmentAction,
): DataEnrichmentState {
  switch (action.type) {
    case 'llmChanged':
      return { ...state, llmEnabled: action.enabled };
    case 'jobCreated':
      return { ...state, error: '', activeJobId: action.jobId, selectedProductId: null };
    case 'failed':
      return { ...state, error: action.message };
    case 'historyChanged':
      return { ...state, historyOpen: action.open };
    case 'productSelected':
      return { ...state, selectedProductId: action.productId };
    case 'historyJobSelected':
      return { ...state, activeJobId: action.jobId, selectedProductId: null };
    case 'initialJobResolved':
      return state.activeJobId === null
        ? { ...state, activeJobId: action.jobId, selectedProductId: null }
        : state;
  }
}

export function loadPrefill(): PrefillPayload {
  if (typeof window === 'undefined') return {};
  const stored = window.sessionStorage.getItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  if (!stored) return {};
  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
      records: Array.isArray(parsed.records) ? parsed.records : [],
    };
  } catch {
    return {};
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  }
}

export function useDataEnrichmentState() {
  const [state, dispatch] = useReducer(dataEnrichmentReducer, INITIAL_DATA_ENRICHMENT_STATE);
  return { state, dispatch };
}
