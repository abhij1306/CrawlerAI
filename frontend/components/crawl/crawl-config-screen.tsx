'use client';
import { Globe, Info, Plus, SlidersHorizontal, Sparkles } from 'lucide-react';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { startTransition, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react';
import { cn } from '../../lib/utils';
import { InlineAlert, TabBar } from '../ui/patterns';
import { Badge, Button, Dropdown, Card, Input, Textarea, Toggle, Tooltip } from '../ui/primitives';
import { api } from '../../lib/api';
import type { CrawlConfig, CrawlDomain, DomainRunProfile } from '../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../lib/constants/crawl-defaults';
import { getNormalizedDomain } from '../../lib/format/domain';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { UI_DELAYS } from '../../lib/constants/timing';
import { telemetryErrorPayload, trackEvent } from '../../lib/telemetry/events';
import {
  AdditionalFieldInput,
  clampNumber,
  CsvFileField,
  deriveSurface,
  FieldEditorHeader,
  type FieldRow,
  ManualFieldEditor,
  parseRequestedCategoryMode,
  parseRequestedCrawlTab,
  parseLines,
  parseRequestedPdpMode,
  SettingSection,
  SliderRow,
  SitemapConfigFields,
  TargetUrlField,
  normalizeField,
  uniqueRequestedFields,
} from './shared';
import {
  applyDiagnosticsPreset,
  BROWSER_ENGINE_OPTIONS,
  buildDispatch,
  buildFieldRowFromSelectorRecord,
  buildFieldRowFromSuggestion,
  canPreview,
  CAPTURE_NETWORK_OPTIONS,
  cloneRunProfile,
  defaultRunProfile,
  diagnosticsPresetForProfile,
  EXTRACTION_SOURCE_OPTIONS,
  FETCH_MODE_OPTIONS,
  inferRunTypeHint,
  isSingleUrlMode,
  JS_MODE_OPTIONS,
  mergeFieldRows,
  normalizeHttpLookupDomain,
  parseOptionalClampedNumber,
  selectRelevantSelectorRecords,
  selectorGenerationFields,
  stripDomainMemoryFieldRows,
  surfaceLabel,
  TRAVERSAL_MODE_OPTIONS,
  type BrowserEngine,
  type CaptureNetworkMode,
  type DiagnosticsPreset,
  type ExtractionSource,
  type FetchMode,
  type JsMode,
  type TraversalDropdownValue,
} from './crawl-config-logic';
import { resolveAutoSurface } from './auto-surface';
import { CrawlAuditMode, CrawlWorkspaceHeader } from './crawl-audit-mode';
import { CrawlActionButtons } from './crawl-action-buttons';
import { testCrawlFieldRow } from './crawl-field-test';
import {
  ADVANCED_COLUMN_CLASS,
  ADVANCED_CONTROL_ROW_CLASS,
  ADVANCED_SECTION_TITLE_CLASS,
  ADVANCED_SUBSECTION_CLASS,
  bindCrawlConfigLocalDispatch,
  buildInitialLocalState,
  crawlConfigLocalReducer,
  isBulkPrefill,
  RUN_SETUP_CONTROL_CLASS,
  RUN_SETUP_LABEL_CLASS,
  RUN_SETUP_ROW_CLASS,
  type CrawlConfigScreenProps,
  useCrawlRouteState,
} from './crawl-config-state';
import { createDesignCrawlRun } from './design-crawl-submit';
import { DOMAIN_OPTIONS, DOMAIN_TABS } from './domain-surface-config';
import * as crawlConfigForm from './use-crawl-config';

export function CrawlConfigScreen({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
  requestedWorkspace = 'crawl',
  requestedUrl = '',
}: Readonly<CrawlConfigScreenProps>) {
  const router = useRouter();
  const { routeState, dispatchRoute, bulkPrefillRouteSyncGuardRef } = useCrawlRouteState({
    requestedTab,
    requestedCategoryMode,
    requestedPdpMode,
  });
  const { crawlTab, crawlDomain, categoryMode, pdpMode } = routeState;
  const {
    handleSubmit,
    setValue,
    fieldRows,
    setFieldRows,
    targetUrl,
    bulkUrls,
    maxRecords,
    proxyInput,
    isSubmitting,
  } = crawlConfigForm.useCrawlConfig();
  const [localState, dispatchLocal] = useReducer(
    crawlConfigLocalReducer,
    requestedWorkspace,
    buildInitialLocalState,
  );
  const {
    sitemapDomain,
    sitemapFilterKeyword,
    sitemapMaxUrls,
    csvFile,
    smartExtraction,
    studioMode,
    runProfile,
    respectRobotsTxt,
    proxyEnabled,
    savedProfileDomain,
    savedProfileLoaded,
    savedProfileMessage,
    additionalDraft,
    additionalFields,
    generatingSelectors,
    savingDomainMemory,
    designSubmitting,
    fieldConfigMessage,
    fieldConfigError,
    fieldRowMessages,
    activeFieldTestId,
    configError,
    workspaceMode,
  } = localState;
  const localDispatch = useMemo(() => bindCrawlConfigLocalDispatch(dispatchLocal), [dispatchLocal]);
  const profileLookupRequestRef = useRef(0);
  const domainMemoryLookupRequestRef = useRef(0);
  const profileLookupTargetUrlRef = useRef('');
  const profileDirtyRef = useRef(false);
  const lastProfileKeyRef = useRef('');
  const lastDomainMemoryKeyRef = useRef('');
  const modePickerEnabled = crawlDomain === 'commerce' || crawlDomain === 'jobs';
  const selectedMode = crawlTab === 'category' ? categoryMode : pdpMode;
  const activeMode = modePickerEnabled ? selectedMode : 'single';
  const surface = deriveSurface(crawlDomain, crawlTab);
  const autoSurfaceResolution = useMemo(
    () => (surface === 'auto' ? resolveAutoSurface(targetUrl, crawlTab) : null),
    [targetUrl, crawlTab, surface],
  );
  const effectiveSurface = autoSurfaceResolution?.surface ?? surface;
  const domainTabs = DOMAIN_TABS[crawlDomain];
  const activeTabLabel =
    domainTabs.find((tab) => tab.value === crawlTab)?.label ?? surfaceLabel(surface);
  const showSurfaceTabs = domainTabs.length > 1;
  const showModePicker = modePickerEnabled;
  const singleUrlMode = isSingleUrlMode(crawlTab, activeMode);
  const normalizedTargetDomain = normalizeHttpLookupDomain(targetUrl);
  const profileLookupKey =
    singleUrlMode && normalizedTargetDomain && effectiveSurface
      ? `${normalizedTargetDomain}|${effectiveSurface}`
      : '';
  const domainMemoryLookupKey =
    singleUrlMode && normalizedTargetDomain && effectiveSurface
      ? `${normalizedTargetDomain}|${effectiveSurface}`
      : '';
  const diagnosticsPreset = diagnosticsPresetForProfile(runProfile);

  // Adjust state during render when the lookup key changes, instead of in an
  // effect. This avoids an extra render with stale UI between commits. See
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  /* eslint-disable react-hooks/refs -- Existing render-time state synchronization uses refs as change guards. */
  if (lastProfileKeyRef.current !== profileLookupKey) {
    profileDirtyRef.current = false;
    lastProfileKeyRef.current = profileLookupKey;
    if (!profileLookupKey) {
      localDispatch.setSavedProfileLoaded(false);
      localDispatch.setSavedProfileDomain('');
      localDispatch.setSavedProfileMessage('');
      localDispatch.setRunProfile(defaultRunProfile());
    }
  }
  if (lastDomainMemoryKeyRef.current !== domainMemoryLookupKey) {
    lastDomainMemoryKeyRef.current = domainMemoryLookupKey;
    localDispatch.setFieldConfigError('');
    localDispatch.setFieldConfigMessage('');
    localDispatch.setFieldRowMessages({});
    setFieldRows((current) => stripDomainMemoryFieldRows(current));
  }
  /* eslint-enable react-hooks/refs */

  useEffect(() => {
    if (requestedWorkspace === 'audit' && requestedUrl) {
      setValue('targetUrl', requestedUrl);
    }
  }, [requestedUrl, requestedWorkspace, setValue]);
  useEffect(() => {
    profileLookupTargetUrlRef.current = profileLookupKey ? targetUrl.trim() : '';
  }, [profileLookupKey, targetUrl]);
  useEffect(() => {
    if (workspaceMode === 'audit') {
      return;
    }
    const routeMode = crawlTab === 'category' ? requestedCategoryMode : requestedPdpMode;
    if (
      bulkPrefillRouteSyncGuardRef.current ||
      (requestedTab === crawlTab && routeMode === activeMode)
    ) {
      return;
    }
    const nextUrl = `/crawl?module=${crawlTab}&mode=${activeMode}`;
    if (typeof window !== 'undefined') {
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (currentUrl !== nextUrl) {
        window.history.replaceState(null, '', nextUrl);
      }
    }
  }, [
    activeMode,
    bulkPrefillRouteSyncGuardRef,
    crawlTab,
    requestedCategoryMode,
    requestedPdpMode,
    requestedTab,
    workspaceMode,
  ]);

  useEffect(() => {
    if (bulkPrefillRouteSyncGuardRef.current && crawlTab === 'pdp' && pdpMode === 'batch') {
      bulkPrefillRouteSyncGuardRef.current = false;
    }
  }, [bulkPrefillRouteSyncGuardRef, crawlTab, pdpMode]);

  useLayoutEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as unknown;
      if (isBulkPrefill(parsed) && parsed.urls.length) {
        bulkPrefillRouteSyncGuardRef.current = true;
        const parsedDomain = parsed.domain;
        const domain =
          parsedDomain && DOMAIN_OPTIONS.some((option) => option.value === parsedDomain)
            ? parsedDomain
            : undefined;
        dispatchRoute({ type: 'applyBulkPrefill', domain });
        setValue('bulkUrls', parsed.urls.join('\n'));
        if (Array.isArray(parsed.additional_fields)) {
          localDispatch.setAdditionalFields(uniqueRequestedFields(parsed.additional_fields));
        }
        const nextUrl = '/crawl?module=pdp&mode=batch';
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        if (currentUrl !== nextUrl) {
          window.history.replaceState(null, '', nextUrl);
        }
      }
    } catch {
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, [bulkPrefillRouteSyncGuardRef, dispatchRoute, localDispatch, setValue]);

  useEffect(() => {
    if (!profileLookupKey) {
      return;
    }
    const requestId = profileLookupRequestRef.current + 1;
    profileLookupRequestRef.current = requestId;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.getDomainRunProfile({
          url: profileLookupTargetUrlRef.current,
          surface: effectiveSurface,
        });
        if (profileLookupRequestRef.current === requestId) {
          const savedProfile = response.saved_run_profile;
          localDispatch.setSavedProfileDomain(response.domain);
          if (savedProfile && !profileDirtyRef.current) {
            localDispatch.setRunProfile(cloneRunProfile(savedProfile));
            localDispatch.setSavedProfileLoaded(true);
            localDispatch.setSavedProfileMessage(
              `Saved domain profile applied for ${response.domain} on ${surfaceLabel(response.surface)}. Explicit edits below override it for this run.`,
            );
          } else {
            localDispatch.setSavedProfileLoaded(Boolean(savedProfile));
            localDispatch.setSavedProfileMessage(
              savedProfile
                ? `Saved domain profile found for ${response.domain}. Your current edits are preserved for this run.`
                : '',
            );
            if (!savedProfile && !profileDirtyRef.current) {
              localDispatch.setRunProfile(defaultRunProfile());
            }
          }
        }
      } catch {
        if (profileLookupRequestRef.current === requestId) {
          localDispatch.setSavedProfileLoaded(false);
          localDispatch.setSavedProfileDomain('');
          localDispatch.setSavedProfileMessage('');
        }
      }
    }, UI_DELAYS.DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [effectiveSurface, localDispatch, profileLookupKey]);

  useEffect(() => {
    if (!domainMemoryLookupKey) {
      return;
    }
    const requestId = domainMemoryLookupRequestRef.current + 1;
    domainMemoryLookupRequestRef.current = requestId;
    const lookupDomain = normalizedTargetDomain;
    const timer = window.setTimeout(async () => {
      localDispatch.setFieldConfigError('');
      try {
        const records = await api.listSelectors({ domain: lookupDomain });
        if (domainMemoryLookupRequestRef.current === requestId) {
          const matchingRecords = selectRelevantSelectorRecords(records, effectiveSurface);
          if (!matchingRecords.length) {
            setFieldRows((current) => stripDomainMemoryFieldRows(current));
            return;
          }
          const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
          setFieldRows((current) =>
            mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows),
          );
          localDispatch.setFieldRowMessages({});
        }
      } catch (error) {
        if (domainMemoryLookupRequestRef.current === requestId) {
          localDispatch.setFieldConfigError(
            error instanceof Error ? error.message : 'Unable to load domain memory.',
          );
        }
      }
    }, UI_DELAYS.DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [
    domainMemoryLookupKey,
    effectiveSurface,
    localDispatch,
    normalizedTargetDomain,
    setFieldRows,
  ]);

  const config = useMemo<CrawlConfig>(
    () => ({
      module: crawlTab,
      domain: crawlDomain,
      mode: activeMode,
      target_url: targetUrl,
      bulk_urls: bulkUrls,
      sitemap_domain: activeMode === 'sitemap' ? sitemapDomain.trim() : undefined,
      sitemap_filter_keyword:
        activeMode === 'sitemap' ? sitemapFilterKeyword.trim() || 'collections' : undefined,
      sitemap_max_urls: activeMode === 'sitemap' ? sitemapMaxUrls : undefined,
      csv_file: csvFile,
      smart_extraction: smartExtraction,
      max_records: clampNumber(
        maxRecords,
        CRAWL_LIMITS.MIN_RECORDS,
        CRAWL_LIMITS.MAX_RECORDS,
        CRAWL_DEFAULTS.MAX_RECORDS,
      ),
      respect_robots_txt: respectRobotsTxt,
      proxy_enabled: proxyEnabled,
      proxy_lines: proxyEnabled ? parseLines(proxyInput) : [],
      additional_fields: additionalFields,
    }),
    [
      additionalFields,
      bulkUrls,
      activeMode,
      crawlDomain,
      crawlTab,
      csvFile,
      maxRecords,
      proxyEnabled,
      proxyInput,
      respectRobotsTxt,
      sitemapDomain,
      sitemapFilterKeyword,
      sitemapMaxUrls,
      smartExtraction,
      targetUrl,
    ],
  );

  async function loadDomainMemoryForUrl(rawUrl: string) {
    const target = rawUrl.trim();
    const domain = getNormalizedDomain(target);
    if (!target || !domain) {
      return;
    }
    const requestId = domainMemoryLookupRequestRef.current + 1;
    domainMemoryLookupRequestRef.current = requestId;
    localDispatch.setFieldConfigError('');
    try {
      const records = await api.listSelectors({ domain });
      if (domainMemoryLookupRequestRef.current === requestId) {
        const matchingRecords = selectRelevantSelectorRecords(records, effectiveSurface);
        if (!matchingRecords.length) {
          localDispatch.setFieldConfigMessage('No saved domain memory found for this URL.');
          setFieldRows((current) => stripDomainMemoryFieldRows(current));
          return;
        }
        const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
        setFieldRows((current) =>
          mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows),
        );
        localDispatch.setFieldRowMessages({});
        localDispatch.setFieldConfigMessage(
          `Loaded ${matchingRecords.length} saved selector${matchingRecords.length === 1 ? '' : 's'} from domain memory.`,
        );
      }
    } catch (error) {
      if (domainMemoryLookupRequestRef.current === requestId) {
        localDispatch.setFieldConfigError(
          error instanceof Error ? error.message : 'Unable to load domain memory.',
        );
      }
    }
  }

  function markProfileDirty(updater: (current: DomainRunProfile) => DomainRunProfile) {
    profileDirtyRef.current = true;
    localDispatch.setRunProfile((current) => cloneRunProfile(updater(current)));
  }

  async function startCrawl() {
    localDispatch.setConfigError('');
    try {
      const parsedConfig = crawlConfigForm.crawlConfigSchema.safeParse(
        crawlConfigForm.transformFormToSubmission({
          mode: config.mode,
          targetUrl: config.target_url,
          bulkUrls: config.bulk_urls,
          maxRecords,
        }),
      );
      if (!parsedConfig.success) {
        throw new Error(parsedConfig.error.issues[0]?.message ?? 'Unable to launch crawl.');
      }
      const dispatch = buildDispatch(config, fieldRows, {
        runProfile,
        studioMode,
      });
      if (studioMode === 'advanced') {
        trackEvent('advanced_mode_selected_vs_effective', {
          module: config.module,
          selected_advanced_mode: runProfile.fetch_profile.traversal_mode,
          effective_advanced_mode: dispatch.settings.advanced_mode ?? null,
        });
      }
      let response: { run_id: number };
      if (dispatch.runType === 'csv') {
        if (!dispatch.csvFile) {
          throw new Error('CSV file is missing.');
        }
        response = await api.createCsvCrawl({
          file: dispatch.csvFile,
          surface: dispatch.surface,
          additionalFields: dispatch.additionalFields,
          settings: dispatch.settings,
        });
      } else {
        response = await api.createCrawl({
          run_type: dispatch.runType,
          url: dispatch.url,
          urls: dispatch.urls,
          surface: dispatch.surface,
          settings: dispatch.settings,
          additional_fields: dispatch.additionalFields,
        });
      }
      startTransition(() => {
        router.replace(`/crawl?run_id=${response.run_id}` as Route);
        router.refresh();
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to launch crawl.';
      trackEvent(
        'crawl_submit_error_rate',
        telemetryErrorPayload(error, {
          module: config.module,
          mode: config.mode,
          surface,
          studio_mode: studioMode,
          smart_extraction: config.smart_extraction,
          run_type_hint: inferRunTypeHint(config),
        }),
      );
      localDispatch.setConfigError(message);
    }
  }

  async function startDesignCrawl() {
    localDispatch.setConfigError('');
    localDispatch.setDesignSubmitting(true);
    try {
      const response = await createDesignCrawlRun({ targetUrl, config, runProfile });
      startTransition(() => {
        router.replace(`/crawl?run_id=${response.run_id}` as Route);
        router.refresh();
      });
    } catch (error) {
      localDispatch.setConfigError(
        error instanceof Error ? error.message : 'Unable to launch design crawl.',
      );
    } finally {
      localDispatch.setDesignSubmitting(false);
    }
  }

  function addManualField() {
    setFieldRows((current) => [
      ...current,
      {
        id: crawlConfigForm.createManualFieldRowId(),
        fieldName: '',
        cssSelector: '',
        xpath: '',
        regex: '',
        cssState: 'idle',
        xpathState: 'idle',
        regexState: 'idle',
      },
    ]);
  }

  async function generateFieldSelectors() {
    const target = targetUrl.trim();
    if (!target) {
      localDispatch.setFieldConfigError('Enter a target URL before generating selectors.');
      return;
    }
    const expectedColumns = selectorGenerationFields(effectiveSurface, fieldRows, additionalFields);
    if (!expectedColumns.length) {
      localDispatch.setFieldConfigError(
        'Add at least one field or additional field before generating selectors.',
      );
      return;
    }
    localDispatch.setGeneratingSelectors(true);
    localDispatch.setFieldConfigError('');
    try {
      const response = await api.suggestSelectors({
        url: target,
        expected_columns: expectedColumns,
        surface: effectiveSurface,
      });
      const incomingRows = expectedColumns.map((fieldName) =>
        buildFieldRowFromSuggestion(
          fieldName,
          response.suggestions[normalizeField(fieldName)]?.[0],
        ),
      );
      setFieldRows((current) => mergeFieldRows(current, incomingRows));
      localDispatch.setFieldRowMessages({});
      localDispatch.setFieldConfigMessage(
        `Generated selector suggestions for ${expectedColumns.length} field${expectedColumns.length === 1 ? '' : 's'}.`,
      );
    } catch (error) {
      localDispatch.setFieldConfigError(
        error instanceof Error ? error.message : 'Unable to generate selectors.',
      );
    } finally {
      localDispatch.setGeneratingSelectors(false);
    }
  }

  async function testFieldRow(row: FieldRow) {
    await testCrawlFieldRow({
      row,
      targetUrl,
      setActiveId: localDispatch.setActiveFieldTestId,
      setMessage: (rowId, tone, message) =>
        localDispatch.setFieldRowMessages((current) => ({
          ...current,
          [rowId]: { tone, message },
        })),
    });
  }

  async function saveToDomainMemory() {
    const target = targetUrl.trim();
    const domain = getNormalizedDomain(target);
    if (!target || !domain) {
      localDispatch.setFieldConfigError('Enter a target URL before saving domain memory.');
      return;
    }
    const dedupedMap = new Map<string, FieldRow>();
    for (const row of fieldRows) {
      const field = normalizeField(row.fieldName);
      if (field && (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim())) {
        dedupedMap.set(field, row);
      }
    }
    const dedupedRows = Array.from(dedupedMap.values());
    if (!dedupedRows.length) {
      localDispatch.setFieldConfigError(
        'Add at least one selector row before saving domain memory.',
      );
      return;
    }
    localDispatch.setSavingDomainMemory(true);
    localDispatch.setFieldConfigError('');
    try {
      const existingRecords = selectRelevantSelectorRecords(
        await api.listSelectors({ domain }),
        effectiveSurface,
      );
      const existingByField = new Map(
        existingRecords.map((record) => [normalizeField(record.field_name), record] as const),
      );
      const settled = await Promise.allSettled(
        dedupedRows.map(async (row) => {
          const fieldName = normalizeField(row.fieldName);
          const payload = {
            field_name: fieldName,
            css_selector: row.cssSelector.trim() || undefined,
            xpath: row.xpath.trim() || undefined,
            regex: row.regex.trim() || undefined,
            source: 'crawl_config',
            status: 'validated' as const,
            is_active: true,
          };
          const existing = existingByField.get(fieldName);
          if (existing) {
            await api.updateSelector(existing.id, payload);
            return;
          }
          await api.createSelector({
            domain,
            surface: effectiveSurface,
            ...payload,
          });
        }),
      );
      const failedCount = settled.filter((result) => result.status === 'rejected').length;
      const savedCount = settled.length - failedCount;
      if (failedCount) {
        localDispatch.setFieldConfigError(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'}, ${failedCount} failed.`,
        );
      } else {
        localDispatch.setFieldConfigMessage(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'} to domain memory.`,
        );
      }
      if (savedCount) {
        await loadDomainMemoryForUrl(target);
      }
    } catch (error) {
      localDispatch.setFieldConfigError(
        error instanceof Error ? error.message : 'Unable to save domain memory.',
      );
    } finally {
      localDispatch.setSavingDomainMemory(false);
    }
  }
  const hasTarget =
    crawlTab === 'category' && activeMode === 'sitemap'
      ? sitemapDomain.trim().length > 0
      : singleUrlMode
        ? targetUrl.trim().length > 0
        : bulkUrls.trim().length > 0 || csvFile !== null;
  const canSubmit =
    hasTarget &&
    canPreview(config, fieldRows, { runProfile, studioMode }) &&
    !isSubmitting &&
    !designSubmitting;
  const canSubmitDesign = targetUrl.trim().length > 0 && !isSubmitting && !designSubmitting;
  function selectWorkspace(value: string) {
    if (value !== 'crawl' && value !== 'audit') return;
    localDispatch.setWorkspaceMode(value);
    window.history.replaceState(
      null,
      '',
      value === 'audit' ? '/crawl?tool=audit' : `/crawl?module=${crawlTab}&mode=${activeMode}`,
    );
  }
  if (workspaceMode === 'audit')
    return (
      <CrawlAuditMode
        targetUrl={targetUrl}
        onTargetUrlChange={(value) => setValue('targetUrl', value)}
        onWorkspaceChange={selectWorkspace}
      />
    );

  return (
    <div className="page-stack gap-4">
      <CrawlWorkspaceHeader value="crawl" onChange={selectWorkspace} />
      <form
        className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_380px] xl:items-stretch"
        onSubmit={(event) => void handleSubmit(startCrawl)(event)}
      >
        <Card className="section-card overflow-hidden p-0">
          <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
            <span className="type-heading-3">Target URL</span>
            <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
              {activeTabLabel}
            </Badge>
          </header>
          <div className="space-y-5 px-6 pt-4 pb-6">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
              <div className="ml-[-4px] flex flex-wrap items-center gap-2.5">
                {showSurfaceTabs ? (
                  <TabBar
                    value={crawlTab}
                    onChange={(value) => {
                      const parsed = parseRequestedCrawlTab(value);
                      if (parsed) {
                        dispatchRoute({ type: 'setTab', tab: parsed });
                      }
                    }}
                    options={domainTabs}
                  />
                ) : null}
                {showModePicker ? (
                  <div className="ml-[-4px] flex flex-wrap items-center gap-2.5">
                    {crawlTab === 'category' ? (
                      <TabBar
                        value={categoryMode}
                        compact
                        onChange={(value) => {
                          const parsed = parseRequestedCategoryMode(value);
                          if (parsed) {
                            dispatchRoute({ type: 'setCategoryMode', mode: parsed });
                          }
                        }}
                        options={[
                          { value: 'single', label: 'Single' },
                          { value: 'sitemap', label: 'Sitemap' },
                          { value: 'bulk', label: 'Bulk' },
                        ]}
                      />
                    ) : (
                      <TabBar
                        value={pdpMode}
                        compact
                        onChange={(value) => {
                          const parsed = parseRequestedPdpMode(value);
                          if (parsed) {
                            dispatchRoute({ type: 'setPdpMode', mode: parsed });
                          }
                        }}
                        options={[
                          { value: 'single', label: 'Single' },
                          { value: 'batch', label: 'Batch' },
                          { value: 'csv', label: 'CSV Upload' },
                        ]}
                      />
                    )}
                  </div>
                ) : null}
              </div>
              <CrawlActionButtons
                canSubmit={canSubmit}
                canSubmitDesign={canSubmitDesign}
                designSubmitting={designSubmitting}
                isSubmitting={isSubmitting}
                onDesignCrawl={() => void startDesignCrawl()}
              />
            </div>

            {(crawlTab === 'category' && categoryMode === 'bulk') ||
            (crawlTab === 'pdp' && pdpMode === 'batch') ? (
              <label className="grid gap-2">
                <span className="type-control font-medium">URLs (one per line)</span>
                <div className="relative">
                  <Textarea
                    value={bulkUrls}
                    onChange={(event) => setValue('bulkUrls', event.target.value)}
                    placeholder={'https://example.com/page-1\nhttps://example.com/page-2'}
                    className="min-h-[420px] font-mono"
                    aria-label="Bulk URLs input"
                  />
                  {bulkUrls.trim() ? (
                    <div className="bg-background/80 text-foreground type-caption absolute right-2 bottom-2 rounded-sm px-2 py-1 backdrop-blur-sm">
                      {parseLines(bulkUrls).length} URLs
                    </div>
                  ) : null}
                </div>
              </label>
            ) : crawlTab === 'pdp' && pdpMode === 'csv' ? (
              <CsvFileField file={csvFile} onChange={localDispatch.setCsvFile} />
            ) : crawlTab === 'category' && activeMode === 'sitemap' ? (
              <SitemapConfigFields
                domain={sitemapDomain}
                filterKeyword={sitemapFilterKeyword}
                maxUrls={sitemapMaxUrls}
                onDomainChange={localDispatch.setSitemapDomain}
                onFilterKeywordChange={localDispatch.setSitemapFilterKeyword}
                onMaxUrlsChange={localDispatch.setSitemapMaxUrls}
              />
            ) : (
              <TargetUrlField
                value={targetUrl}
                onChange={(value) => setValue('targetUrl', value)}
                placeholder={
                  crawlTab === 'category' ? 'https://example.com/list' : 'https://example.com/page'
                }
              />
            )}

            {savedProfileMessage ? (
              <div className="border-subtle-panel-border bg-subtle-panel text-secondary type-body rounded-md border px-3 py-2 leading-relaxed">
                {savedProfileMessage}
              </div>
            ) : null}

            <AdditionalFieldInput
              value={additionalDraft}
              fields={additionalFields}
              onChange={localDispatch.setAdditionalDraft}
              onCommit={(value) =>
                localDispatch.setAdditionalFields((current) =>
                  uniqueRequestedFields([...current, value]),
                )
              }
              onRemove={(value) =>
                localDispatch.setAdditionalFields((current) =>
                  current.filter((field) => field !== value),
                )
              }
            />
          </div>
        </Card>

        <div className="h-full xl:self-stretch">
          <div className="h-full xl:sticky xl:top-[68px]">
            <Card className="section-card h-full overflow-hidden p-0">
              <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
                <span className="type-heading-3">Crawl Settings</span>
                <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
                  {studioMode === 'advanced' ? 'Advanced' : 'Quick'}
                </Badge>
              </header>
              <div className="page-stack px-6 pt-4 pb-6">
                <div className={RUN_SETUP_ROW_CLASS}>
                  <div className={RUN_SETUP_LABEL_CLASS}>
                    <Globe className="text-accent size-4 shrink-0" />
                    <div className="type-body-sm text-foreground font-semibold">Domain</div>
                  </div>
                  <Dropdown<CrawlDomain>
                    ariaLabel="Domain"
                    value={crawlDomain}
                    className={RUN_SETUP_CONTROL_CLASS}
                    onChange={(value) => {
                      if (DOMAIN_OPTIONS.some((option) => option.value === value)) {
                        dispatchRoute({ type: 'setDomain', domain: value });
                      }
                    }}
                    options={DOMAIN_OPTIONS}
                  />
                </div>
                <div className={RUN_SETUP_ROW_CLASS}>
                  <div className={RUN_SETUP_LABEL_CLASS}>
                    <SlidersHorizontal className="text-accent size-4 shrink-0" />
                    <div className="flex items-center gap-1.5">
                      <div className="type-body-sm text-foreground font-semibold">Mode</div>
                      <Tooltip content="Advanced Mode exposes the full fetch, locality, diagnostics, and selector controls.">
                        <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
                      </Tooltip>
                    </div>
                  </div>
                  <TabBar
                    value={studioMode}
                    compact
                    className={RUN_SETUP_CONTROL_CLASS}
                    onChange={(value) => {
                      if (value === 'quick' || value === 'advanced') {
                        localDispatch.setStudioMode(value);
                      }
                    }}
                    options={[
                      { value: 'quick', label: 'Quick' },
                      { value: 'advanced', label: 'Advanced' },
                    ]}
                  />
                </div>

                <div className="flex h-[var(--control-height)] items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="text-accent size-4 shrink-0" />
                    <span className="type-body-sm text-foreground font-semibold">
                      LLM Processing
                    </span>
                    <Tooltip content="Per-run enrichment only. This does not overwrite saved domain defaults.">
                      <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
                    </Tooltip>
                  </div>
                  <Toggle
                    checked={smartExtraction}
                    onChange={localDispatch.setSmartExtraction}
                    ariaLabel="LLM Processing"
                  />
                </div>

                <div className="border-border border-t pt-4">
                  <div className="flex h-[var(--control-height)] items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Globe className="text-accent size-4 shrink-0" />
                      <span className="type-body-sm text-foreground font-semibold">Proxy List</span>
                      <Tooltip content={'Example:\nhttp://host:port\nhttp://user:pass@host:port'}>
                        <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
                      </Tooltip>
                    </div>
                    <Toggle
                      checked={proxyEnabled}
                      onChange={localDispatch.setProxyEnabled}
                      ariaLabel="Proxy List enabled"
                    />
                  </div>
                </div>

                {proxyEnabled ? (
                  <div className="ml-8 flex flex-col gap-4">
                    <div className="type-body-sm text-foreground font-semibold">Proxy URLs</div>
                    <Textarea
                      value={proxyInput}
                      onChange={(event) => {
                        setValue('proxyInput', event.target.value);
                      }}
                      placeholder={'http://host:port\nhttp://user:pass@host:port'}
                      className="min-h-[104px] font-mono leading-relaxed"
                      aria-label="Proxy pool input"
                    />
                  </div>
                ) : null}

                {singleUrlMode && savedProfileLoaded ? (
                  <div className="text-secondary type-body leading-relaxed">
                    Saved domain profile active:{' '}
                    <span className="type-label-mono text-foreground">{savedProfileDomain}</span> ·{' '}
                    {surfaceLabel(effectiveSurface)}
                  </div>
                ) : null}
              </div>
            </Card>
          </div>
        </div>

        {studioMode === 'advanced' ? (
          <Card className="section-card overflow-hidden p-0 xl:col-span-2">
            <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
              <span className="type-heading-3">Field Configuration</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="quiet"
                  type="button"
                  size="sm"
                  onClick={() => void generateFieldSelectors()}
                  disabled={generatingSelectors}
                >
                  <Sparkles className="size-3" />
                  {generatingSelectors ? 'Generating...' : 'Generate'}
                </Button>
                <Button variant="quiet" type="button" size="sm" onClick={addManualField}>
                  <Plus className="size-3" />
                  New Field
                </Button>
                <Button
                  variant="action"
                  type="button"
                  size="sm"
                  onClick={() => void saveToDomainMemory()}
                  disabled={
                    savingDomainMemory ||
                    !fieldRows.some(
                      (row) =>
                        normalizeField(row.fieldName) &&
                        (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim()),
                    )
                  }
                >
                  {savingDomainMemory ? 'Saving...' : 'Save to Memory'}
                </Button>
              </div>
            </header>
            <div className="space-y-4 px-6 pt-6 pb-6">
              {fieldConfigMessage ? (
                <p className="text-success type-body leading-relaxed">{fieldConfigMessage}</p>
              ) : null}
              {fieldConfigError ? <InlineAlert message={fieldConfigError} /> : null}
              <div className="flex flex-col gap-2">
                {fieldRows.length ? (
                  <>
                    <FieldEditorHeader />
                    {fieldRows.map((row) => (
                      <ManualFieldEditor
                        key={row.id}
                        row={row}
                        showLabels={false}
                        message={fieldRowMessages[row.id]?.message}
                        messageTone={fieldRowMessages[row.id]?.tone}
                        onChange={(patch) => {
                          setFieldRows((current) =>
                            current.map((entry) =>
                              entry.id === row.id ? { ...entry, ...patch } : entry,
                            ),
                          );
                          localDispatch.setFieldRowMessages((current) => {
                            if (!current[row.id]) {
                              return current;
                            }
                            const next = { ...current };
                            delete next[row.id];
                            return next;
                          });
                        }}
                        onDelete={() => {
                          setFieldRows((current) => current.filter((entry) => entry.id !== row.id));
                          localDispatch.setFieldRowMessages((current) => {
                            if (!current[row.id]) {
                              return current;
                            }
                            const next = { ...current };
                            delete next[row.id];
                            return next;
                          });
                        }}
                        onTest={() => void testFieldRow(row)}
                        testing={activeFieldTestId === row.id}
                        testDisabled={
                          !targetUrl.trim() ||
                          (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim())
                        }
                      />
                    ))}
                  </>
                ) : (
                  <div className="surface-muted text-secondary type-body rounded-md border-dashed px-4 py-6 leading-relaxed">
                    No selector rows yet.
                  </div>
                )}
              </div>
            </div>
          </Card>
        ) : null}

        {configError ? (
          <div className="xl:col-span-2">
            <InlineAlert message={configError} />
          </div>
        ) : null}

        {studioMode === 'advanced' ? (
          <Card className="section-card overflow-visible p-0 xl:col-span-2">
            <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
              <span className="type-heading-3 flex items-center gap-1.5">
                <SlidersHorizontal className="size-3.5" /> Advanced Settings
              </span>
              <Tooltip content="Fine-tune fetch, limits, locality, and diagnostics for this exploratory run.">
                <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
              </Tooltip>
            </header>
            <div className="grid gap-0 p-6 xl:grid-cols-3 xl:divide-x xl:divide-[var(--border)]">
              <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:pr-6')}>
                <div className={ADVANCED_SECTION_TITLE_CLASS}>
                  <h3>Execution</h3>
                  <Tooltip content="Control how the crawler fetches, renders, and traverses the target.">
                    <Info className="text-muted hover:text-secondary size-3 cursor-help transition-colors" />
                  </Tooltip>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Fetch Mode</div>
                    <Dropdown<FetchMode>
                      ariaLabel="Fetch mode"
                      value={runProfile.fetch_profile.fetch_mode}
                      onChange={(next) => {
                        if (FETCH_MODE_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            fetch_profile: {
                              ...current.fetch_profile,
                              fetch_mode: next,
                            },
                            acquisition_contract:
                              next === 'browser_only'
                                ? {
                                    ...current.acquisition_contract,
                                    prefer_browser: true,
                                    prefer_curl_handoff: false,
                                    handoff_cookie_engine: 'auto',
                                  }
                                : current.acquisition_contract,
                          }));
                        }
                      }}
                      options={[
                        { value: 'auto', label: 'Auto' },
                        { value: 'http_only', label: 'HTTP Only' },
                        { value: 'browser_only', label: 'Browser Only' },
                        { value: 'http_then_browser', label: 'HTTP Then Browser' },
                      ]}
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Browser Engine</div>
                    <Dropdown<BrowserEngine>
                      ariaLabel="Browser engine"
                      value={runProfile.acquisition_contract.preferred_browser_engine}
                      onChange={(next) => {
                        if (BROWSER_ENGINE_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            acquisition_contract: {
                              ...current.acquisition_contract,
                              preferred_browser_engine: next,
                              prefer_browser: next === 'auto' ? false : true,
                              prefer_curl_handoff: false,
                              handoff_cookie_engine: next === 'auto' ? 'auto' : next,
                            },
                          }));
                        }
                      }}
                      options={[
                        { value: 'auto', label: 'Auto' },
                        { value: 'patchright', label: 'Patchright' },
                        { value: 'real_chrome', label: 'Real Chrome' },
                      ]}
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Extraction</div>
                    <Dropdown<ExtractionSource>
                      ariaLabel="Extraction source"
                      value={runProfile.fetch_profile.extraction_source}
                      onChange={(next) => {
                        if (EXTRACTION_SOURCE_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            fetch_profile: {
                              ...current.fetch_profile,
                              extraction_source: next,
                            },
                          }));
                        }
                      }}
                      options={[
                        { value: 'raw_html', label: 'Raw HTML' },
                        { value: 'rendered_dom', label: 'Rendered DOM' },
                        { value: 'rendered_dom_visual', label: 'Rendered + Visual' },
                        { value: 'network_payload_first', label: 'Network Payload First' },
                      ]}
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">JS Mode</div>
                    <Dropdown<JsMode>
                      ariaLabel="JavaScript mode"
                      value={runProfile.fetch_profile.js_mode}
                      onChange={(next) => {
                        if (JS_MODE_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            fetch_profile: {
                              ...current.fetch_profile,
                              js_mode: next,
                            },
                          }));
                        }
                      }}
                      options={[
                        { value: 'auto', label: 'Auto' },
                        { value: 'enabled', label: 'Enabled' },
                        { value: 'disabled', label: 'Disabled' },
                      ]}
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Traversal</div>
                    <Dropdown<TraversalDropdownValue>
                      ariaLabel="Traversal mode"
                      value={runProfile.fetch_profile.traversal_mode ?? 'off'}
                      onChange={(next) => {
                        if (next === 'off') {
                          markProfileDirty((current) => ({
                            ...current,
                            fetch_profile: {
                              ...current.fetch_profile,
                              traversal_mode: null,
                            },
                          }));
                          return;
                        }
                        if (TRAVERSAL_MODE_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            fetch_profile: {
                              ...current.fetch_profile,
                              traversal_mode: next,
                            },
                          }));
                        }
                      }}
                      options={[
                        { value: 'off', label: 'Off' },
                        { value: 'paginate', label: 'Paginate' },
                        { value: 'scroll', label: 'Scroll' },
                        { value: 'load_more', label: 'Load More' },
                        { value: 'view_all', label: 'View All' },
                      ]}
                    />
                  </div>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <SettingSection
                    label="Include iframes"
                    description="Allow iframe content to participate in extraction and selector recovery."
                    checked={runProfile.fetch_profile.include_iframes}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        fetch_profile: {
                          ...current.fetch_profile,
                          include_iframes: next,
                        },
                      }))
                    }
                  />
                  <SettingSection
                    label="Respect robots.txt"
                    description="Skip disallowed paths and honor crawl-delay."
                    checked={respectRobotsTxt}
                    onChange={localDispatch.setRespectRobotsTxt}
                  />
                </div>
              </section>
              <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:px-6')}>
                <div className={ADVANCED_SECTION_TITLE_CLASS}>
                  <h3>Limits &amp; Locales</h3>
                  <Tooltip content="Set repeat-run bounds and regional hints before dispatch.">
                    <Info className="text-muted hover:text-secondary size-3 cursor-help transition-colors" />
                  </Tooltip>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <SliderRow
                    label="Request Delay"
                    description="Wait time between requests to the same target."
                    value={String(runProfile.fetch_profile.request_delay_ms)}
                    min={CRAWL_LIMITS.MIN_REQUEST_DELAY_MS}
                    max={CRAWL_LIMITS.MAX_REQUEST_DELAY_MS}
                    step={100}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        fetch_profile: {
                          ...current.fetch_profile,
                          request_delay_ms: clampNumber(
                            next,
                            CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
                            CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
                            CRAWL_DEFAULTS.REQUEST_DELAY_MS,
                          ),
                        },
                      }))
                    }
                    onReset={() =>
                      markProfileDirty((current) => ({
                        ...current,
                        fetch_profile: {
                          ...current.fetch_profile,
                          request_delay_ms: CRAWL_DEFAULTS.REQUEST_DELAY_MS,
                        },
                      }))
                    }
                  />
                  <SliderRow
                    label="Max Records"
                    description="Target record count. The crawler stops after a page reaches this target; it does not trim extra rows from that page."
                    value={maxRecords}
                    min={CRAWL_LIMITS.MIN_RECORDS}
                    max={CRAWL_LIMITS.MAX_RECORDS}
                    step={10}
                    onChange={(value) => setValue('maxRecords', value)}
                    onReset={() => setValue('maxRecords', String(CRAWL_DEFAULTS.MAX_RECORDS))}
                  />
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="flex items-center gap-2">
                      <div className="type-body-sm text-foreground font-semibold">
                        Host Memory TTL
                      </div>
                      <Tooltip
                        content={`Blank uses default ${CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS}s. Lower TTL forgets host block and pacing memory sooner.`}
                      >
                        <Info className="text-muted hover:text-secondary size-3 cursor-help transition-colors" />
                      </Tooltip>
                    </div>
                    <Input
                      type="number"
                      min={CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS}
                      max={CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS}
                      placeholder={String(CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS)}
                      value={runProfile.fetch_profile.host_memory_ttl_seconds ?? ''}
                      onChange={(event) =>
                        markProfileDirty((current) => ({
                          ...current,
                          fetch_profile: {
                            ...current.fetch_profile,
                            host_memory_ttl_seconds: parseOptionalClampedNumber(
                              event.target.value,
                              CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS,
                              CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS,
                            ),
                          },
                        }))
                      }
                      aria-label="Host memory TTL seconds"
                    />
                  </div>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Geo Country</div>
                    <Input
                      value={runProfile.locality_profile.geo_country}
                      onChange={(event) =>
                        markProfileDirty((current) => ({
                          ...current,
                          locality_profile: {
                            ...current.locality_profile,
                            geo_country: event.target.value.trim() || 'auto',
                          },
                        }))
                      }
                      aria-label="Geo country"
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Language Hint</div>
                    <Input
                      value={runProfile.locality_profile.language_hint ?? ''}
                      onChange={(event) =>
                        markProfileDirty((current) => ({
                          ...current,
                          locality_profile: {
                            ...current.locality_profile,
                            language_hint: event.target.value.trim() || null,
                          },
                        }))
                      }
                      aria-label="Language hint"
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Currency Hint</div>
                    <Input
                      value={runProfile.locality_profile.currency_hint ?? ''}
                      onChange={(event) =>
                        markProfileDirty((current) => ({
                          ...current,
                          locality_profile: {
                            ...current.locality_profile,
                            currency_hint: event.target.value.trim() || null,
                          },
                        }))
                      }
                      aria-label="Currency hint"
                    />
                  </div>
                </div>
              </section>
              <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:pl-6')}>
                <div className={ADVANCED_SECTION_TITLE_CLASS}>
                  <h3>Output &amp; Diagnostics</h3>
                  <Tooltip content="Choose what evidence and artifacts stay attached to this run.">
                    <Info className="text-muted hover:text-secondary size-3 cursor-help transition-colors" />
                  </Tooltip>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">Diagnostics</div>
                    <Dropdown<DiagnosticsPreset>
                      ariaLabel="Diagnostics preset"
                      value={diagnosticsPreset}
                      onChange={(next) => {
                        if (next === 'lean' || next === 'standard' || next === 'deep_debug') {
                          markProfileDirty((current) => applyDiagnosticsPreset(current, next));
                        }
                      }}
                      options={[
                        { value: 'lean', label: 'Lean' },
                        { value: 'standard', label: 'Standard' },
                        { value: 'deep_debug', label: 'Deep Debug' },
                      ]}
                    />
                  </div>
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="type-body-sm text-foreground font-semibold">
                      Network Capture
                    </div>
                    <Dropdown<CaptureNetworkMode>
                      ariaLabel="Network capture"
                      value={runProfile.diagnostics_profile.capture_network}
                      onChange={(next) => {
                        if (CAPTURE_NETWORK_OPTIONS.has(next)) {
                          markProfileDirty((current) => ({
                            ...current,
                            diagnostics_profile: {
                              ...current.diagnostics_profile,
                              capture_network: next,
                            },
                          }));
                        }
                      }}
                      options={[
                        { value: 'off', label: 'Off' },
                        { value: 'matched_only', label: 'Matched Only' },
                        { value: 'all_small_json', label: 'All Small JSON' },
                      ]}
                    />
                  </div>
                </div>
                <div className={ADVANCED_SUBSECTION_CLASS}>
                  <SettingSection
                    label="Capture HTML"
                    description="Persist the page HTML artifact for this run."
                    checked={runProfile.diagnostics_profile.capture_html}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        diagnostics_profile: {
                          ...current.diagnostics_profile,
                          capture_html: next,
                        },
                      }))
                    }
                  />
                  <SettingSection
                    label="Capture Screenshot"
                    description="Store browser screenshots when available."
                    checked={runProfile.diagnostics_profile.capture_screenshot}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        diagnostics_profile: {
                          ...current.diagnostics_profile,
                          capture_screenshot: next,
                        },
                      }))
                    }
                  />
                  <SettingSection
                    label="Capture Response Headers"
                    description="Preserve response-header diagnostics."
                    checked={runProfile.diagnostics_profile.capture_response_headers}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        diagnostics_profile: {
                          ...current.diagnostics_profile,
                          capture_response_headers: next,
                        },
                      }))
                    }
                  />
                  <SettingSection
                    label="Capture Browser Diagnostics"
                    description="Keep detailed browser-attempt diagnostics for debugging."
                    checked={runProfile.diagnostics_profile.capture_browser_diagnostics}
                    onChange={(next) =>
                      markProfileDirty((current) => ({
                        ...current,
                        diagnostics_profile: {
                          ...current.diagnostics_profile,
                          capture_browser_diagnostics: next,
                        },
                      }))
                    }
                  />
                </div>
              </section>
            </div>
          </Card>
        ) : null}
      </form>
    </div>
  );
}
