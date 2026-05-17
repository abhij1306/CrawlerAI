'use client';

import { Play, Search } from 'lucide-react';

import { HistoryDrawer } from '../../components/ui/history-drawer';
import { InlineAlert, PageHeader } from '../../components/ui/patterns';
import { Button } from '../../components/ui/primitives';
import { DiscoveryStatus, JsonModal } from './product-intelligence-components';
import { ProductIntelligenceResults } from './product-intelligence-results';
import { SettingsDrawer } from './product-intelligence-settings-drawer';
import type { ProductIntelligenceController } from './use-product-intelligence';
import { useProductIntelligence } from './use-product-intelligence';
import {
  DEFAULT_OPTIONS,
  MAX_CANDIDATES_PER_PRODUCT_LIMIT,
  MAX_SOURCE_PRODUCTS_LIMIT,
} from './product-intelligence-utils';

export default function ProductIntelligencePage() {
  const controller = useProductIntelligence();
  return <ProductIntelligenceContent controller={controller} />;
}

function ProductIntelligenceContent({ controller }: { controller: ProductIntelligenceController }) {
  return (
    <div className="page-stack gap-4">
      <PageHeader
        title="Product Intelligence"
        description={pageDescription(controller)}
        actions={productIntelligenceActions(controller)}
      />
      {controller.error ? <InlineAlert tone="danger" message={controller.error} /> : null}
      {controller.pending ? (
        <DiscoveryStatus
          provider={controller.effectiveOptions.search_provider}
          sourceCount={controller.visibleSourceRecords.length}
          maxCandidates={controller.effectiveOptions.max_candidates_per_product}
        />
      ) : null}
      <ProductIntelligenceResults controller={controller} />
      <SettingsDrawer
        open={controller.configOpen}
        onClose={() => controller.setConfigOpen(false)}
        options={controller.effectiveOptions}
        onOptionsChange={(patch) => {
          controller.setOptionsEdited(true);
          controller.setOptions((current) => ({ ...current, ...patch }));
        }}
        allowedDomainsText={controller.effectiveAllowedDomainsText}
        onAllowedDomainsTextChange={(value) => {
          controller.setOptionsEdited(true);
          controller.setAllowedDomainsText(value);
        }}
        excludedDomainsText={controller.effectiveExcludedDomainsText}
        onExcludedDomainsTextChange={(value) => {
          controller.setOptionsEdited(true);
          controller.setExcludedDomainsText(value);
        }}
        maxSourceProductsLimit={MAX_SOURCE_PRODUCTS_LIMIT}
        maxCandidatesPerProductLimit={MAX_CANDIDATES_PER_PRODUCT_LIMIT}
        defaultOptions={DEFAULT_OPTIONS}
      />
      {controller.jsonModalCandidate ? (
        <JsonModal
          candidate={controller.jsonModalCandidate}
          onClose={() => controller.setJsonModalCandidate(null)}
        />
      ) : null}
      <HistoryDrawer
        open={controller.historyOpen}
        onClose={() => controller.setHistoryOpen(false)}
        items={controller.historyItems}
        activeId={controller.resolvedActiveJobId}
        onSelect={(id) => controller.openJob(id)}
        title="Intelligence History"
      />
    </div>
  );
}

function productIntelligenceActions(controller: ProductIntelligenceController) {
  return (
    <div className="flex w-full flex-wrap items-center justify-end gap-2">
      <Button
        type="button"
        variant="accent"
        onClick={() => void controller.discover()}
        disabled={controller.pending || !controller.visibleSourceRecords.length}
        className="h-[var(--control-height)] px-4"
      >
        <Search className="size-3.5" />
        {controller.pending ? 'Discovering...' : 'Discover URLs'}
      </Button>
      <Button
        type="button"
        variant="accent"
        onClick={controller.sendSelectedToBatchCrawl}
        disabled={!controller.uniqueSelectedUrls.length}
        className="h-[var(--control-height)]"
      >
        <Play className="size-3.5" />
        Batch Crawl{' '}
        {controller.uniqueSelectedUrls.length ? `(${controller.uniqueSelectedUrls.length})` : ''}
      </Button>
    </div>
  );
}

function pageDescription(controller: ProductIntelligenceController) {
  return (
    [
      controller.visibleSourceRecords.length > 0
        ? `${controller.visibleSourceRecords.length} sources`
        : null,
      controller.discovery ? `${controller.discovery.candidate_count} discovered` : null,
      controller.uniqueSelectedUrls.length > 0
        ? `${controller.uniqueSelectedUrls.length} selected`
        : null,
    ]
      .filter(Boolean)
      .join(' · ') || 'Discover matching product URLs from source records'
  );
}
