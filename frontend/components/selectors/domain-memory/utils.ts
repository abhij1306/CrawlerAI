import type {
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
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

export function defaultDomainRunProfile(): DomainRunProfile {
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
      prefer_curl_handoff: false,
      handoff_cookie_engine: 'auto',
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
