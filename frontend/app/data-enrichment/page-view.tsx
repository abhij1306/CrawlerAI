import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { History, Play, RefreshCcw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';

import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  TableSurface,
} from '../../components/ui/patterns';
import { Button } from '../../components/ui/primitives';
import { buttonVariants } from '../../components/ui/button-variants';
import { api } from '../../lib/api';
import { loadPrefill, useDataEnrichmentState } from './data-enrichment-state';
import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';
import { EnrichedProductDetail, EnrichedProductSidebar } from './enriched-product-view';
import { SourceRecordList } from './source-record-list';
import type { EnrichedProduct } from '../../lib/api/types';
import { cn } from '../../lib/utils';

const EMPTY_ENRICHED_PRODUCTS: EnrichedProduct[] = [];

export default function DataEnrichmentPage() {
  const queryClient = useQueryClient();
  const [initialPrefill] = useState(loadPrefill);
  const { state, dispatch } = useDataEnrichmentState();
  const { llmEnabled, activeJobId, error, historyOpen, selectedProductId } = state;

  const sourceRecords = initialPrefill.records ?? [];
  const sourceRecordIds = sourceRecords
    .map((record) => record.id)
    .filter((id): id is number => typeof id === 'number');

  const { data: jobsData } = useQuery({
    queryKey: queryKeys.dataEnrichment.jobs(),
    queryFn: () => api.listDataEnrichmentJobs({ limit: 20 }),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      const hasRunningJob = jobs.some(
        (job) => job.status === 'pending' || job.status === 'running',
      );
      return historyOpen || hasRunningJob ? 4000 : false;
    },
  });

  const historyItems: HistoryItem[] = useMemo(() => {
    return (jobsData ?? []).map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
      meta: `${Number(job.summary?.accepted_count ?? 0)} records enriched`,
    }));
  }, [jobsData]);

  useEffect(() => {
    const initialJobId = sourceRecords.length ? null : (jobsData?.[0]?.id ?? null);
    if (initialJobId !== null) {
      dispatch({ type: 'initialJobResolved', jobId: initialJobId });
    }
  }, [dispatch, jobsData, sourceRecords.length]);

  const resolvedJobId = activeJobId;
  const {
    data: detailData,
    isLoading: isDetailLoading,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useQuery({
    queryKey: queryKeys.dataEnrichment.detail(resolvedJobId ?? 0),
    queryFn: () => api.getDataEnrichmentJob(resolvedJobId ?? 0),
    enabled: resolvedJobId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job?.status ?? '');
      return status === 'pending' || status === 'running' ? 2500 : false;
    },
  });
  const activeJob = detailData?.job ?? jobsData?.find((job) => job.id === resolvedJobId) ?? null;
  const isRunning = activeJob?.status === 'pending' || activeJob?.status === 'running';

  const products = detailData?.enriched_products ?? EMPTY_ENRICHED_PRODUCTS;
  const productSummary = useMemo(() => {
    const selectedProductExists = products.some((product) => product.id === selectedProductId);
    const resolvedProductId = selectedProductExists ? selectedProductId : (products[0]?.id ?? null);
    return {
      resolvedProductId,
      selectedProduct: products.find((p) => p.id === resolvedProductId) ?? null,
      completedCount: products.filter((product) => product.status === 'enriched').length,
      semanticCount: products.filter((product) => Boolean(product.intent_attributes?.length))
        .length,
    };
  }, [products, selectedProductId]);
  const { resolvedProductId, selectedProduct, completedCount, semanticCount } = productSummary;

  const createMutation = useMutation({
    mutationFn: () =>
      api.createDataEnrichmentJob({
        source_run_id: initialPrefill.source_run_id ?? null,
        source_record_ids: sourceRecordIds,
        source_records: sourceRecords,
        options: {
          max_source_records: 500,
          llm_enabled: llmEnabled,
        },
      }),
    onSuccess: async (job) => {
      dispatch({ type: 'jobCreated', jobId: job.id });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.dataEnrichment.jobs() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.dataEnrichment.detail(job.id) }),
      ]);
    },
    onError: (mutationError) => {
      dispatch({
        type: 'failed',
        message:
          mutationError instanceof Error ? mutationError.message : 'Unable to start enrichment.',
      });
    },
  });

  const descriptionText =
    [
      sourceRecords.length > 0 ? `${sourceRecords.length} selected` : null,
      completedCount > 0 ? `${completedCount} enriched` : null,
      semanticCount > 0 ? `${semanticCount} semantic` : null,
      activeJob ? `Mode: ${activeJob.options?.llm_enabled ? 'LLM' : 'Rules'}` : null,
    ]
      .filter(Boolean)
      .join(' · ') ||
    'Normalize ecommerce detail records into category, price, attribute, and discovery fields.';

  return (
    <div className="page-stack h-full">
      <PageHeader
        title="Data Enrichment"
        description={descriptionText}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <label
              className={cn(buttonVariants({ variant: 'neutral', size: 'sm' }), 'cursor-pointer')}
            >
              <input
                type="checkbox"
                checked={llmEnabled}
                onChange={(event) =>
                  dispatch({ type: 'llmChanged', enabled: event.target.checked })
                }
                className="size-3 cursor-pointer rounded border-divider text-accent focus:ring-accent"
              />
              LLM Enrichment
            </label>
            <Button
              type="button"
              variant="action"
              size="sm"
              disabled={!sourceRecordIds.length || createMutation.isPending || isRunning}
              onClick={() => createMutation.mutate()}
            >
              <Play className="size-3" />
              {createMutation.isPending
                ? 'Starting...'
                : isRunning
                  ? activeJob?.status === 'pending'
                    ? 'Starting...'
                    : 'Enriching...'
                  : 'Enrich Selected'}
            </Button>
          </div>
        }
      />

      {error ? <InlineAlert tone="danger" message={error} /> : null}

      {isRunning ? (
        <EnrichmentStatus
          sourceCount={Number(activeJob?.summary?.accepted_count ?? sourceRecords.length)}
          llmEnabled={Boolean(activeJob?.options?.llm_enabled)}
        />
      ) : null}

      {/* ── Main Results ── */}
      <TableSurface className="mb-8" contentClassName="flex flex-col">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-divider px-4 py-3">
          <div className="flex items-center gap-3">
            <h2 className="type-label-mono">
              {products.length > 0 ? 'ENRICHED OUTPUT' : 'SELECTED RECORDS'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="quiet"
              size="sm"
              onClick={() => void refetchDetail()}
              disabled={!resolvedJobId || isDetailFetching}
            >
              <RefreshCcw className="mr-1.5 size-3" />
              Refresh
            </Button>
            <Button
              type="button"
              variant="quiet"
              size="icon"
              className="shrink-0"
              onClick={() => dispatch({ type: 'historyChanged', open: true })}
              aria-label="Enrichment History"
            >
              <History className="size-3.5" />
            </Button>
          </div>
        </header>

        {isRunning && completedCount === 0 ? (
          <EnrichmentTableLoading llmEnabled={Boolean(activeJob?.options?.llm_enabled)} />
        ) : isDetailLoading && !isRunning ? (
          <DataRegionLoading count={8} className="px-0" />
        ) : products.length ? (
          <div className="flex h-[600px] flex-col divide-y divide-divider lg:flex-row lg:divide-x lg:divide-y-0">
            <EnrichedProductSidebar
              key={resolvedJobId ?? 'source-records'}
              products={products}
              resolvedProductId={resolvedProductId}
              onSelect={(id) => dispatch({ type: 'productSelected', productId: id })}
            />
            <EnrichedProductDetail product={selectedProduct} />
          </div>
        ) : sourceRecords.length ? (
          <SourceRecordList records={sourceRecords} />
        ) : (
          <DataRegionEmpty
            title="No records selected"
            description="Open an ecommerce detail run and send selected records here to begin enrichment."
          />
        )}
      </TableSurface>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => dispatch({ type: 'historyChanged', open: false })}
        items={historyItems}
        activeId={resolvedJobId}
        onSelect={(id) => dispatch({ type: 'historyJobSelected', jobId: id })}
        title="Enrichment History"
      />
    </div>
  );
}
