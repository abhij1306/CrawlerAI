import type { CrawlDomain, DomainRunProfile } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { useEffect, useReducer, useRef, type Dispatch } from 'react';
import { cloneRunProfile, defaultRunProfile, type StudioMode } from './crawl-config-logic';
import { DOMAIN_OPTIONS, DOMAIN_TABS } from './domain-surface-config';
import type { CategoryMode, CrawlTab, FieldRowMessageTone, PdpMode } from './shared';

export type CrawlConfigScreenProps = {
  requestedTab: CrawlTab | null;
  requestedCategoryMode: CategoryMode | null;
  requestedPdpMode: PdpMode | null;
  requestedWorkspace?: 'crawl' | 'audit';
  requestedUrl?: string;
};

export const RUN_SETUP_ROW_CLASS =
  'grid gap-2 md:grid-cols-[110px_minmax(0,1fr)] md:items-center md:gap-3';
export const RUN_SETUP_CONTROL_CLASS = 'flex md:justify-self-end w-full md:w-auto';
export const RUN_SETUP_LABEL_CLASS = 'flex min-w-0 h-[var(--control-height)] items-center gap-3';
export const RUN_SETUP_STACK_CLASS = 'flex flex-col gap-3';
export const ADVANCED_CONTROL_ROW_CLASS =
  'grid gap-1.5 md:grid-cols-[140px_minmax(0,1fr)] md:items-center md:gap-3';
export const ADVANCED_COLUMN_CLASS = 'flex flex-col gap-4';
export const ADVANCED_SUBSECTION_CLASS = 'flex flex-col gap-2.5';
export const ADVANCED_SECTION_TITLE_CLASS = 'flex items-center gap-2 type-subheading';

export type CrawlRouteState = {
  crawlTab: CrawlTab;
  crawlDomain: CrawlDomain;
  categoryMode: CategoryMode;
  pdpMode: PdpMode;
};

export type CrawlConfigLocalState = {
  sitemapDomain: string;
  sitemapFilterKeyword: string;
  sitemapMaxUrls: number;
  csvFile: File | null;
  smartExtraction: boolean;
  studioMode: StudioMode;
  runProfile: DomainRunProfile;
  respectRobotsTxt: boolean;
  proxyEnabled: boolean;
  savedProfileDomain: string;
  savedProfileLoaded: boolean;
  savedProfileMessage: string;
  additionalDraft: string;
  additionalFields: string[];
  generatingSelectors: boolean;
  savingDomainMemory: boolean;
  designSubmitting: boolean;
  fieldConfigMessage: string;
  fieldConfigError: string;
  fieldRowMessages: Record<string, { tone: FieldRowMessageTone; message: string }>;
  activeFieldTestId: string | null;
  configError: string;
  workspaceMode: 'crawl' | 'audit';
};

export type CrawlConfigLocalAction =
  | { type: 'patch'; patch: Partial<CrawlConfigLocalState> }
  | { type: 'runProfileUpdated'; updater: (current: DomainRunProfile) => DomainRunProfile }
  | { type: 'additionalFieldsUpdated'; updater: (current: string[]) => string[] }
  | {
      type: 'fieldRowMessagesUpdated';
      updater: (
        current: Record<string, { tone: FieldRowMessageTone; message: string }>,
      ) => Record<string, { tone: FieldRowMessageTone; message: string }>;
    };

export function buildInitialLocalState(
  workspaceMode: 'crawl' | 'audit' = 'crawl',
): CrawlConfigLocalState {
  return {
    sitemapDomain: '',
    sitemapFilterKeyword: 'collections',
    sitemapMaxUrls: 500,
    csvFile: null,
    smartExtraction: false,
    studioMode: 'quick',
    runProfile: defaultRunProfile(),
    respectRobotsTxt: CRAWL_DEFAULTS.RESPECT_ROBOTS_TXT,
    proxyEnabled: false,
    savedProfileDomain: '',
    savedProfileLoaded: false,
    savedProfileMessage: '',
    additionalDraft: '',
    additionalFields: [],
    generatingSelectors: false,
    savingDomainMemory: false,
    designSubmitting: false,
    fieldConfigMessage: '',
    fieldConfigError: '',
    fieldRowMessages: {},
    activeFieldTestId: null,
    configError: '',
    workspaceMode,
  };
}

export function crawlConfigLocalReducer(
  state: CrawlConfigLocalState,
  action: CrawlConfigLocalAction,
): CrawlConfigLocalState {
  switch (action.type) {
    case 'patch':
      return { ...state, ...action.patch };
    case 'runProfileUpdated':
      return { ...state, runProfile: cloneRunProfile(action.updater(state.runProfile)) };
    case 'additionalFieldsUpdated':
      return { ...state, additionalFields: action.updater(state.additionalFields) };
    case 'fieldRowMessagesUpdated':
      return { ...state, fieldRowMessages: action.updater(state.fieldRowMessages) };
  }
}

export function bindCrawlConfigLocalDispatch(dispatchLocal: Dispatch<CrawlConfigLocalAction>) {
  const setRunProfile = (
    value: DomainRunProfile | ((current: DomainRunProfile) => DomainRunProfile),
  ) =>
    typeof value === 'function'
      ? dispatchLocal({ type: 'runProfileUpdated', updater: value })
      : dispatchLocal({ type: 'patch', patch: { runProfile: value } });
  const setAdditionalFields = (value: string[] | ((current: string[]) => string[])) =>
    typeof value === 'function'
      ? dispatchLocal({ type: 'additionalFieldsUpdated', updater: value })
      : dispatchLocal({ type: 'patch', patch: { additionalFields: value } });
  const setFieldRowMessages = (
    value:
      | Record<string, { tone: FieldRowMessageTone; message: string }>
      | ((
          current: Record<string, { tone: FieldRowMessageTone; message: string }>,
        ) => Record<string, { tone: FieldRowMessageTone; message: string }>),
  ) =>
    typeof value === 'function'
      ? dispatchLocal({ type: 'fieldRowMessagesUpdated', updater: value })
      : dispatchLocal({ type: 'patch', patch: { fieldRowMessages: value } });

  return {
    setSitemapDomain: (sitemapDomain: string) =>
      dispatchLocal({ type: 'patch', patch: { sitemapDomain } }),
    setSitemapFilterKeyword: (sitemapFilterKeyword: string) =>
      dispatchLocal({ type: 'patch', patch: { sitemapFilterKeyword } }),
    setSitemapMaxUrls: (sitemapMaxUrls: number) =>
      dispatchLocal({ type: 'patch', patch: { sitemapMaxUrls } }),
    setCsvFile: (csvFile: File | null) => dispatchLocal({ type: 'patch', patch: { csvFile } }),
    setSmartExtraction: (smartExtraction: boolean) =>
      dispatchLocal({ type: 'patch', patch: { smartExtraction } }),
    setStudioMode: (studioMode: StudioMode) =>
      dispatchLocal({ type: 'patch', patch: { studioMode } }),
    setRunProfile,
    setRespectRobotsTxt: (respectRobotsTxt: boolean) =>
      dispatchLocal({ type: 'patch', patch: { respectRobotsTxt } }),
    setProxyEnabled: (proxyEnabled: boolean) =>
      dispatchLocal({ type: 'patch', patch: { proxyEnabled } }),
    setSavedProfileDomain: (savedProfileDomain: string) =>
      dispatchLocal({ type: 'patch', patch: { savedProfileDomain } }),
    setSavedProfileLoaded: (savedProfileLoaded: boolean) =>
      dispatchLocal({ type: 'patch', patch: { savedProfileLoaded } }),
    setSavedProfileMessage: (savedProfileMessage: string) =>
      dispatchLocal({ type: 'patch', patch: { savedProfileMessage } }),
    setAdditionalDraft: (additionalDraft: string) =>
      dispatchLocal({ type: 'patch', patch: { additionalDraft } }),
    setAdditionalFields,
    setGeneratingSelectors: (generatingSelectors: boolean) =>
      dispatchLocal({ type: 'patch', patch: { generatingSelectors } }),
    setSavingDomainMemory: (savingDomainMemory: boolean) =>
      dispatchLocal({ type: 'patch', patch: { savingDomainMemory } }),
    setDesignSubmitting: (designSubmitting: boolean) =>
      dispatchLocal({ type: 'patch', patch: { designSubmitting } }),
    setFieldConfigMessage: (fieldConfigMessage: string) =>
      dispatchLocal({ type: 'patch', patch: { fieldConfigMessage } }),
    setFieldConfigError: (fieldConfigError: string) =>
      dispatchLocal({ type: 'patch', patch: { fieldConfigError } }),
    setFieldRowMessages,
    setActiveFieldTestId: (activeFieldTestId: string | null) =>
      dispatchLocal({ type: 'patch', patch: { activeFieldTestId } }),
    setConfigError: (configError: string) =>
      dispatchLocal({ type: 'patch', patch: { configError } }),
    setWorkspaceMode: (workspaceMode: 'crawl' | 'audit') =>
      dispatchLocal({ type: 'patch', patch: { workspaceMode } }),
  };
}

export type CrawlRouteAction =
  | {
      type: 'syncRequestedRoute';
      requestedTab: CrawlTab | null;
      requestedCategoryMode: CategoryMode | null;
      requestedPdpMode: PdpMode | null;
    }
  | { type: 'setTab'; tab: CrawlTab }
  | { type: 'setDomain'; domain: CrawlDomain }
  | { type: 'setCategoryMode'; mode: CategoryMode }
  | { type: 'setPdpMode'; mode: PdpMode }
  | { type: 'applyBulkPrefill'; domain?: CrawlDomain };

type BulkPrefill = {
  domain?: CrawlDomain;
  urls: string[];
  additional_fields?: string[];
};

function isCrawlDomain(value: unknown): value is CrawlDomain {
  return DOMAIN_OPTIONS.some((option) => option.value === value);
}

export function isBulkPrefill(value: unknown): value is BulkPrefill {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.domain === undefined || isCrawlDomain(candidate.domain)) &&
    Array.isArray(candidate.urls) &&
    candidate.urls.every((url) => typeof url === 'string') &&
    (candidate.additional_fields === undefined ||
      (Array.isArray(candidate.additional_fields) &&
        candidate.additional_fields.every((field) => typeof field === 'string')))
  );
}

function readBulkPrefill(): BulkPrefill | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return null;
    }
    const parsed = JSON.parse(stored) as unknown;
    return isBulkPrefill(parsed) && parsed.urls.length ? parsed : null;
  } catch {
    return null;
  }
}

function normalizeTabForDomain(domain: CrawlDomain, tab: CrawlTab): CrawlTab {
  const tabs = DOMAIN_TABS[domain];
  return tabs.some((entry) => entry.value === tab) ? tab : (tabs[0]?.value ?? 'category');
}

export function buildInitialRouteState({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>): CrawlRouteState {
  const bulkPrefill = readBulkPrefill();
  return {
    crawlTab: bulkPrefill ? 'pdp' : (requestedTab ?? 'category'),
    crawlDomain: bulkPrefill?.domain ?? 'auto',
    categoryMode: requestedCategoryMode ?? 'single',
    pdpMode: bulkPrefill ? 'batch' : (requestedPdpMode ?? 'single'),
  };
}

export function crawlRouteReducer(
  state: CrawlRouteState,
  action: CrawlRouteAction,
): CrawlRouteState {
  switch (action.type) {
    case 'syncRequestedRoute':
      return {
        ...state,
        crawlTab: action.requestedTab ?? 'category',
        categoryMode: action.requestedCategoryMode ?? 'single',
        pdpMode: action.requestedPdpMode ?? 'single',
      };
    case 'setTab':
      return { ...state, crawlTab: action.tab };
    case 'setDomain':
      return {
        ...state,
        crawlDomain: action.domain,
        crawlTab: normalizeTabForDomain(action.domain, state.crawlTab),
      };
    case 'setCategoryMode':
      return { ...state, categoryMode: action.mode };
    case 'setPdpMode':
      return { ...state, pdpMode: action.mode };
    case 'applyBulkPrefill':
      return {
        ...state,
        crawlTab: 'pdp',
        pdpMode: 'batch',
        crawlDomain: action.domain ?? state.crawlDomain,
      };
  }
}

export function useCrawlRouteState({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>) {
  const [routeState, dispatchRoute] = useReducer(
    crawlRouteReducer,
    { requestedTab, requestedCategoryMode, requestedPdpMode },
    buildInitialRouteState,
  );
  const bulkPrefillRouteSyncGuardRef = useRef(false);
  const didMountRef = useRef(false);

  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    if (bulkPrefillRouteSyncGuardRef.current) {
      if (requestedTab === 'pdp') {
        bulkPrefillRouteSyncGuardRef.current = false;
      } else {
        return;
      }
    }
    dispatchRoute({
      type: 'syncRequestedRoute',
      requestedTab,
      requestedCategoryMode,
      requestedPdpMode,
    });
  }, [requestedTab, requestedCategoryMode, requestedPdpMode]);

  return { routeState, dispatchRoute, bulkPrefillRouteSyncGuardRef };
}
