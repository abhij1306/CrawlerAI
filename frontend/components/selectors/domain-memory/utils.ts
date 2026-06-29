import type {
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
  KnowledgeContract,
  SelectorRecord,
} from '../../../lib/api/types';
import { isSpecialUseDomain } from '../../../lib/format/domain';
import type { SurfaceWorkspace } from './types';

export function surfaceLabel(surface: string) {
  if (surface === 'ecommerce_listing') return 'Commerce Listing';
  if (surface === 'ecommerce_detail') return 'Commerce Detail';
  if (surface === 'job_listing') return 'Job Listing';
  if (surface === 'job_detail') return 'Job Detail';
  return surface.replace(/_/g, ' ');
}

export function titleCaseToken(value: string | null | undefined) {
  return String(value || '')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(' ');
}

export type KnowledgeSourceOption = {
  value: string;
  label: string;
  kind: string;
  locator: string;
};

export function knowledgeSourceOptions(contract: KnowledgeContract): KnowledgeSourceOption[] {
  const candidates = contract.candidates.map((candidate) => ({
    source: String(candidate.source ?? '').trim(),
    value: candidate.value_preview ?? candidate.value,
  }));
  const selectedCandidate = candidates.find(
    (candidate) =>
      normalizeKnowledgeSourcePattern(candidate.source) ===
      normalizeKnowledgeSourcePattern(contract.selected_source),
  );
  const selectedValue =
    selectedCandidate?.value ?? contract.latest_values.find((row) => row.value != null)?.value;
  const observations = [
    { source: contract.selected_source, value: selectedValue },
    ...candidates,
  ].filter((candidate) => candidate.source);
  const distinct = new Map<string, { source: string; value: unknown }>();
  for (const observation of observations) {
    const source = observation.source;
    const pattern = normalizeKnowledgeSourcePattern(source);
    if (!distinct.has(pattern)) distinct.set(pattern, observation);
  }
  return Array.from(distinct.values()).map((observation) =>
    knowledgeSourceOption(observation.source, observation.value),
  );
}

export function knowledgeFieldLabel(field: string) {
  const [group = '', ...nameParts] = field.split('.');
  const name = nameParts.join('.') || group;
  return {
    group: titleCaseToken(group),
    label: titleCaseToken(name.replaceAll('.', ' ')),
  };
}

function normalizeKnowledgeSourcePattern(source: string) {
  const separator = source.indexOf(':');
  if (separator < 0) return source;
  const collector = source.slice(0, separator);
  const locator = source
    .slice(separator + 1)
    .replace(/\/([A-Za-z_][A-Za-z0-9_]*):[^/]+/g, '/$1:{id}')
    .replace(/\/\d+(?=\/|$)/g, '/{index}');
  return `${collector}:${locator}`;
}

export function knowledgeValueLabel(value: unknown) {
  if (value == null) return '';
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return '';
    if (/^https?:\/\//i.test(trimmed)) {
      try {
        const parsed = new URL(trimmed);
        const filename = parsed.pathname.split('/').filter(Boolean).at(-1);
        return filename ? `${parsed.hostname} / ${filename}` : parsed.hostname;
      } catch {
        return trimmed.slice(0, 80);
      }
    }
    if (/^[a-z]+(?:_[a-z]+)+$/.test(trimmed)) return titleCaseToken(trimmed);
    return trimmed.length > 80 ? `${trimmed.slice(0, 77)}...` : trimmed;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  const encoded = JSON.stringify(value);
  return encoded.length > 80 ? `${encoded.slice(0, 77)}...` : encoded;
}

function knowledgeSourceOption(source: string, value: unknown): KnowledgeSourceOption {
  const separator = source.indexOf(':');
  const collector = separator < 0 ? source : source.slice(0, separator);
  const locator = separator < 0 ? '' : source.slice(separator + 1);
  const kind =
    {
      adapter: 'Platform connector',
      css_recipe: 'Saved selector',
      dom: 'Page element',
      jsonld: 'Structured data',
      js_state: 'Page data',
      microdata: 'Microdata',
      network: 'Network response',
      opengraph: 'Page metadata',
      url: 'Page URL',
    }[collector] ?? titleCaseToken(collector);
  const locatorLabel = knowledgeLocatorLabel(collector, locator);
  const valueLabel = knowledgeValueLabel(value);
  return {
    value: source,
    label: valueLabel
      ? `${valueLabel} · ${kind}`
      : locatorLabel
        ? `${kind} · ${locatorLabel}`
        : kind,
    kind,
    locator: locatorLabel || locator,
  };
}

function knowledgeLocatorLabel(collector: string, locator: string) {
  if (!locator) return '';
  if (collector === 'dom' || collector === 'css_recipe') return locator;
  if (collector === 'url') return 'Canonical URL';
  if (collector === 'opengraph') {
    const metadataName = locator.match(/(?:property|name)=["']([^"']+)/)?.[1] ?? locator;
    return titleCaseToken(metadataName.replace(/^(?:og|twitter):/, ''));
  }
  const parts = normalizeKnowledgeSourcePattern(`${collector}:${locator}`)
    .slice(collector.length + 1)
    .split('/')
    .filter(
      (part) =>
        part &&
        ![
          'embedded',
          '__NEXT_DATA__',
          'props',
          'pageProps',
          '__APOLLO_STATE__',
          'data',
          'rows',
        ].includes(part) &&
        part !== '{index}',
    )
    .map((part) => titleCaseToken(part.replace(':{id}', '').replace(/([a-z])([A-Z])/g, '$1 $2')));
  return parts.slice(-3).join(' › ');
}

export function selectorValue(record: Pick<SelectorRecord, 'xpath' | 'css_selector' | 'regex'>) {
  return record.xpath ?? record.css_selector ?? record.regex ?? '';
}

export function getTotalSelectorCount(surfaces: SurfaceWorkspace[]) {
  return surfaces.reduce((count, surface) => count + surface.selectorCount, 0);
}

export function getProfileCount(surfaces: SurfaceWorkspace[]) {
  return surfaces.filter((surface) => surface.profile).length;
}

export function profileSearchText(profile: DomainRunProfileRecord) {
  return [
    profile.domain,
    profile.surface,
    profile.profile.fetch_profile.fetch_mode,
    profile.profile.fetch_profile.extraction_source,
    profile.profile.fetch_profile.js_mode,
    profile.profile.fetch_profile.traversal_mode,
    profile.profile.locality_profile.geo_country,
    profile.profile.locality_profile.language_hint ?? '',
    profile.profile.locality_profile.currency_hint ?? '',
  ]
    .join(' ')
    .toLowerCase();
}

function defaultDomainRunProfile(): DomainRunProfile {
  return {
    version: 1,
    fetch_profile: {
      fetch_mode: 'auto',
      extraction_source: 'raw_html',
      js_mode: 'auto',
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 500,
      host_memory_ttl_seconds: null,
    },
    locality_profile: { geo_country: 'auto', language_hint: null, currency_hint: null },
    diagnostics_profile: {
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'matched_only',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    },
    acquisition_contract: {
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      handoff_eligible: false,
      handoff_cookie_engine: 'auto',
      required_rendering: false,
      required_traversal: false,
      required_network_payloads: false,
      last_quality_success: null,
      stale_after_failures: { failure_count: 0, stale: false },
    },
    source_run_id: null,
    saved_at: null,
  };
}

export function cloneDomainRunProfile(
  profile: DomainRunProfile | null | undefined,
): DomainRunProfile {
  const base = defaultDomainRunProfile();
  if (!profile) return base;
  return {
    version: 1,
    fetch_profile: { ...base.fetch_profile, ...(profile.fetch_profile ?? {}) },
    locality_profile: { ...base.locality_profile, ...(profile.locality_profile ?? {}) },
    diagnostics_profile: { ...base.diagnostics_profile, ...(profile.diagnostics_profile ?? {}) },
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

export function parseOptionalClampedNumber(value: string, min: number, max: number) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  if (Number.isNaN(parsed)) return null;
  return Math.min(max, Math.max(min, parsed));
}

export function profileDraftKey(domain: string, surface: string) {
  return `${domain}:${surface}`;
}

export function feedbackSearchText(feedback: DomainFieldFeedbackRecord) {
  return [
    feedback.domain,
    feedback.surface,
    feedback.field_name,
    feedback.action,
    feedback.source_kind,
    feedback.source_value ?? '',
    feedback.selector_kind ?? '',
    feedback.selector_value ?? '',
  ]
    .join(' ')
    .toLowerCase();
}

export function formatTimestamp(value: string | null | undefined) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleString();
}

export function isInternalDomainMemoryArtifact(
  domain: string,
  surfaceCount: number,
  hasCookieMemory: boolean,
  learningCount: number,
  completedRunCount: number,
) {
  const normalized = String(domain || '')
    .trim()
    .toLowerCase();
  if (!normalized.startsWith('owned-session-')) return false;
  return hasCookieMemory && surfaceCount === 0 && learningCount === 0 && completedRunCount === 0;
}

export function firstUsableDomain(domains: Array<string | null | undefined>) {
  for (const value of domains) {
    const normalized = String(value || '').trim();
    if (!normalized || isSpecialUseDomain(normalized)) continue;
    return normalized;
  }
  return '';
}
