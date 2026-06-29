import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useDeferredValue, useEffect, useMemo, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../../lib/api';
import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
  KnowledgeSiteRecord,
  SelectorDomainSummary,
  SelectorRecord,
} from '../../../lib/api/types';
import { getNormalizedDomain } from '../../../lib/format/domain';
import { buildDomainWorkspaces } from './build-workspaces';
import type { EditDraft, LocalRecord, SurfaceWorkspace } from './types';
import { useSelectorRecordActions } from './use-selector-record-actions';
import { cloneDomainRunProfile, firstUsableDomain, profileDraftKey } from './utils';

let localUidCounter = 0;
const EMPTY_SELECTOR_SUMMARIES: SelectorDomainSummary[] = [];
const EMPTY_PROFILES: DomainRunProfileRecord[] = [];
const EMPTY_COOKIES: DomainCookieMemoryRecord[] = [];
const EMPTY_FEEDBACK: DomainFieldFeedbackRecord[] = [];
const EMPTY_KNOWLEDGE_SITES: KnowledgeSiteRecord[] = [];
const EMPTY_RUNS: CrawlRun[] = [];

function latestCompletedRunIdFor(surfaceWorkspace: SurfaceWorkspace): number | null {
  let latestId: number | null = null;
  let latestTime = -Infinity;
  for (const run of surfaceWorkspace.completedRuns) {
    const time = new Date(run.completed_at ?? run.updated_at ?? run.created_at).getTime();
    if (time > latestTime) {
      latestTime = time;
      latestId = run.id;
    }
  }
  return latestId;
}

function toLocalRecords(selectorData: SelectorRecord[]) {
  return selectorData.map((record, index) => ({
    ...record,
    _uid: `${record.id}-${index}-${(localUidCounter += 1)}`,
  }));
}
export function useDomainMemoryWorkspace() {
  const [records, setRecords] = useState<LocalRecord[]>([]);
  const [error, setError] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [surfaceFilter, setSurfaceFilter] = useState('all');
  const [activeTab, setActiveTab] = useState('selectors');
  const [profileDrafts, setProfileDrafts] = useState<Record<string, DomainRunProfile>>({});
  const [profileSaveKey, setProfileSaveKey] = useState('');
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetPending, setResetPending] = useState(false);
  const [resetError, setResetError] = useState('');
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const queryClient = useQueryClient();
  const selectorSummaryQuery = useQuery({
    queryKey: queryKeys.domainMemory.domains(),
    queryFn: () => api.listSelectorSummaries(),
  });
  const profilesQuery = useQuery({
    queryKey: queryKeys.domainRunProfiles.all,
    queryFn: () => api.listDomainRunProfiles(),
  });
  const cookiesQuery = useQuery({
    queryKey: ['domain-cookie-memory'] as const,
    queryFn: () => api.listDomainCookieMemory(),
  });
  const feedbackQuery = useQuery({
    queryKey: ['domain-field-feedback', 100] as const,
    queryFn: () => api.listDomainFieldFeedback({ limit: 100 }),
  });
  const completedRunsQuery = useQuery({
    queryKey: queryKeys.runs.list({ status: 'completed', limit: 100 }),
    queryFn: () => api.listCrawls({ status: 'completed', limit: 100 }),
  });
  const knowledgeSitesQuery = useQuery({
    queryKey: ['knowledge-sites'] as const,
    queryFn: () => api.listKnowledgeSites(),
  });
  const workspaceQueries = [
    selectorSummaryQuery,
    profilesQuery,
    cookiesQuery,
    feedbackQuery,
    completedRunsQuery,
    knowledgeSitesQuery,
  ] as const;
  const queryError = workspaceQueries.map((query) => query.error).find(Boolean);
  const queryErrorMessage =
    queryError instanceof Error
      ? queryError.message
      : queryError
        ? 'Unable to load domain memory.'
        : '';

  const selectorSummaries = selectorSummaryQuery.data ?? EMPTY_SELECTOR_SUMMARIES;
  const profiles = profilesQuery.data ?? EMPTY_PROFILES;
  const cookies = cookiesQuery.data ?? EMPTY_COOKIES;
  const feedback = feedbackQuery.data ?? EMPTY_FEEDBACK;
  const knowledgeSites = knowledgeSitesQuery.data?.sites ?? EMPTY_KNOWLEDGE_SITES;
  const completedRuns = completedRunsQuery.data?.items ?? EMPTY_RUNS;
  const loading = workspaceQueries.some((query) => query.isLoading || query.isFetching);
  const hasLoadedOnce = workspaceQueries.every((query) => query.isFetched || query.isError);

  async function loadWorkspace() {
    setError('');
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.domainMemory.domains() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.domainRunProfiles.all }),
        queryClient.invalidateQueries({ queryKey: ['domain-cookie-memory'] }),
        queryClient.invalidateQueries({ queryKey: ['domain-field-feedback'] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runs.all }),
        queryClient.invalidateQueries({ queryKey: ['knowledge-sites'] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.selectors.all }),
      ]);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load domain memory.');
    }
  }

  const availableSurfaces = useMemo(
    () =>
      Array.from(
        new Set([
          ...selectorSummaries.map((summary) => summary.surface),
          ...records.map((record) => record.surface),
          ...profiles.map((profile) => profile.surface),
          ...feedback.map((entry) => entry.surface),
          ...completedRuns.map((run) => run.surface),
        ]),
      ).sort((left, right) => left.localeCompare(right)),
    [completedRuns, feedback, profiles, records, selectorSummaries],
  );

  const groupedWorkspaces = useMemo(
    () =>
      buildDomainWorkspaces({
        completedRuns,
        cookies,
        feedback,
        knowledgeSites,
        profiles,
        records,
        selectorSummaries,
        searchQuery: deferredSearchQuery,
        surfaceFilter,
      }),
    [
      completedRuns,
      cookies,
      deferredSearchQuery,
      feedback,
      knowledgeSites,
      profiles,
      records,
      selectorSummaries,
      surfaceFilter,
    ],
  );

  const resolvedSelectedDomain =
    selectedDomain && groupedWorkspaces.some((entry) => entry.domain === selectedDomain)
      ? selectedDomain
      : (groupedWorkspaces[0]?.domain ?? '');
  const selectedWorkspace =
    groupedWorkspaces.find((entry) => entry.domain === resolvedSelectedDomain) ??
    groupedWorkspaces[0] ??
    null;

  const selectorRecordsQuery = useQuery({
    queryKey: queryKeys.selectors.list({ domain: resolvedSelectedDomain }),
    queryFn: () => api.listSelectors({ domain: resolvedSelectedDomain }),
    enabled: Boolean(resolvedSelectedDomain),
  });
  const selectorLoading = selectorRecordsQuery.isLoading || selectorRecordsQuery.isFetching;

  useEffect(() => {
    setRecords(toLocalRecords(selectorRecordsQuery.data ?? []));
  }, [selectorRecordsQuery.data]);

  useEffect(() => {
    const loadedDomains = [
      ...selectorSummaries.map((row) => row.domain),
      ...profiles.map((row) => row.domain),
      ...cookies.map((row) => row.domain),
      ...feedback.map((row) => row.domain),
      ...knowledgeSites.map((row) => row.domain),
      ...completedRuns.map(
        (run) => String(run.result_summary?.domain || '').trim() || getNormalizedDomain(run.url),
      ),
    ];
    const currentDomainStillAvailable = loadedDomains.includes(selectedDomain)
      ? selectedDomain
      : '';
    const preferredDomain = firstUsableDomain([currentDomainStillAvailable, ...loadedDomains]);
    if (preferredDomain && preferredDomain !== selectedDomain) {
      setSelectedDomain(preferredDomain);
    }
  }, [
    completedRuns,
    cookies,
    feedback,
    knowledgeSites,
    profiles,
    selectedDomain,
    selectorSummaries,
  ]);

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
  }

  const { deleteDomainSelectors, deleteRecord, saveEdit, startEdit, toggleActive } =
    useSelectorRecordActions({
      cancelEdit,
      draft,
      editingId,
      setDraft,
      setEditingId,
      setError,
      setRecords,
      invalidateSelectorData: async (domain, surface) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.domainMemory.domains() }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.selectors.list({ domain: domain ?? '', surface: surface ?? '' }),
          }),
          queryClient.invalidateQueries({ queryKey: queryKeys.selectors.all }),
        ]);
      },
    });

  function profileDraftFor(domain: string, surfaceWorkspace: SurfaceWorkspace) {
    const key = profileDraftKey(domain, surfaceWorkspace.surface);
    return profileDrafts[key] ?? cloneDomainRunProfile(surfaceWorkspace.profile?.profile);
  }

  function updateProfileDraft(
    domain: string,
    surfaceWorkspace: SurfaceWorkspace,
    updater: (current: DomainRunProfile) => DomainRunProfile,
  ) {
    setError('');
    const key = profileDraftKey(domain, surfaceWorkspace.surface);
    setProfileDrafts((current) => ({
      ...current,
      [key]: updater(current[key] ?? cloneDomainRunProfile(surfaceWorkspace.profile?.profile)),
    }));
  }

  async function saveProfile(domain: string, surfaceWorkspace: SurfaceWorkspace) {
    const sourceRunId = latestCompletedRunIdFor(surfaceWorkspace);
    if (!sourceRunId) {
      setError('No completed run available to save this profile.');
      return;
    }
    const saveKey = profileDraftKey(domain, surfaceWorkspace.surface);
    setProfileSaveKey(saveKey);
    setError('');
    try {
      await api.saveDomainRunProfile(sourceRunId, {
        profile: profileDraftFor(domain, surfaceWorkspace),
      });
      setProfileDrafts((current) => {
        const next = { ...current };
        delete next[saveKey];
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.domainRunProfiles.all });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to save run profile.');
    } finally {
      setProfileSaveKey('');
    }
  }

  async function resetDomainMemoryWorkspace() {
    setResetPending(true);
    setResetError('');
    setError('');
    try {
      await api.resetDomainMemory();
      setProfileDrafts({});
      cancelEdit();
      await loadWorkspace();
      setResetDialogOpen(false);
    } catch (nextError) {
      setResetError(
        nextError instanceof Error ? nextError.message : 'Unable to reset domain memory.',
      );
    } finally {
      setResetPending(false);
    }
  }

  return {
    activeTab,
    availableSurfaces,
    cancelEdit,
    deleteDomainSelectors,
    deleteRecord,
    draft,
    editingId,
    error: error || queryErrorMessage,
    groupedWorkspaces,
    hasLoadedOnce,
    latestCompletedRunId: latestCompletedRunIdFor,
    loadedSelectorDomain: selectorRecordsQuery.data ? resolvedSelectedDomain : '',
    loading,
    loadWorkspace,
    knowledgeSites,
    profileDraftFor,
    profileSaveKey,
    resetDialogOpen,
    resetDomainMemoryWorkspace,
    resetError,
    resetPending,
    resolvedSelectedDomain,
    saveEdit,
    saveProfile,
    searchQuery,
    selectedWorkspace,
    selectorLoading,
    setActiveTab,
    setDraft,
    setResetDialogOpen,
    setResetError,
    setSearchQuery,
    setSelectedDomain,
    setSurfaceFilter,
    startEdit,
    surfaceFilter,
    toggleActive,
    updateProfileDraft,
  };
}

export type DomainMemoryWorkspaceController = ReturnType<typeof useDomainMemoryWorkspace>;
