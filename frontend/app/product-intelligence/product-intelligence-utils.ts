import type {
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceJobDetail,
  ProductIntelligenceOptions,
} from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import type { ProductIntelligencePrefillPayload } from '../../lib/crawl/prefill';
import { parsePrefillRecords } from '../../lib/crawl/prefill';

export const SEARCH_PROVIDER_OPTIONS: Array<{
  value: ProductIntelligenceOptions['search_provider'];
  label: string;
}> = [
  { value: 'serpapi', label: 'SerpAPI' },
  { value: 'google_native', label: 'Google Native' },
];

export function searchProviderLabel(provider: string) {
  const option = SEARCH_PROVIDER_OPTIONS.find((item) => item.value === provider);
  return option?.label ?? provider;
}

export type PrefillLoadResult = {
  error: string;
  payload: ProductIntelligencePrefillPayload;
};

export type ProductDiscoveryCandidate = ProductIntelligenceDiscoveryResponse['candidates'][number];

export type CandidateGroup = {
  sourceIndex: number;
  sourceTitle: string;
  sourceBrand: string;
  sourcePrice: unknown;
  sourceCurrency: string;
  sourceUrl: string;
  candidates: ProductDiscoveryCandidate[];
};

export const DEFAULT_OPTIONS: ProductIntelligenceOptions = {
  max_source_products: 10,
  max_candidates_per_product: 2,
  search_provider: 'serpapi',
  private_label_mode: 'exclude',
  confidence_threshold: 0.4,
  allowed_domains: [],
  excluded_domains: [],
  llm_enrichment_enabled: false,
};

export const MAX_SOURCE_PRODUCTS_LIMIT = 500;
export const MAX_CANDIDATES_PER_PRODUCT_LIMIT = 25;

export function loadPrefillPayload(): PrefillLoadResult {
  if (typeof globalThis.window === 'undefined') {
    return { error: '', payload: emptyPrefillPayload() };
  }
  const stored = globalThis.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  if (!stored) {
    return { error: '', payload: emptyPrefillPayload() };
  }
  try {
    const parsed = JSON.parse(stored) as Partial<ProductIntelligencePrefillPayload>;
    return {
      error: '',
      payload: {
        source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? '',
        records: parsePrefillRecords<ProductIntelligencePrefillPayload['records'][number]>(
          parsed.records,
        ),
      },
    };
  } catch {
    return {
      error: 'Unable to read Product Intelligence prefill.',
      payload: emptyPrefillPayload(),
    };
  } finally {
    globalThis.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  }
}

function emptyPrefillPayload(): ProductIntelligencePrefillPayload {
  return { source_run_id: null, source_domain: '', records: [] };
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
  const matchesByCandidateId = new Map(detail.matches.map((match) => [match.candidate_id, match]));
  const candidates = detail.candidates.map((candidate) =>
    discoveryCandidate(candidate, sourcesById, matchesByCandidateId),
  );
  return {
    job_id: detail.job.id,
    options: detail.job.options ?? {},
    source_count: detail.source_products.length,
    candidate_count: candidates.length,
    candidates,
  };
}

function discoveryCandidate(
  candidate: ProductIntelligenceJobDetail['candidates'][number],
  sourcesById: Map<
    number,
    { source: ProductIntelligenceJobDetail['source_products'][number]; index: number }
  >,
  matchesByCandidateId: Map<number, ProductIntelligenceJobDetail['matches'][number]>,
): ProductDiscoveryCandidate {
  const sourceEntry = sourcesById.get(candidate.source_product_id);
  const source = sourceEntry?.source;
  const payload = candidate.payload ?? {};
  const payloadIntelligence = isRecord(payload.intelligence) ? payload.intelligence : null;
  return {
    ...discoverySourceFields(source, sourceEntry?.index),
    url: candidate.url,
    domain: candidate.domain,
    source_type: candidate.source_type,
    query_used: candidate.query_used,
    search_rank: candidate.search_rank,
    payload,
    intelligence:
      payloadIntelligence ?? matchToIntelligence(matchesByCandidateId.get(candidate.id), candidate),
  };
}

function discoverySourceFields(
  source: ProductIntelligenceJobDetail['source_products'][number] | undefined,
  sourceIndex: number | undefined,
) {
  if (!source) {
    return {
      source_record_id: null,
      source_run_id: null,
      source_url: '',
      source_title: '',
      source_brand: '',
      source_price: null,
      source_currency: '',
      source_index: sourceIndex ?? 0,
    };
  }
  return {
    source_record_id: source.source_record_id,
    source_run_id: source.source_run_id,
    source_url: source.source_url,
    source_title: source.title,
    source_brand: source.brand,
    source_price: source.price,
    source_currency: source.currency,
    source_index: sourceIndex ?? 0,
  };
}

function matchToIntelligence(
  match: ProductIntelligenceJobDetail['matches'][number] | undefined,
  candidate: ProductIntelligenceJobDetail['candidates'][number],
) {
  if (!match) {
    return {};
  }
  return {
    canonical_record: {
      url: match.candidate_url || candidate.url,
      domain: match.candidate_domain || candidate.domain,
      price: match.candidate_price,
      currency: match.currency,
      availability: match.availability,
    },
    confidence_score: match.score,
    confidence_label: match.score_label,
    score_reasons: match.score_reasons ?? {},
    llm_enrichment: match.llm_enrichment ?? {},
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

function privateLabelMode(value: unknown): ProductIntelligenceOptions['private_label_mode'] {
  return value === 'include' || value === 'exclude' || value === 'flag'
    ? value
    : DEFAULT_OPTIONS.private_label_mode;
}

export function searchProvider(value: unknown): ProductIntelligenceOptions['search_provider'] {
  return value === 'google_native' || value === 'serpapi' ? value : DEFAULT_OPTIONS.search_provider;
}

export function parseDomainLines(value: string) {
  return value.split(/[\n,]+/).flatMap((line) => {
    const trimmed = line.trim().toLowerCase();
    return trimmed ? [trimmed] : [];
  });
}

export function candidateConfidence(candidate: ProductDiscoveryCandidate) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const parsed = Number(intelligence.confidence_score ?? 0);
  return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1) : 0;
}

export function stringField(value: unknown) {
  if (isRecord(value) || Array.isArray(value)) {
    return '';
  }
  const text = String(value ?? '').trim();
  return text === '--' || text === 'null' || text === 'undefined' ? '' : text;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function formatPrice(value: unknown, currency = '') {
  const numeric = typeof value === 'number' ? value : numericTextPrice(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  const prefix = currency || '$';
  return `${prefix}${numeric.toFixed(2)}`;
}

function numericTextPrice(value: unknown) {
  if (typeof value !== 'string') {
    return Number.NaN;
  }
  return Number(value.replace(/[^0-9.]+/g, ''));
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        const text = String(item || '')
          .trim()
          .toLowerCase();
        return text ? [text] : [];
      })
    : [];
}

export function clampInt(value: unknown, min: number, max: number, fallback: number) {
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
