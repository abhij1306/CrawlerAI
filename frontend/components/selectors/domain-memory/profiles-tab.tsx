import type { DomainRunProfile } from '../../../lib/api/types';
import { DataRegionEmpty, DetailRow, SurfaceSection } from '../../ui/patterns';
import type { DomainWorkspace, SurfaceWorkspace } from './types';
import type { UpdateProfileDraft } from './profile-types';
import { RunProfileRow } from './run-profile-row';
import { profileDraftKey } from './utils';

type ProfilesTabProps = {
  latestCompletedRunId: (surfaceWorkspace: SurfaceWorkspace) => number | null;
  profileDraftFor: (domain: string, surfaceWorkspace: SurfaceWorkspace) => DomainRunProfile;
  profileSaveKey: string;
  saveProfile: (domain: string, surfaceWorkspace: SurfaceWorkspace) => Promise<void>;
  selectedWorkspace: DomainWorkspace;
  updateProfileDraft: UpdateProfileDraft;
};

export function ProfilesTab({
  latestCompletedRunId,
  profileDraftFor,
  profileSaveKey,
  saveProfile,
  selectedWorkspace,
  updateProfileDraft,
}: ProfilesTabProps) {
  const profileSurfaces = selectedWorkspace.surfaces.filter(
    (surface) => surface.profile || surface.completedRuns.length,
  );
  return (
    <SurfaceSection
      title="Run Profile Defaults"
      description="Edit and save reusable fetch defaults here. Domain Memory is the canonical home for saved run profiles."
      bodyClassName="space-y-3"
    >
      {profileSurfaces.length ? (
        profileSurfaces.map((surface) => {
          const saveKey = profileDraftKey(selectedWorkspace.domain, surface.surface);
          return (
            <DetailRow key={`${selectedWorkspace.domain}:${surface.surface}:profile`}>
              <RunProfileRow
                domain={selectedWorkspace.domain}
                latestCompletedRunId={latestCompletedRunId}
                profile={profileDraftFor(selectedWorkspace.domain, surface)}
                profileSaveKey={profileSaveKey}
                saveKey={saveKey}
                saveProfile={saveProfile}
                surface={surface}
                updateProfileDraft={updateProfileDraft}
              />
            </DetailRow>
          );
        })
      ) : (
        <DataRegionEmpty
          title="No saved run profiles"
          description="Complete a crawl for this domain, then save reusable defaults here."
        />
      )}
    </SurfaceSection>
  );
}
