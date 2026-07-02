import { useMemo, useReducer } from 'react';

import type { CrawlConfig } from '../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../lib/constants/crawl-defaults';
import { InlineAlert } from '../ui/patterns';
import { clampNumber, deriveSurface, parseLines, uniqueRequestedFields } from './shared';
import { canPreview, isSingleUrlMode, surfaceLabel } from './crawl-config-logic';
import {
  bindCrawlConfigLocalDispatch,
  buildInitialLocalState,
  crawlConfigLocalReducer,
  type CrawlConfigScreenProps,
  useCrawlRouteState,
} from './crawl-config-state';
import { DOMAIN_TABS } from './domain-surface-config';
import * as crawlConfigForm from './use-crawl-config';
import { CrawlAdvancedSettingsCard } from './crawl-advanced-settings-card';
import { CrawlFieldConfigCard } from './crawl-field-config-card';
import { CrawlQuickSettingsCard } from './crawl-quick-settings-card';
import { CrawlTargetCard } from './crawl-target-card';
import { useCrawlDomainMemory } from './use-crawl-domain-memory';
import { useCrawlFieldActions } from './use-crawl-field-actions';
import { useCrawlRouteSync } from './use-crawl-route-sync';
import { useCrawlSubmission } from './use-crawl-submission';

export function CrawlConfigScreen({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
  requestedUrl = '',
}: Readonly<CrawlConfigScreenProps>) {
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
  const [localState, dispatchLocal] = useReducer(crawlConfigLocalReducer, buildInitialLocalState());
  const localDispatch = useMemo(() => bindCrawlConfigLocalDispatch(dispatchLocal), [dispatchLocal]);
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
    fieldConfigMessage,
    fieldConfigError,
    fieldRowMessages,
    activeFieldTestId,
    configError,
  } = localState;

  const activeMode = crawlTab === 'category' ? categoryMode : pdpMode;
  useCrawlRouteSync({
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
  });

  const surface = deriveSurface(crawlDomain, crawlTab);
  const domainTabs = DOMAIN_TABS[crawlDomain];
  const activeTabLabel =
    domainTabs.find((tab) => tab.value === crawlTab)?.label ?? surfaceLabel(surface);
  const singleUrlMode = isSingleUrlMode(crawlTab, activeMode);
  const { markProfileDirty } = useCrawlDomainMemory({
    singleUrlMode,
    targetUrl,
    surface,
    setFieldRows,
    localDispatch,
  });

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
      activeMode,
      additionalFields,
      bulkUrls,
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

  const { startCrawl } = useCrawlSubmission({
    config,
    fieldRows,
    runProfile,
    studioMode,
    maxRecords,
    setConfigError: localDispatch.setConfigError,
  });
  const { addManualField, generateFieldSelectors, testFieldRow } = useCrawlFieldActions({
    targetUrl,
    surface,
    fieldRows,
    additionalFields,
    setFieldRows,
    localDispatch,
  });

  const hasTarget =
    crawlTab === 'category' && activeMode === 'sitemap'
      ? sitemapDomain.trim().length > 0
      : singleUrlMode
        ? targetUrl.trim().length > 0
        : bulkUrls.trim().length > 0 || csvFile !== null;
  const canSubmit =
    hasTarget && canPreview(config, fieldRows, { runProfile, studioMode }) && !isSubmitting;

  return (
    <div className="page-stack gap-4">
      <form
        className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_380px] xl:items-stretch"
        onSubmit={(event) => void handleSubmit(startCrawl)(event)}
      >
        <CrawlTargetCard
          crawlTab={crawlTab}
          categoryMode={categoryMode}
          pdpMode={pdpMode}
          activeMode={activeMode}
          activeTabLabel={activeTabLabel}
          domainTabs={domainTabs}
          showSurfaceTabs={domainTabs.length > 1}
          canSubmit={canSubmit}
          isSubmitting={isSubmitting}
          targetUrl={targetUrl}
          bulkUrls={bulkUrls}
          csvFile={csvFile}
          sitemapDomain={sitemapDomain}
          sitemapFilterKeyword={sitemapFilterKeyword}
          sitemapMaxUrls={sitemapMaxUrls}
          savedProfileMessage={savedProfileMessage}
          additionalDraft={additionalDraft}
          additionalFields={additionalFields}
          onTabChange={(tab) => dispatchRoute({ type: 'setTab', tab })}
          onCategoryModeChange={(mode) => dispatchRoute({ type: 'setCategoryMode', mode })}
          onPdpModeChange={(mode) => dispatchRoute({ type: 'setPdpMode', mode })}
          onTargetUrlChange={(value) => setValue('targetUrl', value)}
          onBulkUrlsChange={(value) => setValue('bulkUrls', value)}
          onCsvFileChange={localDispatch.setCsvFile}
          onSitemapDomainChange={localDispatch.setSitemapDomain}
          onSitemapFilterKeywordChange={localDispatch.setSitemapFilterKeyword}
          onSitemapMaxUrlsChange={localDispatch.setSitemapMaxUrls}
          onAdditionalDraftChange={localDispatch.setAdditionalDraft}
          onAdditionalFieldCommit={(value) =>
            localDispatch.setAdditionalFields((current) =>
              uniqueRequestedFields([...current, value]),
            )
          }
          onAdditionalFieldRemove={(value) =>
            localDispatch.setAdditionalFields((current) =>
              current.filter((field) => field !== value),
            )
          }
        />

        <CrawlQuickSettingsCard
          crawlDomain={crawlDomain}
          studioMode={studioMode}
          smartExtraction={smartExtraction}
          proxyEnabled={proxyEnabled}
          proxyInput={proxyInput}
          singleUrlMode={singleUrlMode}
          savedProfileLoaded={savedProfileLoaded}
          savedProfileDomain={savedProfileDomain}
          surface={surface}
          onDomainChange={(domain) => dispatchRoute({ type: 'setDomain', domain })}
          onStudioModeChange={localDispatch.setStudioMode}
          onSmartExtractionChange={localDispatch.setSmartExtraction}
          onProxyEnabledChange={localDispatch.setProxyEnabled}
          onProxyInputChange={(value) => setValue('proxyInput', value)}
        />

        {studioMode === 'advanced' ? (
          <CrawlFieldConfigCard
            fieldRows={fieldRows}
            fieldMessages={fieldRowMessages}
            targetUrl={targetUrl}
            activeFieldTestId={activeFieldTestId}
            generatingSelectors={generatingSelectors}
            message={fieldConfigMessage}
            error={fieldConfigError}
            setFieldRows={setFieldRows}
            clearFieldMessage={(rowId) =>
              localDispatch.setFieldRowMessages((current) => {
                if (!current[rowId]) return current;
                const next = { ...current };
                delete next[rowId];
                return next;
              })
            }
            onGenerate={() => void generateFieldSelectors()}
            onAddField={addManualField}
            onTest={(row) => void testFieldRow(row)}
          />
        ) : null}

        {configError ? (
          <div className="xl:col-span-2">
            <InlineAlert message={configError} />
          </div>
        ) : null}

        {studioMode === 'advanced' ? (
          <CrawlAdvancedSettingsCard
            runProfile={runProfile}
            respectRobotsTxt={respectRobotsTxt}
            maxRecords={maxRecords}
            onProfileChange={markProfileDirty}
            onRespectRobotsTxtChange={localDispatch.setRespectRobotsTxt}
            onMaxRecordsChange={(value) => setValue('maxRecords', value)}
          />
        ) : null}
      </form>
    </div>
  );
}
