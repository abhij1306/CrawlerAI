import type { DomainRunProfile } from '../api/types';
import { CRAWL_DEFAULTS } from '../constants/crawl-defaults';

export function defaultRunProfileBase(): DomainRunProfile {
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
      stale_after_failures: {
        failure_count: 0,
        stale: false,
      },
    },
    internal_api_endpoints: [],
    source_run_id: null,
    saved_at: null,
  };
}

export function mergeRunProfile(
  base: DomainRunProfile,
  profile: DomainRunProfile | null | undefined,
): DomainRunProfile {
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
    internal_api_endpoints: profile.internal_api_endpoints ?? base.internal_api_endpoints,
    source_run_id: profile.source_run_id !== undefined ? profile.source_run_id : base.source_run_id,
    saved_at: profile.saved_at !== undefined ? profile.saved_at : base.saved_at,
  };
}
