import type { CrawlRecord } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';

export type ProductIntelligencePrefillPayload = {
  source_run_id: number | null;
  source_domain: string;
  records: Array<Pick<CrawlRecord, 'id' | 'run_id' | 'source_url' | 'data'>>;
};

export type DataEnrichmentPrefillPayload = {
  source_run_id: number | null;
  records: Array<Pick<CrawlRecord, 'id' | 'run_id' | 'source_url' | 'data'>>;
};

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
