import type { DomainRunProfile } from '../api/types';

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
    source_run_id: profile.source_run_id ?? null,
    saved_at: profile.saved_at ?? null,
  };
}
