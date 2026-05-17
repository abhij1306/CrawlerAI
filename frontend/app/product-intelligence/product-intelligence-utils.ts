'use client';

import type {
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceJobDetail,
  ProductIntelligenceOptions,
  ProductIntelligenceSourceRecordInput,
} from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';

export type PrefillPayload = {
  source_run_id?: number | null;
  source_domain?: string;
  records?: ProductIntelligenceSourceRecordInput[];
};

export type PrefillLoadResult = {
  error: string;
  payload: PrefillPayload;
};

export type ProductIntelligenceCandidate =
  ProductIntelligenceDiscoveryResponse['candidates'][number];

export type CandidateGroup = {
  sourceIndex: number;
  sourceTitle: string;
  sourceBrand: string;
  sourcePrice: unknown;
  sourceCurrency: string;
  sourceUrl: string;
  candidates: ProductIntelligenceCandidate[];
};

export const DEFAULT_OPTIONS: ProductIntelligenceOptions = {
  max_source_products: 10,
  max_candidates_per_product: 2,
  search_provider: 'google_native',
  private_label_mode: 'flag',
  confidence_threshold: 0.4,
  allowed_domains: [],
  excluded_domains: [],
  llm_enrichment_enabled: false,
};

export const MAX_SOURCE_PRODUCTS_LIMIT = 500;
export const MAX_CANDIDATES_PER_PRODUCT_LIMIT = 25;

export function loadPrefillPayload(): PrefillLoadResult {
  if (typeof window === 'undefined') {
    return { error: '', payload: {} };
  }
  const stored = window.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  if (!stored) {
    return { error: '', payload: {} };
  }
  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      error: '',
      payload: {
        source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? '',
        records: Array.isArray(parsed.records) ? parsed.records : [],
      },
    };
  } catch {
    return { error: 'Unable to read Product Intelligence prefill.', payload: {} };
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  }
}

export function detailToDiscovery(
  detail: ProductIntelligenceJobDetail,
): ProductIntelligenceDiscoveryResponse {
  const sourcesById = new Map<
    number,
    { source: ProductIntelligenceJobDetail['source_products'][number]; index: number }
  >();
  detail.source_products.forEach((source, index) => {
    if (sourcesById.has(source.id)) {
      console.warn('Duplicate Product Intelligence source id; keeping first.', {
        job_id: detail.job.id,
        source_id: source.id,
        duplicate_index: index,
        first_index: sourcesById.get(source.id)?.index,
      });
      return;
    }
    sourcesById.set(source.id, { source, index });
  });
  const candidates = detail.candidates.map((candidate) => {
    const sourceEntry = sourcesById.get(candidate.source_product_id);
    const source = sourceEntry?.source;
    return {
      source_record_id: source?.source_record_id ?? null,
      source_run_id: source?.source_run_id ?? null,
      source_url: source?.source_url ?? '',
      source_title: source?.title ?? '',
      source_brand: source?.brand ?? '',
      source_price: source?.price ?? null,
      source_currency: source?.currency ?? '',
      source_index: sourceEntry?.index ?? 0,
      url: candidate.url,
      domain: candidate.domain,
      source_type: candidate.source_type,
      query_used: candidate.query_used,
      search_rank: candidate.search_rank,
      payload: candidate.payload ?? {},
      intelligence: isRecord(candidate.payload?.intelligence) ? candidate.payload.intelligence : {},
    };
  });
  return {
    job_id: detail.job.id,
    options: detail.job.options ?? {},
    source_count: detail.source_products.length,
    candidate_count: candidates.length,
    candidates,
  };
}

export function detailOptions(
  value: Record<string, unknown> | null | undefined,
): ProductIntelligenceOptions {
  const raw = isRecord(value) ? value : {};
  return {
    ...DEFAULT_OPTIONS,
    max_source_products: clampInt(
      raw.max_source_products,
      1,
      MAX_SOURCE_PRODUCTS_LIMIT,
      DEFAULT_OPTIONS.max_source_products,
    ),
    max_candidates_per_product: clampInt(
      raw.max_candidates_per_product,
      1,
      MAX_CANDIDATES_PER_PRODUCT_LIMIT,
      DEFAULT_OPTIONS.max_candidates_per_product,
    ),
    search_provider: searchProvider(raw.search_provider),
    private_label_mode: privateLabelMode(raw.private_label_mode),
    confidence_threshold: clampFloat(
      raw.confidence_threshold,
      0,
      1,
      DEFAULT_OPTIONS.confidence_threshold,
    ),
    allowed_domains: stringArray(raw.allowed_domains),
    excluded_domains: stringArray(raw.excluded_domains),
    llm_enrichment_enabled: Boolean(raw.llm_enrichment_enabled),
  };
}

export function privateLabelMode(value: unknown): ProductIntelligenceOptions['private_label_mode'] {
  return value === 'include' || value === 'exclude' || value === 'flag'
    ? value
    : DEFAULT_OPTIONS.private_label_mode;
}

export function searchProvider(value: unknown): ProductIntelligenceOptions['search_provider'] {
  return value === 'google_native' || value === 'serpapi' ? value : DEFAULT_OPTIONS.search_provider;
}

export function parseDomainLines(value: string) {
  return value
    .split(/[\n,]+/)
    .map((line) => line.trim().toLowerCase())
    .filter(Boolean);
}

export function candidateConfidence(candidate: ProductIntelligenceCandidate) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const parsed = Number(intelligence.confidence_score ?? 0);
  return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1) : 0;
}

export function stringField(value: unknown) {
  const text = String(value ?? '').trim();
  return text === '--' || text === 'null' || text === 'undefined' ? '' : text;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function displayValue(data: Record<string, unknown>, fields: string[]) {
  for (const field of fields) {
    const value = data[field];
    if (value !== undefined && value !== null && value !== '') {
      return String(value);
    }
  }
  return '';
}

export function formatPrice(value: unknown, currency = '') {
  const numeric =
    typeof value === 'number' ? value : Number(String(value ?? '').replace(/[^0-9.]+/g, ''));
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  const prefix = currency || '$';
  return `${prefix}${numeric.toFixed(2)}`;
}

export function formatExtractedPrice(price: unknown, currency: unknown) {
  if (isEmptyValue(price)) {
    return '--';
  }
  const currencyText = String(currency ?? '').trim();
  if (typeof price === 'number' && currencyText) {
    return formatPrice(price, currencyText);
  }
  return String(price);
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value
        .map((item) =>
          String(item || '')
            .trim()
            .toLowerCase(),
        )
        .filter(Boolean)
    : [];
}

function isEmptyValue(value: unknown) {
  return value === undefined || value === null || String(value).trim() === '';
}

function clampInt(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}

function clampFloat(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseFloat(String(value));
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}
