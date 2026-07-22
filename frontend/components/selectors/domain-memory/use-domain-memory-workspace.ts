import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useDeferredValue, useEffect, useMemo, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import { crawlsApi } from '../../../lib/api/crawls';
import { dashboardApi } from '../../../lib/api/dashboard';
import { domainMemoryApi } from '../../../lib/api/domain-memory';
import { knowledgeApi } from '../../../lib/api/knowledge';
import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
  KnowledgeSiteRecord,
} from '../../../lib/api/types';
import { getNormalizedDomain } from '../../../lib/format/domain';
import { buildDomainWorkspaces } from './build-workspaces';
import type { SurfaceWorkspace } from './types';
import { cloneDomainRunProfile, firstUsableDomain, profileDraftKey } from './utils';

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

export function useDomainMemoryWorkspace() {
  const [error, setError] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [surfaceFilter, setSurfaceFilter] = useState('all');
  const [activeTab, setActiveTab] = useState('profiles');
  const [profileDrafts, setProfileDrafts] = useState<Record<string, DomainRunProfile>>({});
  const [profileSaveKey, setProfileSaveKey] = useState('');
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetPending, setResetPending] = useState(false);
  const [resetError, setResetError] = useState('');
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const queryClient = useQueryClient();
  const profilesQuery = useQuery({
    queryKey: queryKeys.domainRunProfiles.all,
    queryFn: () => domainMemoryApi.listDomainRunProfiles(),
  });
  const cookiesQuery = useQuery({
    queryKey: queryKeys.domainMemory.cookieMemory(),
    queryFn: () => domainMemoryApi.listDomainCookieMemory(),
  });
  const feedbackQuery = useQuery({
    queryKey: queryKeys.domainMemory.fieldFeedback(100),
    queryFn: () => domainMemoryApi.listDomainFieldFeedback({ limit: 100 }),
  });
  const completedRunsQuery = useQuery({
    queryKey: queryKeys.runs.list({ status: 'completed', limit: 100 }),
    queryFn: () => crawlsApi.listCrawls({ status: 'completed', limit: 100 }),
  });
  const knowledgeSitesQuery = useQuery({
    queryKey: queryKeys.knowledgeGraph.sites(),
    queryFn: () => knowledgeApi.listKnowledgeSites(),
  });
  const workspaceQueries = [
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
        queryClient.invalidateQueries({ queryKey: queryKeys.domainRunProfiles.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.domainMemory.cookieMemory() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.domainMemory.fieldFeedback(100) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runs.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGraph.sites() }),
      ]);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load domain memory.');
    }
  }

  const availableSurfaces = useMemo(
    () =>
      Array.from(
        new Set([
          ...profiles.map((profile) => profile.surface),
          ...feedback.map((entry) => entry.surface),
          ...completedRuns.map((run) => run.surface),
        ]),
      ).sort((left, right) => left.localeCompare(right)),
    [completedRuns, feedback, profiles],
  );

  const groupedWorkspaces = useMemo(
    () =>
      buildDomainWorkspaces({
        completedRuns,
        cookies,
        feedback,
        knowledgeSites,
        profiles,
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

  useEffect(() => {
    const loadedDomains = [
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
  }, [completedRuns, cookies, feedback, knowledgeSites, profiles, selectedDomain]);

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
      await domainMemoryApi.saveDomainRunProfile(sourceRunId, {
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
      await dashboardApi.resetDomainMemory();
      setProfileDrafts({});
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
    error: error || queryErrorMessage,
    groupedWorkspaces,
    hasLoadedOnce,
    latestCompletedRunId: latestCompletedRunIdFor,
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
    saveProfile,
    searchQuery,
    selectedWorkspace,
    setActiveTab,
    setResetDialogOpen,
    setResetError,
    setSearchQuery,
    setSelectedDomain,
    setSurfaceFilter,
    surfaceFilter,
    updateProfileDraft,
  };
}

export type DomainMemoryWorkspaceController = ReturnType<typeof useDomainMemoryWorkspace>;
