'use client';

import { Code2, Download, History, Layers, Search, Settings } from 'lucide-react';
import type { ReactNode } from 'react';

import { DataRegionEmpty } from '../../components/ui/patterns';
import { Badge, Button, Dropdown, Input } from '../../components/ui/primitives';
import { DiscoveryTableLoading } from './product-intelligence-components';
import { CandidateGroupSection } from './product-intelligence-candidate-card';
import { downloadRows } from './product-intelligence-export';
import type { ProductIntelligenceController } from './use-product-intelligence';
import { formatPrice, isRecord, stringField } from './product-intelligence-utils';

type ProductIntelligenceResultsProps = {
  controller: ProductIntelligenceController;
};

export function ProductIntelligenceResults({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div>
      <div className="space-y-4">
        <section className="border-border bg-panel shadow-card overflow-hidden rounded-[var(--radius-xl)] border">
          <ResultsToolbar controller={controller} />
          <ResultsBody controller={controller} />
        </section>
        {controller.uniqueSelectedUrls.length > 0 ? (
          <BulkActionBar controller={controller} />
        ) : null}
      </div>
    </div>
  );
}

function ResultsToolbar({ controller }: ProductIntelligenceResultsProps) {
  const allFilteredSelected =
    controller.filteredCandidates.length > 0 &&
    controller.filteredCandidates.every((candidate) =>
      controller.selectedUrls.includes(candidate.url),
    );
  return (
    <header className="border-divider flex flex-wrap items-center gap-4 border-b px-4 py-3">
      <div className="flex shrink-0 items-center gap-3">
        {controller.discovery?.candidates.length ? (
          <input
            type="checkbox"
            className="border-divider text-accent focus:ring-accent h-3.5 w-3.5 cursor-pointer rounded"
            checked={allFilteredSelected}
            onChange={controller.toggleAllUrls}
            aria-label="Select all filtered URLs"
            title="Select all filtered URLs"
          />
        ) : null}
        <h2 className="type-label-mono text-muted uppercase">DISCOVERED CANDIDATES</h2>
      </div>
      {controller.discovery?.candidates.length ? <ResultsFilters controller={controller} /> : null}
      <ToolbarActions controller={controller} />
    </header>
  );
}

function ResultsFilters({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="flex flex-1 items-center gap-2">
      <div className="relative min-w-[200px] flex-1">
        <Search className="text-muted absolute top-1/2 left-2.5 size-3 -translate-y-1/2" />
        <Input
          type="text"
          value={controller.searchText}
          onChange={(event) => controller.setSearchText(event.target.value)}
          placeholder="Filter by title, domain, or brand..."
          className="bg-background-alt focus:bg-background focus:border-accent/20 type-body h-8 border-transparent pl-8"
        />
      </div>
      <Dropdown
        value={controller.confidenceFilter}
        onChange={(value) =>
          controller.setConfidenceFilter(value as 'all' | 'high' | 'medium' | 'low')
        }
        options={[
          { value: 'all', label: 'All Confidence' },
          { value: 'high', label: `High (${controller.confidenceDistribution.high})` },
          { value: 'medium', label: `Med (${controller.confidenceDistribution.medium})` },
          { value: 'low', label: `Low (${controller.confidenceDistribution.low})` },
        ]}
        ariaLabel="Filter by confidence"
        className="type-control h-8 w-[160px]"
      />
    </div>
  );
}

function ToolbarActions({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="flex items-center gap-2">
      {controller.selectedDomainSummary ? (
        <>
          <div className="bg-accent border-accent flex items-center gap-2 rounded border px-2 py-1">
            <span className="type-label-mono font-bold text-white uppercase">
              {controller.selectedDomainSummary.count} selected
            </span>
          </div>
          <div className="bg-divider mx-1 h-4 w-px" />
        </>
      ) : null}
      <IconAction onClick={() => controller.setConfigOpen(true)} label="Settings">
        <Settings className="size-4" />
      </IconAction>
      <IconAction onClick={() => controller.setHistoryOpen(true)} label="Run History">
        <History className="size-4" />
      </IconAction>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="secondary"
          size="icon"
          onClick={() => downloadRows('urls', 'csv', controller.discovery)}
          disabled={!controller.discovery?.candidates.length}
          className="h-8 w-8"
          aria-label="Download CSV"
        >
          <Download className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="icon"
          onClick={() => downloadRows('urls', 'json', controller.discovery)}
          disabled={!controller.discovery?.candidates.length}
          className="h-8 w-8"
          aria-label="Download JSON"
        >
          <Code2 className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function ResultsBody({ controller }: ProductIntelligenceResultsProps) {
  if (controller.pending) {
    return <DiscoveryTableLoading provider={controller.effectiveOptions.search_provider} />;
  }
  if (controller.groupedCandidates.length) {
    return (
      <div className="divide-y divide-[var(--divider)]">
        {controller.groupedCandidates.map((group, groupIndex) => (
          <CandidateGroupSection
            key={group.sourceIndex}
            group={group}
            groupIndex={groupIndex}
            controller={controller}
          />
        ))}
      </div>
    );
  }
  if (controller.visibleSourceRecords.length) {
    return <SourceRecordsPreview controller={controller} />;
  }
  return (
    <DataRegionEmpty
      title="No discovery results yet"
      description="Add source products from a crawl run, configure search options, then click Discover URLs to find matching products across the web."
    />
  );
}

function SourceRecordsPreview({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="divide-y divide-[var(--divider)]">
      {controller.visibleSourceRecords.map((record, index) => {
        const data = isRecord(record.data) ? record.data : {};
        const title = stringField(data.title ?? data.name ?? data.product_title);
        const brand = stringField(data.brand ?? data.brand_name);
        const price = formatPrice(
          data.price,
          typeof data.currency === 'string' ? data.currency : '',
        );
        const url = (typeof data.url === 'string' && data.url) || record.source_url || '';
        return (
          <div
            key={`${record.id ?? 'src'}-${index}`}
            className="hover:bg-background-alt flex items-center gap-3 px-3 py-2.5"
          >
            <span className="text-muted type-caption-mono w-6 shrink-0">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="text-foreground type-body truncate font-medium" title={title}>
                {title}
              </div>
              <div className="text-muted type-caption flex items-center gap-2">
                <span>{brand}</span>
                <span className="type-caption-mono">{price}</span>
                {url ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-accent truncate hover:underline"
                    title={url}
                  >
                    {url}
                  </a>
                ) : null}
              </div>
            </div>
            <Badge tone="neutral" className="h-5 shrink-0 px-1.5 text-xs">
              Pending
            </Badge>
          </div>
        );
      })}
    </div>
  );
}

function BulkActionBar({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="animate-fade-in sticky bottom-4 z-20">
      <div className="border-border bg-panel flex items-center gap-3 rounded-[var(--radius-xl)] border px-4 py-2.5 shadow-lg">
        <Layers className="text-accent size-4 shrink-0" />
        <span className="text-foreground type-body font-medium">
          {controller.uniqueSelectedUrls.length} URLs selected
        </span>
        <span className="text-muted type-body">
          from {controller.selectedDomainSummary?.domains.length ?? 0} domain
          {(controller.selectedDomainSummary?.domains.length ?? 0) !== 1 ? 's' : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => controller.setSelectedUrls([])}
            className="text-muted h-7 px-2"
          >
            Clear
          </Button>
          <Button
            type="button"
            variant="accent"
            size="sm"
            onClick={controller.sendSelectedToBatchCrawl}
            className="h-7 px-3"
          >
            Batch Crawl
          </Button>
        </div>
      </div>
    </div>
  );
}

function IconAction({
  children,
  label,
  onClick,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onClick}
      aria-label={label}
      className="text-muted hover:text-foreground h-8 w-8"
    >
      {children}
    </Button>
  );
}
