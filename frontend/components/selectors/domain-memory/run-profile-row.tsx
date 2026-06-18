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
          <div className="text-foreground text-sm font-medium">{surfaceLabel(surface.surface)}</div>
          <div className="text-muted text-xs">
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
    </>
  );
}
