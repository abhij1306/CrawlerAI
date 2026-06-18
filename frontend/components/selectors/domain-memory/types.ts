import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfileRecord,
  SelectorRecord,
} from '../../../lib/api/types';

export type LocalRecord = SelectorRecord & { _uid: string };

export type EditDraft = {
  field_name: string;
  kind: 'xpath' | 'css_selector' | 'regex';
  selectorValue: string;
  source: string;
  is_active: boolean;
};

export type SurfaceWorkspace = {
  surface: string;
  selectorCount: number;
  selectors: LocalRecord[];
  profile: DomainRunProfileRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRuns: CrawlRun[];
};

export type DomainWorkspace = {
  domain: string;
  surfaces: SurfaceWorkspace[];
  cookieMemory: DomainCookieMemoryRecord | null;
  learning: DomainFieldFeedbackRecord[];
  completedRunCount: number;
  latestCompletedAt: string | null;
};
