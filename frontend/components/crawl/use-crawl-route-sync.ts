import { useEffect, useLayoutEffect, type Dispatch } from 'react';
import type { UseFormSetValue } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { trackEvent } from '../../lib/telemetry/events';
import type { CategoryMode, CrawlTab, PdpMode } from './shared';
import { uniqueRequestedFields } from './shared';
import type { bindCrawlConfigLocalDispatch, CrawlRouteAction } from './crawl-config-state';
import { isBulkPrefill } from './crawl-config-state';
import { DOMAIN_OPTIONS } from './domain-surface-config';
import type { CrawlConfigFormValues } from './use-crawl-config';

type LocalDispatch = Pick<ReturnType<typeof bindCrawlConfigLocalDispatch>, 'setAdditionalFields'>;

type UseCrawlRouteSyncOptions = {
  requestedUrl: string;
  requestedTab: CrawlTab | null;
  requestedCategoryMode: CategoryMode | null;
  requestedPdpMode: PdpMode | null;
  crawlTab: CrawlTab;
  pdpMode: PdpMode;
  activeMode: CategoryMode | PdpMode;
  dispatchRoute: Dispatch<CrawlRouteAction>;
  bulkPrefillRouteSyncGuardRef: { current: boolean };
  setValue: UseFormSetValue<CrawlConfigFormValues>;
  localDispatch: LocalDispatch;
};

export function useCrawlRouteSync({
  requestedUrl,
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
  crawlTab,
  pdpMode,
  activeMode,
  dispatchRoute,
  bulkPrefillRouteSyncGuardRef,
  setValue,
  localDispatch,
}: Readonly<UseCrawlRouteSyncOptions>) {
  const navigate = useNavigate();

  useEffect(() => {
    if (requestedUrl) setValue('targetUrl', requestedUrl);
  }, [requestedUrl, setValue]);

  useEffect(() => {
    const routeMode = crawlTab === 'category' ? requestedCategoryMode : requestedPdpMode;
    if (
      bulkPrefillRouteSyncGuardRef.current ||
      (requestedTab === crawlTab && routeMode === activeMode)
    ) {
      return;
    }
    const nextUrl = `/crawl?module=${crawlTab}&mode=${activeMode}`;
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (currentUrl !== nextUrl) navigate(nextUrl, { replace: true });
  }, [
    activeMode,
    bulkPrefillRouteSyncGuardRef,
    crawlTab,
    requestedCategoryMode,
    requestedPdpMode,
    requestedTab,
    navigate,
  ]);

  useEffect(() => {
    if (bulkPrefillRouteSyncGuardRef.current && crawlTab === 'pdp' && pdpMode === 'batch') {
      bulkPrefillRouteSyncGuardRef.current = false;
    }
  }, [bulkPrefillRouteSyncGuardRef, crawlTab, pdpMode]);

  useLayoutEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored) as unknown;
      if (!isBulkPrefill(parsed) || !parsed.urls.length) {
        trackEvent('bulk_prefill_restore_failed', { reason: 'invalid_payload' });
        return;
      }
      bulkPrefillRouteSyncGuardRef.current = true;
      const domain =
        parsed.domain && DOMAIN_OPTIONS.some((option) => option.value === parsed.domain)
          ? parsed.domain
          : undefined;
      dispatchRoute({ type: 'applyBulkPrefill', domain });
      setValue('bulkUrls', parsed.urls.join('\n'));
      if (Array.isArray(parsed.additional_fields)) {
        localDispatch.setAdditionalFields(uniqueRequestedFields(parsed.additional_fields));
      }
      const nextUrl = '/crawl?module=pdp&mode=batch';
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (currentUrl !== nextUrl) navigate(nextUrl, { replace: true });
    } catch (error) {
      trackEvent('bulk_prefill_restore_failed', {
        reason: 'malformed_json',
        error_type: error instanceof Error ? error.name : 'UnknownError',
      });
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, [bulkPrefillRouteSyncGuardRef, dispatchRoute, localDispatch, navigate, setValue]);
}
