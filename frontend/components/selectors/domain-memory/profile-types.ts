import type { DomainRunProfile } from '../../../lib/api/types';
import type { SurfaceWorkspace } from './types';

export type UpdateProfileDraft = (
  domain: string,
  surfaceWorkspace: SurfaceWorkspace,
  updater: (current: DomainRunProfile) => DomainRunProfile,
) => void;
