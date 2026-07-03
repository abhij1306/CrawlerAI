import { describe, expect, it } from 'vite-plus/test';

import type { DomainRunProfile } from '../api/types';
import { defaultRunProfileBase, mergeRunProfile } from './run-profile';

describe('mergeRunProfile', () => {
  it('returns the base profile when the incoming profile is empty', () => {
    const base = defaultRunProfileBase();

    expect(mergeRunProfile(base, null)).toBe(base);
    expect(mergeRunProfile(base, undefined)).toBe(base);
  });

  it('deep-merges partial profile sections without dropping base nested values', () => {
    const base: DomainRunProfile = {
      ...defaultRunProfileBase(),
      source_run_id: 42,
      saved_at: '2026-07-03T00:00:00Z',
      acquisition_contract: {
        ...defaultRunProfileBase().acquisition_contract,
        stale_after_failures: { failure_count: 3, stale: true },
      },
    };
    const profile = {
      fetch_profile: { fetch_mode: 'browser_only' },
      locality_profile: { currency_hint: 'USD' },
      diagnostics_profile: { capture_network: 'all_small_json' },
      acquisition_contract: {
        required_network_payloads: true,
        stale_after_failures: { stale: false },
      },
    } as DomainRunProfile;

    const merged = mergeRunProfile(base, profile);

    expect(merged.fetch_profile.fetch_mode).toBe('browser_only');
    expect(merged.fetch_profile.request_delay_ms).toBe(base.fetch_profile.request_delay_ms);
    expect(merged.locality_profile.currency_hint).toBe('USD');
    expect(merged.locality_profile.geo_country).toBe(base.locality_profile.geo_country);
    expect(merged.diagnostics_profile.capture_network).toBe('all_small_json');
    expect(merged.diagnostics_profile.capture_html).toBe(base.diagnostics_profile.capture_html);
    expect(merged.acquisition_contract.required_network_payloads).toBe(true);
    expect(merged.acquisition_contract.stale_after_failures).toEqual({
      failure_count: 3,
      stale: false,
    });
    expect(merged.source_run_id).toBe(42);
    expect(merged.saved_at).toBe('2026-07-03T00:00:00Z');
  });

  it('uses present source metadata from the incoming profile', () => {
    const base: DomainRunProfile = {
      ...defaultRunProfileBase(),
      source_run_id: 42,
      saved_at: '2026-07-03T00:00:00Z',
    };

    expect(
      mergeRunProfile(base, {
        ...defaultRunProfileBase(),
        source_run_id: null,
        saved_at: null,
      }).source_run_id,
    ).toBeNull();
    expect(
      mergeRunProfile(base, {
        ...defaultRunProfileBase(),
        source_run_id: 7,
        saved_at: '2026-07-03T01:00:00Z',
      }).saved_at,
    ).toBe('2026-07-03T01:00:00Z');
  });
});
