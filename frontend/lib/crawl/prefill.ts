import type { CrawlRecord } from '../api/types';
import { CRAWL_DEFAULTS } from '../constants/crawl-defaults';
import { STORAGE_KEYS } from '../constants/storage-keys';

export type PrefillRecord = Pick<CrawlRecord, 'id' | 'run_id' | 'source_url' | 'data'>;

export type ProductIntelligencePrefillPayload = {
  source_run_id: number | null;
  source_domain: string;
  records: PrefillRecord[];
};

export type DataEnrichmentPrefillPayload = {
  source_run_id: number | null;
  records: PrefillRecord[];
};

/**
 * Reader-side guard for sessionStorage prefill payloads: keeps only plain
 * records carrying the numeric id/run_id pair the job-create flows depend on
 * and drops malformed entries instead of failing the whole load.
 */
export function parsePrefillRecords(value: unknown): PrefillRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is PrefillRecord =>
      typeof item === 'object' &&
      item !== null &&
      !Array.isArray(item) &&
      typeof (item as Record<string, unknown>).id === 'number' &&
      typeof (item as Record<string, unknown>).run_id === 'number',
  );
}

/**
 * Shared reader for the sessionStorage prefill payloads: reads and removes the
 * key in one shot, and reports whether JSON parsing succeeded so each caller can
 * surface its own corrupt-payload copy (or stay silent). Shape normalization and
 * record filtering stay with the caller via `normalize`.
 */
export function loadStoredPrefill<T extends { source_run_id: number | null }>(
  storageKey: string,
  emptyPayload: () => T,
  normalize: (parsed: Partial<T>) => T,
): { payload: T; ok: boolean } {
  if (typeof window === 'undefined') return { payload: emptyPayload(), ok: true };
  const stored = window.sessionStorage.getItem(storageKey);
  if (!stored) return { payload: emptyPayload(), ok: true };
  try {
    return { payload: normalize(JSON.parse(stored) as Partial<T>), ok: true };
  } catch {
    return { payload: emptyPayload(), ok: false };
  } finally {
    window.sessionStorage.removeItem(storageKey);
  }
}

function isStorageQuotaError(error: unknown) {
  return (
    error instanceof DOMException &&
    (error.name === 'QuotaExceededError' || error.name === 'NS_ERROR_DOM_QUOTA_REACHED')
  );
}

export function storeProductIntelligencePrefill(
  payload: ProductIntelligencePrefillPayload,
  storage?: Storage,
) {
  const targetStorage =
    storage ?? (typeof window !== 'undefined' ? window.sessionStorage : undefined);
  if (!targetStorage) return;
  try {
    targetStorage.setItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL, JSON.stringify(payload));
  } catch (error) {
    console.error('Unable to store full Product Intelligence prefill.', error);
    const reducedPayload = {
      ...payload,
      records: payload.records.slice(0, CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4).map((record) => ({
        id: record.id,
        run_id: record.run_id,
        source_url: record.source_url,
        data: {},
      })),
    };
    try {
      targetStorage.setItem(
        STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL,
        JSON.stringify(reducedPayload),
      );
    } catch (fallbackError) {
      console.error('Unable to store reduced Product Intelligence prefill.', fallbackError);
      targetStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
    }
  }
}

export function storeDataEnrichmentPrefill(
  payload: DataEnrichmentPrefillPayload,
  storage?: Storage,
) {
  const targetStorage =
    storage ?? (typeof window !== 'undefined' ? window.sessionStorage : undefined);
  if (!targetStorage) return;
  const serializedPayload = JSON.stringify(payload);
  try {
    targetStorage.setItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL, serializedPayload);
  } catch (error) {
    console.error(
      'Unable to store Data Enrichment prefill for triggerDataEnrichmentFromResults.',
      error,
    );
    if (isStorageQuotaError(error)) {
      try {
        targetStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
        targetStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
        targetStorage.setItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL, serializedPayload);
        return;
      } catch (fallbackError) {
        console.error(
          'Unable to store Data Enrichment prefill after clearing older keys.',
          fallbackError,
        );
      }
    }
    targetStorage.removeItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  }
}
