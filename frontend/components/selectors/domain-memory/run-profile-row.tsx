import { Save } from 'lucide-react';

import type { DomainRunProfile } from '../../../lib/api/types';
import { Button } from '../../ui/primitives';
import type { SurfaceWorkspace } from './types';
import type { UpdateProfileDraft } from './profile-types';
import { RunProfileFields } from './run-profile-fields';
import { RunProfileToggles } from './run-profile-toggles';
import { formatTimestamp, surfaceLabel } from './utils';

type RunProfileRowProps = {
  domain: string;
  latestCompletedRunId: (surfaceWorkspace: SurfaceWorkspace) => number | null;
  profile: DomainRunProfile;
  profileSaveKey: string;
  saveKey: string;
  saveProfile: (domain: string, surfaceWorkspace: SurfaceWorkspace) => Promise<void>;
  surface: SurfaceWorkspace;
  updateProfileDraft: UpdateProfileDraft;
};

export function RunProfileRow({
  domain,
  latestCompletedRunId,
  profile,
  profileSaveKey,
  saveKey,
  saveProfile,
  surface,
  updateProfileDraft,
}: RunProfileRowProps) {
  const sourceRunId = latestCompletedRunId(surface);
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-foreground">{surfaceLabel(surface.surface)}</div>
          <div className="text-xs text-muted">
            Saved {formatTimestamp(surface.profile?.updated_at ?? null)} · Source run{' '}
            {sourceRunId ?? '—'}
          </div>
        </div>
        <Button
          type="button"
          variant="action"
          size="sm"
          disabled={!sourceRunId || profileSaveKey === saveKey}
          onClick={() => void saveProfile(domain, surface)}
        >
          <Save className="size-3.5" />
          {profileSaveKey === saveKey ? 'Saving...' : 'Save Profile'}
        </Button>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <RunProfileFields
          domain={domain}
          profile={profile}
          surface={surface}
          updateProfileDraft={updateProfileDraft}
        />
        <RunProfileToggles
          domain={domain}
          profile={profile}
          surface={surface}
          updateProfileDraft={updateProfileDraft}
        />
      </div>
      <InternalApiReplayEndpoints endpoints={profile.internal_api_endpoints ?? []} />
    </>
  );
}

function InternalApiReplayEndpoints({
  endpoints,
}: Readonly<{
  endpoints: NonNullable<DomainRunProfile['internal_api_endpoints']>;
}>) {
  return (
    <section className="mt-4 border-t border-border pt-3" aria-label="Internal API Replay">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h4 className="text-sm font-medium text-foreground">Internal API Replay</h4>
          <p className="text-xs text-muted">
            Verified public endpoint memory. Request payloads and response data stay private.
          </p>
        </div>
        <span className="text-xs text-muted">
          {endpoints.length} endpoint{endpoints.length === 1 ? '' : 's'}
        </span>
      </div>
      {endpoints.length ? (
        <div className="mt-3 grid gap-2">
          {endpoints.map((endpoint) => {
            const retrying = endpoint.failure_count > 0;
            return (
              <div
                key={`${endpoint.method}:${endpoint.source_route ?? ''}:${endpoint.source_run_id ?? ''}`}
                className="rounded-md border border-border bg-background-alt px-3 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{endpoint.method}</span>
                  <span className={retrying ? 'text-warning' : 'text-success'}>
                    {retrying ? `Retrying · ${endpoint.failure_count} failure(s)` : 'Ready'}
                  </span>
                </div>
                <div className="mt-1 break-all text-muted">
                  {endpoint.source_route || 'Route unavailable'}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          No verified public endpoints learned for this surface yet.
        </p>
      )}
    </section>
  );
}
