import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfileRecord,
  KnowledgeSiteRecord,
} from '@lib/api/types';

export type SurfaceWorkspace = {
  surface: string;
  profile: DomainRunProfileRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRuns: CrawlRun[];
};

export type DomainWorkspace = {
  domain: string;
  surfaces: SurfaceWorkspace[];
  cookieMemory: DomainCookieMemoryRecord | null;
  knowledgeSite: KnowledgeSiteRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRunCount: number;
  latestCompletedAt: string | null;
};
