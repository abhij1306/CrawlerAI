'use client';

import { Check, Globe, Info, Plus, Shield, SlidersHorizontal, Sparkles } from 'lucide-react';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { FormEvent, startTransition, useEffect, useMemo, useRef, useState } from 'react';

import { cn } from '../../lib/utils';
import { InlineAlert, PageHeader, SectionHeader, TabBar } from '../ui/patterns';
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
  type CategoryMode,
  type CrawlTab,
  deriveSurface,
  FieldEditorHeader,
  type FieldRow,
  type FieldRowMessageTone,
  ManualFieldEditor,
  parseRequestedCategoryMode,
  parseRequestedCrawlTab,
  parseLines,
  parseRequestedPdpMode,
  type PdpMode,
  SettingSection,
  SliderRow,
  validateAdditionalFieldName,
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
  type StudioMode,
  type TraversalDropdownValue,
} from './crawl-config-logic';
import { DOMAIN_OPTIONS, DOMAIN_TABS } from './domain-surface-config';

type CrawlConfigScreenProps = {
  requestedTab: CrawlTab | null;
  requestedCategoryMode: CategoryMode | null;
  requestedPdpMode: PdpMode | null;
};

const RUN_SETUP_ROW_CLASS =
  'grid gap-2 md:grid-cols-[110px_minmax(0,1fr)] md:items-center md:gap-3';
const RUN_SETUP_CONTROL_CLASS = 'flex md:justify-self-end';
const RUN_SETUP_LABEL_CLASS = 'flex min-w-0 h-[var(--control-height)] items-center gap-3';
const RUN_SETUP_STACK_CLASS = 'flex flex-col gap-3';
const ADVANCED_CONTROL_ROW_CLASS =
  'grid gap-1.5 md:grid-cols-[140px_minmax(0,1fr)] md:items-center md:gap-3';
const ADVANCED_COLUMN_CLASS = 'flex flex-col gap-4';
const ADVANCED_SUBSECTION_CLASS = 'flex flex-col gap-2.5';
const ADVANCED_SECTION_TITLE_CLASS = 'flex items-center gap-2 type-caption text-secondary';

export function CrawlConfigScreen({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>) {
  const router = useRouter();
  const [crawlTab, setCrawlTab] = useState<CrawlTab>(() => requestedTab ?? 'category');
  const [crawlDomain, setCrawlDomain] = useState<CrawlDomain>('commerce');
  const [categoryMode, setCategoryMode] = useState<CategoryMode>(
    () => requestedCategoryMode ?? 'single',
  );
  const [pdpMode, setPdpMode] = useState<PdpMode>(() => requestedPdpMode ?? 'single');
  const [targetUrl, setTargetUrl] = useState('');
  const [bulkUrls, setBulkUrls] = useState('');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [smartExtraction, setSmartExtraction] = useState(false);
  const [studioMode, setStudioMode] = useState<StudioMode>('quick');
  const [runProfile, setRunProfile] = useState<DomainRunProfile>(() => defaultRunProfile());
  const [maxRecords, setMaxRecords] = useState(String(CRAWL_DEFAULTS.MAX_RECORDS));
  const [respectRobotsTxt, setRespectRobotsTxt] = useState<boolean>(
    CRAWL_DEFAULTS.RESPECT_ROBOTS_TXT,
  );
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyInput, setProxyInput] = useState('');
  const [savedProfileDomain, setSavedProfileDomain] = useState('');
  const [savedProfileLoaded, setSavedProfileLoaded] = useState(false);
  const [savedProfileMessage, setSavedProfileMessage] = useState('');
  const [additionalDraft, setAdditionalDraft] = useState('');
  const [additionalFields, setAdditionalFields] = useState<string[]>([]);
  const [fieldRows, setFieldRows] = useState<FieldRow[]>([]);
  const [generatingSelectors, setGeneratingSelectors] = useState(false);
  const [savingDomainMemory, setSavingDomainMemory] = useState(false);
  const [fieldConfigMessage, setFieldConfigMessage] = useState('');
  const [fieldConfigError, setFieldConfigError] = useState('');
  const [fieldRowMessages, setFieldRowMessages] = useState<
    Record<string, { tone: FieldRowMessageTone; message: string }>
  >({});
  const [activeFieldTestId, setActiveFieldTestId] = useState<string | null>(null);
  const [configError, setConfigError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const bulkPrefillRouteSyncGuardRef = useRef(false);
  const profileLookupRequestRef = useRef(0);
  const domainMemoryLookupRequestRef = useRef(0);
  const profileLookupTargetUrlRef = useRef('');
  const profileDirtyRef = useRef(false);
  const lastProfileKeyRef = useRef('');
  const lastDomainMemoryKeyRef = useRef('');

  const effectivePdpMode = crawlDomain === 'forum_thread' ? 'single' : pdpMode;
  const activeMode = crawlTab === 'category' ? categoryMode : effectivePdpMode;
  const surface = deriveSurface(crawlDomain, crawlTab);
  const domainTabs = DOMAIN_TABS[crawlDomain];
  const activeTabLabel =
    domainTabs.find((tab) => tab.value === crawlTab)?.label ?? surfaceLabel(surface);
  const showSurfaceTabs = domainTabs.length > 1;
  const showModePicker = crawlDomain !== 'forum_thread';
  const singleUrlMode = isSingleUrlMode(crawlTab, activeMode);
  const normalizedTargetDomain = normalizeHttpLookupDomain(targetUrl);
  const profileLookupKey =
    singleUrlMode && normalizedTargetDomain && surface
      ? `${normalizedTargetDomain}|${surface}`
      : '';
  const domainMemoryLookupKey =
    singleUrlMode && normalizedTargetDomain && surface
      ? `${normalizedTargetDomain}|${surface}`
      : '';
  const diagnosticsPreset = diagnosticsPresetForProfile(runProfile);

  useEffect(() => {
    profileLookupTargetUrlRef.current = profileLookupKey ? targetUrl.trim() : '';
  }, [profileLookupKey, targetUrl]);

  useEffect(() => {
    if (bulkPrefillRouteSyncGuardRef.current) {
      if (requestedTab === 'pdp') {
        bulkPrefillRouteSyncGuardRef.current = false;
      } else {
        return;
      }
    }
    const nextTab = requestedTab ?? 'category';
    const nextCategoryMode = requestedCategoryMode ?? 'single';
    const nextPdpMode = requestedPdpMode ?? 'single';
    setCrawlTab((current) => (current === nextTab ? current : nextTab));
    setCategoryMode((current) => (current === nextCategoryMode ? current : nextCategoryMode));
    setPdpMode((current) => (current === nextPdpMode ? current : nextPdpMode));
  }, [requestedCategoryMode, requestedPdpMode, requestedTab]);

  useEffect(() => {
    if (domainTabs.some((tab) => tab.value === crawlTab)) {
      return;
    }
    setCrawlTab(domainTabs[0]?.value ?? 'category');
  }, [crawlDomain, crawlTab, domainTabs]);

  useEffect(() => {
    if (crawlDomain !== 'forum_thread') return;
    setPdpMode((current) => (current === 'single' ? current : 'single'));
  }, [crawlDomain]);

  useEffect(() => {
    const routeMode = crawlTab === 'category' ? requestedCategoryMode : requestedPdpMode;
    if (requestedTab === crawlTab && routeMode === activeMode) {
      return;
    }
    const nextUrl = `/crawl?module=${crawlTab}&mode=${activeMode}`;
    if (typeof window !== 'undefined') {
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (currentUrl !== nextUrl) {
        window.history.replaceState(null, '', nextUrl);
      }
    }
  }, [activeMode, crawlTab, requestedCategoryMode, requestedPdpMode, requestedTab]);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as {
        domain?: CrawlDomain;
        urls: string[];
        additional_fields?: string[];
      };
      if (Array.isArray(parsed.urls) && parsed.urls.length) {
        bulkPrefillRouteSyncGuardRef.current = true;
        setCrawlTab('pdp');
        setPdpMode('batch');
        const parsedDomain = parsed.domain;
        if (parsedDomain && DOMAIN_OPTIONS.some((option) => option.value === parsedDomain)) {
          setCrawlDomain(parsedDomain);
        }
        setBulkUrls(parsed.urls.join('\n'));
        if (Array.isArray(parsed.additional_fields)) {
          setAdditionalFields(uniqueRequestedFields(parsed.additional_fields));
        }
        router.replace('/crawl?module=pdp&mode=batch' as Route);
      }
    } catch {
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, [router]);

  useEffect(() => {
    if (lastProfileKeyRef.current !== profileLookupKey) {
      profileDirtyRef.current = false;
      lastProfileKeyRef.current = profileLookupKey;
      if (!profileLookupKey) {
        setSavedProfileLoaded(false);
        setSavedProfileDomain('');
        setSavedProfileMessage('');
        setRunProfile(defaultRunProfile());
        return;
      }
    }
    if (!profileLookupKey) {
      return;
    }
    const requestId = profileLookupRequestRef.current + 1;
    profileLookupRequestRef.current = requestId;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.getDomainRunProfile({
          url: profileLookupTargetUrlRef.current,
          surface,
        });
        if (profileLookupRequestRef.current !== requestId) {
          return;
        }
        const savedProfile = response.saved_run_profile;
        setSavedProfileDomain(response.domain);
        if (savedProfile && !profileDirtyRef.current) {
          setRunProfile(cloneRunProfile(savedProfile));
          setSavedProfileLoaded(true);
          setSavedProfileMessage(
            `Saved domain profile applied for ${response.domain} on ${surfaceLabel(response.surface)}. Explicit edits below override it for this run.`,
          );
        } else {
          setSavedProfileLoaded(Boolean(savedProfile));
          setSavedProfileMessage(
            savedProfile
              ? `Saved domain profile found for ${response.domain}. Your current edits are preserved for this run.`
              : '',
          );
          if (!savedProfile && !profileDirtyRef.current) {
            setRunProfile(defaultRunProfile());
          }
        }
      } catch {
        if (profileLookupRequestRef.current === requestId) {
          setSavedProfileLoaded(false);
          setSavedProfileDomain('');
          setSavedProfileMessage('');
        }
      }
    }, UI_DELAYS.DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [profileLookupKey, surface]);

  useEffect(() => {
    if (lastDomainMemoryKeyRef.current !== domainMemoryLookupKey) {
      lastDomainMemoryKeyRef.current = domainMemoryLookupKey;
      setFieldConfigError('');
      setFieldConfigMessage('');
      setFieldRowMessages({});
      setFieldRows((current) => stripDomainMemoryFieldRows(current));
      if (!domainMemoryLookupKey) {
        return;
      }
    }
    if (!domainMemoryLookupKey) {
      return;
    }
    const requestId = domainMemoryLookupRequestRef.current + 1;
    domainMemoryLookupRequestRef.current = requestId;
    const lookupDomain = normalizedTargetDomain;
    const timer = window.setTimeout(async () => {
      setFieldConfigError('');
      try {
        const records = await api.listSelectors({ domain: lookupDomain });
        if (domainMemoryLookupRequestRef.current !== requestId) {
          return;
        }
        const matchingRecords = selectRelevantSelectorRecords(records, surface);
        if (!matchingRecords.length) {
          setFieldRows((current) => stripDomainMemoryFieldRows(current));
          return;
        }
        const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
        setFieldRows((current) =>
          mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows),
        );
        setFieldRowMessages({});
      } catch (error) {
        if (domainMemoryLookupRequestRef.current === requestId) {
          setFieldConfigError(
            error instanceof Error ? error.message : 'Unable to load domain memory.',
          );
        }
      }
    }, UI_DELAYS.DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [domainMemoryLookupKey, normalizedTargetDomain, surface]);

  const config = useMemo<CrawlConfig>(
    () => ({
      module: crawlTab,
      domain: crawlDomain,
      mode: crawlTab === 'category' ? categoryMode : effectivePdpMode,
      target_url: targetUrl,
      bulk_urls: bulkUrls,
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
      categoryMode,
      crawlDomain,
      crawlTab,
      csvFile,
      maxRecords,
      effectivePdpMode,
      proxyEnabled,
      proxyInput,
      respectRobotsTxt,
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
    setFieldConfigError('');
    try {
      const records = await api.listSelectors({ domain });
      if (domainMemoryLookupRequestRef.current !== requestId) {
        return;
      }
      const matchingRecords = selectRelevantSelectorRecords(records, surface);
      if (!matchingRecords.length) {
        setFieldConfigMessage('No saved domain memory found for this URL.');
        setFieldRows((current) => stripDomainMemoryFieldRows(current));
        return;
      }
      const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
      setFieldRows((current) => mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows));
      setFieldRowMessages({});
      setFieldConfigMessage(
        `Loaded ${matchingRecords.length} saved selector${matchingRecords.length === 1 ? '' : 's'} from domain memory.`,
      );
    } catch (error) {
      if (domainMemoryLookupRequestRef.current === requestId) {
        setFieldConfigError(
          error instanceof Error ? error.message : 'Unable to load domain memory.',
        );
      }
    }
  }

  function markProfileDirty(updater: (current: DomainRunProfile) => DomainRunProfile) {
    profileDirtyRef.current = true;
    setRunProfile((current) => cloneRunProfile(updater(current)));
  }

  async function startCrawl(event: FormEvent) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }
    setConfigError('');
    setIsSubmitting(true);
    try {
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
      setConfigError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  function addManualField() {
    setFieldRows((current) => [
      ...current,
      {
        id: `${Date.now()}-${current.length}`,
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
      setFieldConfigError('Enter a target URL before generating selectors.');
      return;
    }
    const expectedColumns = selectorGenerationFields(surface, fieldRows, additionalFields);
    if (!expectedColumns.length) {
      setFieldConfigError(
        'Add at least one field or additional field before generating selectors.',
      );
      return;
    }
    setGeneratingSelectors(true);
    setFieldConfigError('');
    try {
      const response = await api.suggestSelectors({
        url: target,
        expected_columns: expectedColumns,
        surface,
      });
      const incomingRows = expectedColumns.map((fieldName) =>
        buildFieldRowFromSuggestion(
          fieldName,
          response.suggestions[normalizeField(fieldName)]?.[0],
        ),
      );
      setFieldRows((current) => mergeFieldRows(current, incomingRows));
      setFieldRowMessages({});
      setFieldConfigMessage(
        `Generated selector suggestions for ${expectedColumns.length} field${expectedColumns.length === 1 ? '' : 's'}.`,
      );
    } catch (error) {
      setFieldConfigError(error instanceof Error ? error.message : 'Unable to generate selectors.');
    } finally {
      setGeneratingSelectors(false);
    }
  }

  async function testFieldRow(row: FieldRow) {
    const target = targetUrl.trim();
    if (!target) {
      setFieldRowMessages((current) => ({
        ...current,
        [row.id]: { tone: 'warning', message: 'Enter a target URL before testing selectors.' },
      }));
      return;
    }
    if (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim()) {
      setFieldRowMessages((current) => ({
        ...current,
        [row.id]: {
          tone: 'warning',
          message: 'Add a CSS selector, XPath, or regex before testing.',
        },
      }));
      return;
    }
    setActiveFieldTestId(row.id);
    try {
      const response = await api.testSelector({
        url: target,
        css_selector: row.cssSelector.trim() || undefined,
        xpath: row.xpath.trim() || undefined,
        regex: row.regex.trim() || undefined,
      });
      setFieldRowMessages((current) => ({
        ...current,
        [row.id]: {
          tone: response.count > 0 ? 'success' : 'warning',
          message:
            response.count > 0
              ? `Matched ${response.count} result${response.count === 1 ? '' : 's'}${response.matched_value ? `: ${response.matched_value}` : '.'}`
              : 'No matches.',
        },
      }));
    } catch (error) {
      setFieldRowMessages((current) => ({
        ...current,
        [row.id]: {
          tone: 'danger',
          message: error instanceof Error ? error.message : 'Selector test failed.',
        },
      }));
    } finally {
      setActiveFieldTestId(null);
    }
  }

  async function saveToDomainMemory() {
    const target = targetUrl.trim();
    const domain = getNormalizedDomain(target);
    if (!target || !domain) {
      setFieldConfigError('Enter a target URL before saving domain memory.');
      return;
    }
    const dedupedRows = Array.from(
      new Map(
        fieldRows
          .filter(
            (row) =>
              normalizeField(row.fieldName) &&
              (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim()),
          )
          .map((row) => [normalizeField(row.fieldName), row] as const),
      ).values(),
    );
    if (!dedupedRows.length) {
      setFieldConfigError('Add at least one selector row before saving domain memory.');
      return;
    }
    setSavingDomainMemory(true);
    setFieldConfigError('');
    try {
      const existingRecords = selectRelevantSelectorRecords(
        await api.listSelectors({ domain }),
        surface,
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
            surface,
            ...payload,
          });
        }),
      );
      const failedCount = settled.filter((result) => result.status === 'rejected').length;
      const savedCount = settled.length - failedCount;
      if (failedCount) {
        setFieldConfigError(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'}, ${failedCount} failed.`,
        );
      } else {
        setFieldConfigMessage(
          `Saved ${savedCount} selector${savedCount === 1 ? '' : 's'} to domain memory.`,
        );
      }
      if (savedCount) {
        await loadDomainMemoryForUrl(target);
      }
    } catch (error) {
      setFieldConfigError(error instanceof Error ? error.message : 'Unable to save domain memory.');
    } finally {
      setSavingDomainMemory(false);
    }
  }

  const hasTarget =
    singleUrlMode || categoryMode === 'sitemap'
      ? targetUrl.trim().length > 0
      : bulkUrls.trim().length > 0 || csvFile !== null;
  const canSubmit = canPreview(config, fieldRows, { runProfile, studioMode }) && !isSubmitting;

  return (
    <div className="page-stack gap-4">
      <PageHeader
        title="Crawl Studio"
        description="Configure and launch crawls across product listings and detail pages."
      />

      <form
        className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_380px] xl:items-stretch"
        onSubmit={(event) => void startCrawl(event)}
      >
        <Card className="section-card overflow-hidden p-0">
          <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
            <span className="type-body-sm text-secondary font-medium">Target URL</span>
            <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
              {activeTabLabel}
            </Badge>
          </header>
          <div className="space-y-5 px-6 pt-6 pb-6">
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
              <div className="ml-[-4px] flex flex-wrap items-center gap-2.5">
                {showSurfaceTabs ? (
                  <TabBar
                    value={crawlTab}
                    onChange={(value) => {
                      const parsed = parseRequestedCrawlTab(value);
                      if (parsed) {
                        setCrawlTab(parsed);
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
                            setCategoryMode(parsed);
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
                            setPdpMode(parsed);
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
              <Button
                variant="accent"
                size="lg"
                type="submit"
                disabled={!canSubmit}
                className="min-w-[140px] justify-self-start lg:justify-self-end"
              >
                {isSubmitting ? (
                  <>
                    <span
                      className="inline-block size-1.5 animate-pulse rounded-full bg-current opacity-80"
                      aria-hidden="true"
                    />
                    Starting...
                  </>
                ) : (
                  'Start Crawl'
                )}
              </Button>
            </div>

            {(crawlTab === 'category' && categoryMode === 'bulk') ||
            (crawlTab === 'pdp' && pdpMode === 'batch') ? (
              <label className="grid gap-1.5">
                <span className="type-control crawl-control-label">URLs (one per line)</span>
                <div className="relative">
                  <Textarea
                    value={bulkUrls}
                    onChange={(event) => setBulkUrls(event.target.value)}
                    placeholder={'https://example.com/page-1\nhttps://example.com/page-2'}
                    className="min-h-[420px] font-mono"
                    aria-label="Bulk URLs input"
                  />
                  {bulkUrls.trim() ? (
                    <div className="bg-background/80 text-foreground type-caption absolute right-2 bottom-2 rounded-[var(--radius-sm)] px-2 py-1 backdrop-blur-sm">
                      {parseLines(bulkUrls).length} URLs
                    </div>
                  ) : null}
                </div>
              </label>
            ) : crawlTab === 'pdp' && pdpMode === 'csv' ? (
              <label className="grid gap-1.5">
                <span className="type-control crawl-control-label">CSV File</span>
                <div className="flex items-center gap-3">
                  <input
                    key="csv-file-input"
                    id="csv-file-input"
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                    className="sr-only"
                    aria-label="CSV file input"
                  />
                  <label
                    htmlFor="csv-file-input"
                    className="ui-on-accent-surface bg-accent hover:bg-accent-hover type-control cursor-pointer rounded-[var(--radius-md)] px-3 py-1.5 transition-colors"
                  >
                    Choose file
                  </label>
                  <span className="text-muted type-body">
                    {csvFile ? csvFile.name : 'No file chosen'}
                  </span>
                </div>
              </label>
            ) : (
              <label className="grid gap-1.5">
                <span className="type-control crawl-control-label">Target URL</span>
                <Input
                  key="target-url-input"
                  value={targetUrl}
                  onChange={(event) => setTargetUrl(event.target.value)}
                  className="font-mono"
                  placeholder={
                    crawlTab === 'category'
                      ? 'https://example.com/list'
                      : 'https://example.com/page'
                  }
                  aria-label="Target URL input"
                />
              </label>
            )}

            {savedProfileMessage ? (
              <div className="border-subtle-panel-border bg-subtle-panel text-secondary type-body rounded-[var(--radius-md)] border px-3 py-2 leading-[var(--leading-relaxed)]">
                {savedProfileMessage}
              </div>
            ) : null}

            <AdditionalFieldInput
              value={additionalDraft}
              fields={additionalFields}
              onChange={setAdditionalDraft}
              onCommit={(value) =>
                setAdditionalFields((current) => uniqueRequestedFields([...current, value]))
              }
              onRemove={(value) =>
                setAdditionalFields((current) => current.filter((field) => field !== value))
              }
            />
          </div>
        </Card>

        <div className="h-full xl:self-stretch">
          <div className="h-full xl:sticky xl:top-[68px]">
            <Card className="section-card h-full overflow-hidden p-0">
              <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
                <span className="type-body-sm text-secondary font-medium">Crawl Settings</span>
                <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
                  {studioMode === 'advanced' ? 'Advanced' : 'Quick'}
                </Badge>
              </header>
              <div className="page-stack px-6 pt-6 pb-6">
                <div className={RUN_SETUP_ROW_CLASS}>
                  <div className={RUN_SETUP_LABEL_CLASS}>
                    <Globe className="text-accent size-4 shrink-0" />
                    <div className="type-control crawl-control-label">Domain</div>
                  </div>
                  <Dropdown<CrawlDomain>
                    ariaLabel="Domain"
                    value={crawlDomain}
                    className={RUN_SETUP_CONTROL_CLASS}
                    onChange={(value) => {
                      if (DOMAIN_OPTIONS.some((option) => option.value === value)) {
                        setCrawlDomain(value);
                      }
                    }}
                    options={DOMAIN_OPTIONS}
                  />
                </div>

                <div className={RUN_SETUP_ROW_CLASS}>
                  <div className={RUN_SETUP_LABEL_CLASS}>
                    <SlidersHorizontal className="text-accent size-4 shrink-0" />
                    <div className="flex items-center gap-1.5">
                      <div className="type-control crawl-control-label">Mode</div>
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
                        setStudioMode(value);
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
                    <span className="type-control crawl-control-label">LLM Processing</span>
                    <Tooltip content="Per-run enrichment only. This does not overwrite saved domain defaults.">
                      <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
                    </Tooltip>
                  </div>
                  <Toggle
                    checked={smartExtraction}
                    onChange={setSmartExtraction}
                    ariaLabel="LLM Processing"
                  />
                </div>

                <div className="border-border border-t pt-4">
                  <div className="flex h-[var(--control-height)] items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Globe className="text-accent size-4 shrink-0" />
                      <span className="type-control crawl-control-label">Proxy List</span>
                      <Tooltip content={'Example:\nhttp://host:port\nhttp://user:pass@host:port'}>
                        <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
                      </Tooltip>
                    </div>
                    <Toggle
                      checked={proxyEnabled}
                      onChange={setProxyEnabled}
                      ariaLabel="Proxy List enabled"
                    />
                  </div>
                </div>

                {proxyEnabled ? (
                  <div className="ml-7 flex flex-col gap-3">
                    <div className="type-control crawl-control-label">
                      Proxy URLs
                    </div>
                    <Textarea
                      value={proxyInput}
                      onChange={(event) => {
                        setProxyInput(event.target.value);
                      }}
                      placeholder={'http://host:port\nhttp://user:pass@host:port'}
                      className="min-h-[104px] font-mono leading-[var(--leading-relaxed)]"
                      aria-label="Proxy pool input"
                    />
                  </div>
                ) : null}

                {singleUrlMode && savedProfileLoaded ? (
                  <div className="text-secondary type-body leading-[var(--leading-relaxed)]">
                    Saved domain profile active:{' '}
                    <span className="type-label-mono text-foreground">{savedProfileDomain}</span> Â·{' '}
                    {surfaceLabel(surface)}
                  </div>
                ) : null}
              </div>
            </Card>
          </div>
        </div>

        {studioMode === 'advanced' ? (
          <Card className="section-card overflow-hidden p-0 xl:col-span-2">
            <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
              <span className="type-body-sm text-secondary font-medium">Field Configuration</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  type="button"
                  size="sm"
                  onClick={() => void generateFieldSelectors()}
                  disabled={generatingSelectors}
                  className="rounded-lg"
                >
                  <Sparkles className="size-3" />
                  {generatingSelectors ? 'Generating...' : 'Generate'}
                </Button>
                <Button
                  variant="ghost"
                  type="button"
                  size="sm"
                  onClick={addManualField}
                  className="rounded-lg"
                >
                  <Plus className="size-3" />
                  New Field
                </Button>
                <Button
                  variant="accent"
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
                  className="rounded-[var(--radius-md)]"
                >
                  {savingDomainMemory ? 'Saving...' : 'Save to Memory'}
                </Button>
              </div>
            </header>
            <div className="space-y-4 px-6 pt-6 pb-6">
              {fieldConfigMessage ? (
                <p className="text-success type-body leading-[var(--leading-relaxed)]">
                  {fieldConfigMessage}
                </p>
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
                          setFieldRowMessages((current) => {
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
                          setFieldRowMessages((current) => {
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
                  <div className="surface-muted text-secondary type-body rounded-[var(--radius-md)] border-dashed px-4 py-6 leading-[var(--leading-relaxed)]">
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
              <span className="type-body-sm text-secondary flex items-center gap-1.5 font-medium">
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
                    <div className="type-control crawl-control-label">Fetch Mode</div>
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
                    <div className="type-control crawl-control-label">Browser Engine</div>
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
                    <div className="type-control crawl-control-label">Extraction</div>
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
                    <div className="type-control crawl-control-label">JS Mode</div>
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
                    <div className="type-control crawl-control-label">Traversal</div>
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
                    onChange={setRespectRobotsTxt}
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
                    onChange={setMaxRecords}
                    onReset={() => setMaxRecords(String(CRAWL_DEFAULTS.MAX_RECORDS))}
                  />
                  <div className={ADVANCED_CONTROL_ROW_CLASS}>
                    <div className="flex items-center gap-2">
                      <div className="type-control crawl-control-label">Host Memory TTL</div>
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
                    <div className="type-control crawl-control-label">Geo Country</div>
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
                    <div className="type-control crawl-control-label">Language Hint</div>
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
                    <div className="type-control crawl-control-label">Currency Hint</div>
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
                    <div className="type-control crawl-control-label">Diagnostics</div>
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
                    <div className="type-control crawl-control-label">Network Capture</div>
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
