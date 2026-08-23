import { History, Play, RefreshCcw } from 'lucide-react';

import { buttonVariants } from '../../components/ui/button-variants';
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  TableSurface,
} from '../../components/ui/patterns';
import { Button } from '../../components/ui/primitives';
import type {
  DataEnrichmentJob,
  DataEnrichmentSourceRecordInput,
  EnrichedProduct,
} from '../../lib/api/data-enrichment';
import { cn } from '../../lib/utils';
import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';
import { EnrichedProductDetail, EnrichedProductSidebar } from './enriched-product-view';
import { SourceRecordList } from './source-record-list';

export function summarizeProducts(products: EnrichedProduct[], selectedProductId: number | null) {
  const selectedExists = products.some((product) => product.id === selectedProductId);
  const resolvedProductId = selectedExists ? selectedProductId : (products[0]?.id ?? null);
  return {
    resolvedProductId,
    selectedProduct: products.find((product) => product.id === resolvedProductId) ?? null,
    completedCount: products.filter((product) => product.status === 'enriched').length,
    semanticCount: products.filter((product) => Boolean(product.intent_attributes?.length)).length,
  };
}

export function activeEnrichmentJob(
  detailJob: DataEnrichmentJob | undefined,
  jobs: DataEnrichmentJob[] | undefined,
  jobId: number | null,
) {
  return detailJob ?? jobs?.find((job) => job.id === jobId) ?? null;
}

export function enrichmentDescription(
  sourceCount: number,
  completedCount: number,
  semanticCount: number,
  activeJob: DataEnrichmentJob | null,
) {
  const parts = [
    sourceCount > 0 ? `${sourceCount} selected` : null,
    completedCount > 0 ? `${completedCount} enriched` : null,
    semanticCount > 0 ? `${semanticCount} semantic` : null,
    activeJob ? `Mode: ${activeJob.options?.llm_enabled ? 'LLM' : 'Rules'}` : null,
  ].filter(Boolean);
  return (
    parts.join(' · ') ||
    'Normalize ecommerce detail records into category, price, attribute, and discovery fields.'
  );
}

function enrichmentActionLabel(pending: boolean, running: boolean, status: string | undefined) {
  if (pending || status === 'pending') return 'Starting...';
  return running ? 'Enriching...' : 'Enrich Selected';
}

export function EnrichmentHeader({
  description,
  llmEnabled,
  sourceCount,
  canStart,
  pending,
  activeJob,
  error,
  onLlmChange,
  onStart,
}: {
  description: string;
  llmEnabled: boolean;
  sourceCount: number;
  canStart: boolean;
  pending: boolean;
  activeJob: DataEnrichmentJob | null;
  error: string;
  onLlmChange: (enabled: boolean) => void;
  onStart: () => void;
}) {
  const running = activeJob?.status === 'pending' || activeJob?.status === 'running';
  return (
    <>
      <PageHeader
        title="Data Enrichment"
        description={description}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <label
              className={cn(buttonVariants({ variant: 'neutral', size: 'sm' }), 'cursor-pointer')}
            >
              <input
                type="checkbox"
                checked={llmEnabled}
                onChange={(event) => onLlmChange(event.target.checked)}
                className="size-3 cursor-pointer rounded border-divider text-accent focus:ring-accent"
              />
              LLM Enrichment
            </label>
            <Button
              type="button"
              variant="action"
              size="sm"
              disabled={!canStart || pending || running}
              onClick={onStart}
            >
              <Play className="size-3" />
              {enrichmentActionLabel(pending, running, activeJob?.status)}
            </Button>
          </div>
        }
      />
      {error ? <InlineAlert tone="danger" message={error} /> : null}
      {running ? (
        <EnrichmentStatus
          sourceCount={Number(activeJob?.summary?.accepted_count ?? sourceCount)}
          llmEnabled={Boolean(activeJob?.options?.llm_enabled)}
        />
      ) : null}
    </>
  );
}

export function EnrichmentResults({
  products,
  sourceRecords,
  selectedProduct,
  resolvedProductId,
  resolvedJobId,
  completedCount,
  running,
  detailLoading,
  detailFetching,
  llmEnabled,
  onRefresh,
  onHistory,
  onSelect,
}: {
  products: EnrichedProduct[];
  sourceRecords: DataEnrichmentSourceRecordInput[];
  selectedProduct: EnrichedProduct | null;
  resolvedProductId: number | null;
  resolvedJobId: number | null;
  completedCount: number;
  running: boolean;
  detailLoading: boolean;
  detailFetching: boolean;
  llmEnabled: boolean;
  onRefresh: () => void;
  onHistory: () => void;
  onSelect: (id: number) => void;
}) {
  let content = (
    <DataRegionEmpty
      title="No records selected"
      description="Open an ecommerce detail run and send selected records here to begin enrichment."
    />
  );
  if (sourceRecords.length) content = <SourceRecordList records={sourceRecords} />;
  if (products.length)
    content = (
      <div className="flex h-[600px] flex-col divide-y divide-divider lg:flex-row lg:divide-x lg:divide-y-0">
        <EnrichedProductSidebar
          key={resolvedJobId ?? 'source-records'}
          products={products}
          resolvedProductId={resolvedProductId}
          onSelect={onSelect}
        />
        <EnrichedProductDetail product={selectedProduct} />
      </div>
    );
  if (detailLoading && !running) content = <DataRegionLoading count={8} className="px-0" />;
  if (running && completedCount === 0) content = <EnrichmentTableLoading llmEnabled={llmEnabled} />;
  return (
    <TableSurface className="mb-8" contentClassName="flex flex-col">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-divider px-4 py-3">
        <h2 className="type-label-mono">
          {products.length ? 'ENRICHED OUTPUT' : 'SELECTED RECORDS'}
        </h2>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="quiet"
            size="sm"
            onClick={onRefresh}
            disabled={!resolvedJobId || detailFetching}
          >
            <RefreshCcw className="mr-1.5 size-3" /> Refresh
          </Button>
          <Button
            type="button"
            variant="quiet"
            size="icon"
            className="shrink-0"
            onClick={onHistory}
            aria-label="Enrichment History"
          >
            <History className="size-3.5" />
          </Button>
        </div>
      </header>
      {content}
    </TableSurface>
  );
}
