import { Code2, Download, History, Layers, Search, Settings } from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';

import { DataRegionEmpty } from '../../components/ui/patterns';
import { Badge, Button, Dropdown, Input } from '../../components/ui/primitives';
import { SafeExternalLink } from '../../components/ui/safe-external-link';
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
        <section className="overflow-hidden rounded-xl border border-border bg-panel shadow-card">
          <ResultsToolbar controller={controller} />
          {controller.discovery?.candidates.length ? (
            <ResultsSummary controller={controller} />
          ) : null}
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
      controller.selectedUrlSet.has(candidate.url),
    );
  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-divider px-4 py-3">
      <div className="flex shrink-0 items-center gap-3">
        {controller.discovery?.candidates.length ? (
          <input
            type="checkbox"
            className="focus-ring size-3.5 cursor-pointer rounded border-border-strong bg-transparent accent-accent"
            checked={allFilteredSelected}
            onChange={controller.toggleAllUrls}
            aria-label="Select all filtered URLs"
            title="Select all filtered URLs"
          />
        ) : null}
        <h2 className="type-label">Discovered candidates</h2>
      </div>
      {controller.discovery?.candidates.length ? <ResultsFilters controller={controller} /> : null}
      <ToolbarActions controller={controller} />
    </header>
  );
}

function ResultsSummary({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="grid gap-3 border-b border-divider bg-background-alt/50 px-4 py-3 sm:grid-cols-4">
      <SummaryMetric label="Sources" value={controller.discovery?.source_count ?? 0} />
      <SummaryMetric label="Candidates" value={controller.discovery?.candidate_count ?? 0} />
      <SummaryMetric label="High confidence" value={controller.confidenceDistribution.high} />
      <SummaryMetric label="Selected URLs" value={controller.uniqueSelectedUrls.length} />
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="type-label">{label}</div>
      <div className="type-metric mt-1 text-lg">{value}</div>
    </div>
  );
}

function ResultsFilters({ controller }: ProductIntelligenceResultsProps) {
  return (
    <div className="flex flex-1 items-center gap-2">
      <div className="relative min-w-[200px] flex-1">
        <Search className="absolute top-1/2 left-2.5 size-3 -translate-y-1/2 text-muted" />
        <Input
          type="text"
          value={controller.searchText}
          onChange={(event) => controller.setSearchText(event.target.value)}
          placeholder="Filter by title, domain, or brand..."
          className="type-body-sm h-8 border-transparent bg-background-alt pl-8 focus:border-accent focus:bg-panel"
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
          <div className="flex items-center gap-2 rounded border border-accent bg-accent px-2 py-1">
            <span className="type-label font-normal !text-white">
              {controller.selectedDomainSummary.count} selected
            </span>
          </div>
          <div className="mx-1 h-4 w-px bg-divider" />
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
          variant="download"
          size="icon"
          onClick={() => downloadRows('urls', 'csv', controller.discovery)}
          disabled={!controller.discovery?.candidates.length}
          aria-label="Download CSV"
        >
          <Download className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="download"
          size="icon"
          onClick={() => downloadRows('urls', 'json', controller.discovery)}
          disabled={!controller.discovery?.candidates.length}
          aria-label="Download JSON"
        >
          <Code2 className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function ResultsBody({ controller }: ProductIntelligenceResultsProps) {
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<number>>(() => new Set([0]));
  const groupKeySig = useMemo(
    () => controller.groupedCandidates.map((group) => group.sourceIndex).join('|'),
    [controller.groupedCandidates],
  );
  const firstGroupKey = controller.groupedCandidates[0]?.sourceIndex;

  useEffect(() => {
    setExpandedGroupKeys(firstGroupKey === undefined ? new Set() : new Set([firstGroupKey]));
  }, [groupKeySig, firstGroupKey]);

  if (controller.loadingDiscovery) {
    return <DiscoveryTableLoading provider={controller.effectiveOptions.search_provider} />;
  }
  if (controller.groupedCandidates.length) {
    return (
      <div>
        {controller.groupedCandidates.map((group) => (
          <CandidateGroupSection
            key={group.sourceIndex}
            group={group}
            expanded={expandedGroupKeys.has(group.sourceIndex)}
            selectedUrlSet={controller.selectedUrlSet}
            onToggleExpanded={() => {
              setExpandedGroupKeys((current) => {
                const next = new Set(current);
                if (next.has(group.sourceIndex)) {
                  next.delete(group.sourceIndex);
                } else {
                  next.add(group.sourceIndex);
                }
                return next;
              });
            }}
            onToggleUrl={controller.toggleUrl}
            onOpenJson={controller.setJsonModalCandidate}
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
    <div>
      {controller.visibleSourceRecords.map((record, index) => {
        const data = isRecord(record.data) ? record.data : {};
        const title = stringField(data.title ?? data.name ?? data.product_title);
        const brand = stringField(data.brand ?? data.brand_name);
        const price = formatPrice(
          data.price,
          typeof data.currency === 'string' ? data.currency : '',
        );
        const url = (typeof data.url === 'string' && data.url) || record.source_url || '';
        const rowKey = record.id ?? (url || title || index);
        return (
          <div
            key={String(rowKey)}
            className="flex items-center gap-3 px-3 py-2.5 hover:bg-background-alt"
          >
            <span className="type-caption-mono w-6 shrink-0">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="type-body-sm truncate font-medium text-foreground" title={title}>
                {title}
              </div>
              <div className="type-caption flex items-center gap-2">
                <span>{brand}</span>
                <span className="type-caption-mono">{price}</span>
                {url ? (
                  <SafeExternalLink
                    href={url}
                    className="link-accent truncate hover:underline"
                    title={url}
                  >
                    {url}
                  </SafeExternalLink>
                ) : null}
              </div>
            </div>
            <Badge tone="neutral" className="h-5 shrink-0 px-1.5 text-base">
              Source
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
      <div className="flex items-center gap-3 rounded-xl border border-border bg-panel px-4 py-2.5 shadow-lg">
        <Layers className="size-4 shrink-0 text-accent" />
        <span className="type-body-sm font-semibold text-foreground">
          {controller.uniqueSelectedUrls.length} URLs selected
        </span>
        <span className="type-body-sm text-muted">
          from {controller.selectedDomainSummary?.domains.length ?? 0} domain
          {(controller.selectedDomainSummary?.domains.length ?? 0) !== 1 ? 's' : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="quiet"
            size="sm"
            onClick={() => controller.setSelectedUrls([])}
          >
            Clear
          </Button>
          <Button
            type="button"
            variant="action"
            size="sm"
            onClick={controller.sendSelectedToBatchCrawl}
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
    <Button type="button" variant="quiet" size="icon" onClick={onClick} aria-label={label}>
      {children}
    </Button>
  );
}
