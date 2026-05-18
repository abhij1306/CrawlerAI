import type { CrawlConfig, DomainRunProfile } from '../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../lib/constants/crawl-defaults';
import {
  clampNumber,
  type CategoryMode,
  type CrawlTab,
  deriveSurface,
  type FieldRow,
  type PendingDispatch,
  parseLines,
  type PdpMode,
  normalizeField,
  uniqueFields,
  uniqueRequestedFields,
  validateAdditionalFieldName,
} from './shared';
import { DEFAULT_FIELDS } from './domain-surface-config';

export type StudioMode = 'quick' | 'advanced';
export type FetchMode = DomainRunProfile['fetch_profile']['fetch_mode'];
export type ExtractionSource = DomainRunProfile['fetch_profile']['extraction_source'];
export type JsMode = DomainRunProfile['fetch_profile']['js_mode'];
export type TraversalMode = NonNullable<DomainRunProfile['fetch_profile']['traversal_mode']>;
export type TraversalDropdownValue = TraversalMode | 'off';
export type CaptureNetworkMode = DomainRunProfile['diagnostics_profile']['capture_network'];
export type BrowserEngine = DomainRunProfile['acquisition_contract']['preferred_browser_engine'];
export type DiagnosticsPreset = 'lean' | 'standard' | 'deep_debug';

export const FETCH_MODE_OPTIONS = new Set<FetchMode>([
  'auto',
  'http_only',
  'browser_only',
  'http_then_browser',
]);
export const EXTRACTION_SOURCE_OPTIONS = new Set<ExtractionSource>([
  'raw_html',
  'rendered_dom',
  'rendered_dom_visual',
  'network_payload_first',
]);
export const JS_MODE_OPTIONS = new Set<JsMode>(['auto', 'enabled', 'disabled']);
export const TRAVERSAL_MODE_OPTIONS = new Set<TraversalMode>([
  'scroll',
  'load_more',
  'view_all',
  'paginate',
]);
export const CAPTURE_NETWORK_OPTIONS = new Set<CaptureNetworkMode>([
  'off',
  'matched_only',
  'all_small_json',
]);
export const BROWSER_ENGINE_OPTIONS = new Set<BrowserEngine>([
  'auto',
  'patchright',
  'real_chrome',
]);

const DIAGNOSTICS_PRESETS: Record<DiagnosticsPreset, DomainRunProfile['diagnostics_profile']> = {
  lean: {
    capture_html: true,
    capture_screenshot: false,
    capture_network: 'off',
    capture_response_headers: true,
    capture_browser_diagnostics: true,
  },
  standard: {
    capture_html: true,
    capture_screenshot: false,
    capture_network: 'matched_only',
    capture_response_headers: true,
    capture_browser_diagnostics: true,
  },
  deep_debug: {
    capture_html: true,
    capture_screenshot: true,
    capture_network: 'all_small_json',
    capture_response_headers: true,
    capture_browser_diagnostics: true,
  },
};

export function defaultRunProfile(): DomainRunProfile {
  return {
    version: 1,
    fetch_profile: {
      fetch_mode: 'auto',
      extraction_source: 'raw_html',
      js_mode: 'auto',
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: CRAWL_DEFAULTS.REQUEST_DELAY_MS,
      host_memory_ttl_seconds: null,
    },
    locality_profile: {
      geo_country: 'auto',
      language_hint: null,
      currency_hint: null,
    },
    diagnostics_profile: { ...DIAGNOSTICS_PRESETS.standard },
    acquisition_contract: {
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      prefer_curl_handoff: false,
      handoff_cookie_engine: 'auto',
      last_quality_success: null,
      stale_after_failures: {
        failure_count: 0,
        stale: false,
      },
    },
    source_run_id: null,
    saved_at: null,
  };
}

export function cloneRunProfile(profile: DomainRunProfile | null | undefined): DomainRunProfile {
  const base = defaultRunProfile();
  if (!profile) {
    return base;
  }
  return {
    version: 1,
    fetch_profile: {
      ...base.fetch_profile,
      ...(profile.fetch_profile ?? {}),
    },
    locality_profile: {
      ...base.locality_profile,
      ...(profile.locality_profile ?? {}),
    },
    diagnostics_profile: {
      ...base.diagnostics_profile,
      ...(profile.diagnostics_profile ?? {}),
    },
    acquisition_contract: {
      ...base.acquisition_contract,
      ...(profile.acquisition_contract ?? {}),
      stale_after_failures: {
        ...base.acquisition_contract.stale_after_failures,
        ...(profile.acquisition_contract?.stale_after_failures ?? {}),
      },
    },
    source_run_id: profile.source_run_id ?? null,
    saved_at: profile.saved_at ?? null,
  };
}

export function diagnosticsPresetForProfile(profile: DomainRunProfile): DiagnosticsPreset {
  const current = profile.diagnostics_profile;
  for (const preset of ['lean', 'standard', 'deep_debug'] as const) {
    const candidate = DIAGNOSTICS_PRESETS[preset];
    if (
      current.capture_html === candidate.capture_html &&
      current.capture_screenshot === candidate.capture_screenshot &&
      current.capture_network === candidate.capture_network &&
      current.capture_response_headers === candidate.capture_response_headers &&
      current.capture_browser_diagnostics === candidate.capture_browser_diagnostics
    ) {
      return preset;
    }
  }
  return 'standard';
}

export function applyDiagnosticsPreset(
  profile: DomainRunProfile,
  preset: DiagnosticsPreset,
): DomainRunProfile {
  return {
    ...profile,
    diagnostics_profile: { ...DIAGNOSTICS_PRESETS[preset] },
  };
}

export function parseOptionalClampedNumber(value: string, min: number, max: number) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return clampNumber(trimmed, min, max, min);
}

export function isSingleUrlMode(crawlTab: CrawlTab, mode: CategoryMode | PdpMode) {
  return (
    (crawlTab === 'category' && mode === 'single') || (crawlTab === 'pdp' && mode === 'single')
  );
}

export function normalizeHttpLookupDomain(rawUrl: string) {
  const candidate = rawUrl.trim();
  if (!candidate) {
    return '';
  }
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return '';
    }
    return parsed.hostname.replace(/^www\./, '').toLowerCase();
  } catch {
    return '';
  }
}

export function surfaceLabel(surface: string) {
  if (surface === 'content_listing') {
    return 'Content Rows';
  }
  if (surface === 'content_detail') {
    return 'Page Content';
  }
  if (surface === 'ecommerce_listing') {
    return 'Commerce Listing';
  }
  if (surface === 'ecommerce_detail') {
    return 'Commerce Detail';
  }
  if (surface === 'job_listing') {
    return 'Job Listing';
  }
  if (surface === 'job_detail') {
    return 'Job Detail';
  }
  if (surface === 'automobile_listing') {
    return 'Automobile Listing';
  }
  if (surface === 'automobile_detail') {
    return 'Automobile Detail';
  }
  if (surface === 'article_listing') {
    return 'Article Feed';
  }
  if (surface === 'article_detail') {
    return 'Article Page';
  }
  if (surface === 'forum_detail') {
    return 'Forum Thread';
  }
  return surface;
}

export function stripDomainMemoryFieldRows(rows: FieldRow[]) {
  return rows.filter((row) => !row.id.startsWith('domain-memory-'));
}

export function inferRunTypeHint(config: CrawlConfig) {
  if (config.module === 'category') {
    return config.mode === 'bulk' ? 'batch' : 'crawl';
  }
  if (config.mode === 'csv') {
    return 'csv';
  }
  if (config.mode === 'batch') {
    return 'batch';
  }
  return 'crawl';
}

function buildExtractionContract(fieldRows: FieldRow[]) {
  const extractionContract = fieldRows
    .map((row) => {
      const fieldName = normalizeField(row.fieldName);
      const cssSelector = row.cssSelector.trim();
      const xpath = row.xpath.trim();
      const regex = row.regex.trim();
      if (!fieldName || (!cssSelector && !xpath && !regex)) {
        return null;
      }
      const reason = validateAdditionalFieldName(fieldName);
      if (reason) {
        throw new Error(`Invalid manual field "${row.fieldName || fieldName}": ${reason}`);
      }
      return {
        field_name: fieldName,
        css_selector: cssSelector || undefined,
        xpath: xpath || undefined,
        regex: regex || undefined,
      };
    })
    .filter((row): row is NonNullable<typeof row> => Boolean(row));
  return extractionContract;
}

export function buildDispatch(
  config: CrawlConfig,
  fieldRows: FieldRow[] = [],
  options?: {
    runProfile?: DomainRunProfile;
    studioMode?: StudioMode;
  },
): PendingDispatch {
  const additionalFields = uniqueRequestedFields(config.additional_fields);
  for (const field of additionalFields) {
    const reason = validateAdditionalFieldName(field);
    if (reason) {
      throw new Error(`Invalid additional field "${field}": ${reason}`);
    }
  }
  const surface = deriveSurface(config.domain, config.module);
  const runProfile = cloneRunProfile(options?.runProfile);
  const studioMode = options?.studioMode ?? 'quick';
  const traversalMode = studioMode === 'advanced' ? runProfile.fetch_profile.traversal_mode : null;
  const commonSettings = {
    llm_enabled: config.smart_extraction,
    advanced_enabled: studioMode === 'advanced',
    advanced_mode: traversalMode,
    max_records: config.max_records,
    respect_robots_txt: config.respect_robots_txt,
    proxy_enabled: config.proxy_enabled,
    proxy_list: config.proxy_enabled ? config.proxy_lines : [],
    proxy_profile: {
      enabled: config.proxy_enabled,
      proxy_list: config.proxy_enabled ? config.proxy_lines : [],
    },
    additional_fields: additionalFields,
    crawl_module: config.module,
    crawl_mode: config.mode,
    fetch_profile: {
      ...runProfile.fetch_profile,
      traversal_mode: traversalMode,
      request_delay_ms: clampNumber(
        runProfile.fetch_profile.request_delay_ms,
        CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
        CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
        CRAWL_DEFAULTS.REQUEST_DELAY_MS,
      ),
      host_memory_ttl_seconds:
        runProfile.fetch_profile.host_memory_ttl_seconds == null
          ? null
          : clampNumber(
              runProfile.fetch_profile.host_memory_ttl_seconds,
              CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS,
              CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS,
              CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS,
            ),
    },
    locality_profile: { ...runProfile.locality_profile },
    diagnostics_profile: { ...runProfile.diagnostics_profile },
    acquisition_contract: { ...runProfile.acquisition_contract },
    extraction_contract: buildExtractionContract(fieldRows),
  };

  if (config.module === 'category') {
    if (config.mode === 'bulk') {
      const urls = parseLines(config.bulk_urls);
      if (!urls.length) throw new Error('Bulk crawl needs at least one URL.');
      return {
        runType: 'batch',
        surface,
        url: urls[0],
        urls,
        settings: { ...commonSettings, urls },
        additionalFields,
        csvFile: null,
      };
    }
    if (!config.target_url.trim()) throw new Error('Enter a target URL.');
    return {
      runType: 'crawl',
      surface,
      url: config.target_url.trim(),
      settings: commonSettings,
      additionalFields,
      csvFile: null,
    };
  }

  if (config.mode === 'csv') {
    if (!config.csv_file) throw new Error('Select a CSV file.');
    return {
      runType: 'csv',
      surface,
      url: config.target_url.trim() || undefined,
      settings: commonSettings,
      additionalFields,
      csvFile: config.csv_file,
    };
  }

  if (config.mode === 'batch') {
    const urls = parseLines(config.bulk_urls);
    if (!urls.length) throw new Error('Batch crawl needs at least one URL.');
    return {
      runType: 'batch',
      surface,
      url: urls[0],
      urls,
      settings: { ...commonSettings, urls },
      additionalFields,
      csvFile: null,
    };
  }

  if (!config.target_url.trim()) throw new Error('Enter a target URL.');
  return {
    runType: 'crawl',
    surface,
    url: config.target_url.trim(),
    settings: commonSettings,
    additionalFields,
    csvFile: null,
  };
}

export function canPreview(
  config: CrawlConfig,
  fieldRows: FieldRow[],
  options?: {
    runProfile?: DomainRunProfile;
    studioMode?: StudioMode;
  },
) {
  try {
    buildDispatch(config, fieldRows, options);
    return true;
  } catch {
    return false;
  }
}

export function selectorGenerationFields(
  surface: string,
  fieldRows: FieldRow[],
  additionalFields: string[],
) {
  return uniqueFields([
    ...defaultFieldsForSurface(surface),
    ...additionalFields,
    ...fieldRows.map((row) => row.fieldName),
  ]);
}

function defaultFieldsForSurface(surface: string) {
  return DEFAULT_FIELDS[surface as keyof typeof DEFAULT_FIELDS] ?? ['title', 'url'];
}

export function selectRelevantSelectorRecords(
  records: Array<{
    id: number;
    field_name: string;
    surface: string;
    is_active: boolean;
    css_selector?: string | null;
    xpath?: string | null;
    regex?: string | null;
  }>,
  surface: string,
) {
  return records
    .filter(
      (record) => record.is_active && (record.surface === surface || record.surface === 'generic'),
    )
    .sort((left, right) => {
      const leftPriority = left.surface === surface ? 0 : 1;
      const rightPriority = right.surface === surface ? 0 : 1;
      if (leftPriority !== rightPriority) {
        return leftPriority - rightPriority;
      }
      return left.field_name.localeCompare(right.field_name);
    });
}

export function buildFieldRowFromSelectorRecord(record: {
  id: number;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
}) {
  return {
    id: `domain-memory-${record.id}`,
    fieldName: record.field_name,
    cssSelector: record.css_selector ?? '',
    xpath: record.xpath ?? '',
    regex: record.regex ?? '',
    cssState: record.css_selector ? 'valid' : 'idle',
    xpathState: record.xpath ? 'valid' : 'idle',
    regexState: record.regex ? 'valid' : 'idle',
  } satisfies FieldRow;
}

export function buildFieldRowFromSuggestion(
  fieldName: string,
  suggestion?: {
    css_selector?: string | null;
    xpath?: string | null;
    regex?: string | null;
  },
) {
  return {
    id: `generated-${fieldName}`,
    fieldName,
    cssSelector: suggestion?.css_selector ?? '',
    xpath: suggestion?.xpath ?? '',
    regex: suggestion?.regex ?? '',
    cssState: suggestion?.css_selector ? 'valid' : 'idle',
    xpathState: suggestion?.xpath ? 'valid' : 'idle',
    regexState: suggestion?.regex ? 'valid' : 'idle',
  } satisfies FieldRow;
}

export function mergeFieldRows(currentRows: FieldRow[], incomingRows: FieldRow[]) {
  const merged = new Map<string, FieldRow>();
  for (const row of currentRows) {
    merged.set(normalizeField(row.fieldName || row.id), row);
  }
  for (const row of incomingRows) {
    const key = normalizeField(row.fieldName || row.id);
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, row);
      continue;
    }
    merged.set(key, {
      ...existing,
      fieldName: existing.fieldName || row.fieldName,
      cssSelector: existing.cssSelector || row.cssSelector,
      xpath: existing.xpath || row.xpath,
      regex: existing.regex || row.regex,
      cssState: existing.cssSelector ? existing.cssState : row.cssState,
      xpathState: existing.xpath ? existing.xpathState : row.xpathState,
      regexState: existing.regex ? existing.regexState : row.regexState,
    });
  }
  return Array.from(merged.values());
}
