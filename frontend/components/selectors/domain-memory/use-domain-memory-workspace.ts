import { useDeferredValue, useEffect, useEffectEvent, useMemo, useState } from 'react';

import { api } from '../../../lib/api';
import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfile,
  DomainRunProfileRecord,
  SelectorDomainSummary,
  SelectorRecord,
} from '../../../lib/api/types';
import { getNormalizedDomain } from '../../../lib/format/domain';
import { buildDomainWorkspaces } from './build-workspaces';
import type { EditDraft, LocalRecord, SurfaceWorkspace } from './types';
import { useSelectorRecordActions } from './use-selector-record-actions';
import { cloneDomainRunProfile, firstUsableDomain, profileDraftKey } from './utils';

let localUidCounter = 0;

function toLocalRecords(selectorData: SelectorRecord[]) {
  return selectorData.map((record, index) => ({
    ...record,
    _uid: `${record.id}-${index}-${(localUidCounter += 1)}`,
  }));
}
export function useDomainMemoryWorkspace() {
  const [records, setRecords] = useState<LocalRecord[]>([]);
  const [selectorSummaries, setSelectorSummaries] = useState<SelectorDomainSummary[]>([]);
  const [profiles, setProfiles] = useState<DomainRunProfileRecord[]>([]);
  const [cookies, setCookies] = useState<DomainCookieMemoryRecord[]>([]);
  const [feedback, setFeedback] = useState<DomainFieldFeedbackRecord[]>([]);
  const [completedRuns, setCompletedRuns] = useState<CrawlRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [selectorLoading, setSelectorLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('');
  const [loadedSelectorDomain, setLoadedSelectorDomain] = useState('');
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
  async function loadWorkspace(showLoading = true) {
    if (showLoading) setLoading(true);
    setError('');
    try {
      const [selectorSummaryData, profileData, cookieData, feedbackData, crawlData] =
        await Promise.all([
          api.listSelectorSummaries(),
          api.listDomainRunProfiles(),
          api.listDomainCookieMemory(),
          api.listDomainFieldFeedback({ limit: 100 }),
          api.listCrawls({ status: 'completed', limit: 100 }),
        ]);
      const preferredDomain = firstUsableDomain([
        selectedDomain,
        ...selectorSummaryData.map((row) => row.domain),
        ...profileData.map((row) => row.domain),
        ...cookieData.map((row) => row.domain),
        ...feedbackData.map((row) => row.domain),
        ...crawlData.items.map(
          (run) => String(run.result_summary?.domain || '').trim() || getNormalizedDomain(run.url),
        ),
      ]);
      const selectorData = preferredDomain
        ? await api.listSelectors({ domain: preferredDomain })
        : [];
      setSelectorSummaries(selectorSummaryData);
      setProfiles(profileData);
      setCookies(cookieData);
      setFeedback(feedbackData);
      setCompletedRuns(crawlData.items);
      setSelectedDomain(preferredDomain);
      setRecords(toLocalRecords(selectorData));
      setLoadedSelectorDomain(preferredDomain);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Unable to load domain memory.');
    } finally {
      setLoading(false);
      setHasLoadedOnce(true);
    }
  }
  const loadWorkspaceOnMount = useEffectEvent(() => {
    void loadWorkspace(false);
  });

  useEffect(() => {
    const timeoutId = window.setTimeout(() => loadWorkspaceOnMount(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

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
      ).sort(),
    [completedRuns, feedback, profiles, records, selectorSummaries],
  );

  const groupedWorkspaces = useMemo(
    () =>
      buildDomainWorkspaces({
        completedRuns,
        cookies,
        feedback,
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

  useEffect(() => {
    if (!resolvedSelectedDomain || loadedSelectorDomain === resolvedSelectedDomain) return;
    let cancelled = false;
    async function loadSelectedDomainSelectors() {
      setSelectorLoading(true);
      try {
        const selectorData = await api.listSelectors({ domain: resolvedSelectedDomain });
        if (cancelled) return;
        setRecords(toLocalRecords(selectorData));
        setLoadedSelectorDomain(resolvedSelectedDomain);
      } catch (nextError) {
        if (!cancelled)
          setError(nextError instanceof Error ? nextError.message : 'Unable to load selectors.');
      } finally {
        if (!cancelled) setSelectorLoading(false);
      }
    }
    void loadSelectedDomainSelectors();
    return () => {
      cancelled = true;
    };
  }, [loadedSelectorDomain, resolvedSelectedDomain]);

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
      setSelectorSummaries,
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

  function latestCompletedRunId(surfaceWorkspace: SurfaceWorkspace) {
    const latestRun = [...surfaceWorkspace.completedRuns].sort((left, right) => {
      const leftTime = new Date(left.completed_at ?? left.updated_at ?? left.created_at).getTime();
      const rightTime = new Date(
        right.completed_at ?? right.updated_at ?? right.created_at,
      ).getTime();
      return rightTime - leftTime;
    })[0];
    return latestRun?.id ?? null;
  }

  async function saveProfile(domain: string, surfaceWorkspace: SurfaceWorkspace) {
    const sourceRunId = latestCompletedRunId(surfaceWorkspace);
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
      await loadWorkspace(false);
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
    error,
    groupedWorkspaces,
    hasLoadedOnce,
    latestCompletedRunId,
    loadedSelectorDomain,
    loading,
    loadWorkspace,
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
