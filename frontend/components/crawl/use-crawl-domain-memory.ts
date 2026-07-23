import { useDeferredValue, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { domainMemoryApi } from '../../lib/api/domain-memory';
import { selectorsApi } from '../../lib/api/selectors';
import type { CrawlSurface, DomainRunProfile } from '../../lib/api/types';
import { surfaceLabel } from '../../lib/format/domain';
import {
  buildFieldRowFromSelectorRecord,
  cloneRunProfile,
  defaultRunProfile,
  mergeFieldRows,
  normalizeHttpLookupDomain,
  selectRelevantSelectorRecords,
  stripDomainMemoryFieldRows,
} from './crawl-config-logic';
import type { bindCrawlConfigLocalDispatch } from './crawl-config-state';
import type { FieldRow } from './shared';

type LocalDispatch = Pick<
  ReturnType<typeof bindCrawlConfigLocalDispatch>,
  | 'setFieldConfigError'
  | 'setFieldConfigMessage'
  | 'setFieldRowMessages'
  | 'setRunProfile'
  | 'setSavedProfileDomain'
  | 'setSavedProfileLoaded'
  | 'setSavedProfileMessage'
>;

type SetFieldRows = (next: FieldRow[] | ((current: FieldRow[]) => FieldRow[])) => void;

type UseCrawlDomainMemoryOptions = {
  singleUrlMode: boolean;
  targetUrl: string;
  surface: CrawlSurface;
  setFieldRows: SetFieldRows;
  localDispatch: LocalDispatch;
};

export function useCrawlDomainMemory({
  singleUrlMode,
  targetUrl,
  surface,
  setFieldRows,
  localDispatch,
}: Readonly<UseCrawlDomainMemoryOptions>) {
  const profileDirtyRef = useRef(false);
  const normalizedTargetDomain = normalizeHttpLookupDomain(targetUrl);
  const profileLookupKey =
    singleUrlMode && normalizedTargetDomain ? `${normalizedTargetDomain}|${surface}` : '';
  const selectorLookupKey = profileLookupKey;

  const deferredTargetUrl = useDeferredValue(targetUrl.trim());
  const deferredTargetDomain = normalizeHttpLookupDomain(deferredTargetUrl);
  const deferredSurface = useDeferredValue(surface);
  const deferredLookupReady =
    deferredTargetDomain === normalizedTargetDomain && deferredSurface === surface;
  const queryEnabled =
    singleUrlMode && deferredLookupReady && Boolean(deferredTargetDomain && deferredSurface);

  const {
    data: profileData,
    isSuccess: isProfileSuccess,
    isError: isProfileError,
  } = useQuery({
    queryKey: queryKeys.domainRunProfiles.detail(deferredTargetDomain, deferredSurface),
    queryFn: ({ signal }) =>
      domainMemoryApi.getDomainRunProfile(
        {
          url: deferredTargetUrl,
          surface: deferredSurface,
        },
        { signal },
      ),
    enabled: queryEnabled,
    staleTime: 30_000,
  });

  const {
    data: selectorsData,
    isSuccess: isSelectorsSuccess,
    isError: isSelectorsError,
    error: selectorsError,
  } = useQuery({
    queryKey: queryKeys.selectors.list({
      domain: deferredTargetDomain,
      surface: deferredSurface,
    }),
    queryFn: ({ signal }) =>
      selectorsApi.listSelectors(
        { domain: deferredTargetDomain, surface: deferredSurface },
        { signal },
      ),
    enabled: queryEnabled,
    staleTime: 30_000,
  });

  useEffect(() => {
    profileDirtyRef.current = false;
    localDispatch.setSavedProfileLoaded(false);
    localDispatch.setSavedProfileDomain('');
    localDispatch.setSavedProfileMessage('');
    localDispatch.setRunProfile(defaultRunProfile());
  }, [localDispatch, profileLookupKey]);

  useEffect(() => {
    localDispatch.setFieldConfigError('');
    localDispatch.setFieldConfigMessage('');
    localDispatch.setFieldRowMessages({});
    setFieldRows((current) => stripDomainMemoryFieldRows(current));
  }, [localDispatch, selectorLookupKey, setFieldRows]);

  useEffect(() => {
    if (!queryEnabled) return;
    if (isProfileSuccess && profileData) {
      const response = profileData;
      const savedProfile = response.saved_run_profile;
      localDispatch.setSavedProfileDomain(response.domain);
      if (savedProfile && !profileDirtyRef.current) {
        localDispatch.setRunProfile(cloneRunProfile(savedProfile));
        localDispatch.setSavedProfileLoaded(true);
        localDispatch.setSavedProfileMessage(
          `Saved domain profile applied for ${response.domain} on ${surfaceLabel(response.surface)}. Explicit edits below override it for this run.`,
        );
        return;
      }
      localDispatch.setSavedProfileLoaded(Boolean(savedProfile));
      localDispatch.setSavedProfileMessage(
        savedProfile
          ? `Saved domain profile found for ${response.domain}. Your current edits are preserved for this run.`
          : '',
      );
      if (!savedProfile && !profileDirtyRef.current) {
        localDispatch.setRunProfile(defaultRunProfile());
      }
    } else if (isProfileError) {
      localDispatch.setSavedProfileLoaded(false);
      localDispatch.setSavedProfileDomain('');
      localDispatch.setSavedProfileMessage('');
    }
  }, [localDispatch, profileData, isProfileError, isProfileSuccess, queryEnabled]);

  useEffect(() => {
    if (!queryEnabled) return;
    localDispatch.setFieldConfigError('');
    if (isSelectorsSuccess && selectorsData) {
      const matchingRecords = selectRelevantSelectorRecords(selectorsData, deferredSurface);
      if (!matchingRecords.length) {
        setFieldRows((current) => stripDomainMemoryFieldRows(current));
        return;
      }
      const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
      setFieldRows((current) => mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows));
      localDispatch.setFieldRowMessages({});
    } else if (isSelectorsError) {
      localDispatch.setFieldConfigError(
        selectorsError instanceof Error ? selectorsError.message : 'Unable to load domain memory.',
      );
    }
  }, [
    deferredSurface,
    localDispatch,
    queryEnabled,
    selectorsData,
    selectorsError,
    isSelectorsError,
    isSelectorsSuccess,
    setFieldRows,
  ]);

  function markProfileDirty(updater: (current: DomainRunProfile) => DomainRunProfile) {
    profileDirtyRef.current = true;
    localDispatch.setRunProfile((current) => cloneRunProfile(updater(current)));
  }

  return { markProfileDirty };
}
