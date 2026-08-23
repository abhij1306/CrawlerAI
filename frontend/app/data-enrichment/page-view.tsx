import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';
import { dataEnrichmentApi } from '../../lib/api/data-enrichment';
import type { EnrichedProduct } from '../../lib/api/data-enrichment';
import { loadPrefill, useDataEnrichmentState } from './data-enrichment-state';
import {
  activeEnrichmentJob,
  EnrichmentHeader,
  enrichmentDescription,
  EnrichmentResults,
  summarizeProducts,
} from './enrichment-page-sections';

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
    queryFn: () => dataEnrichmentApi.listDataEnrichmentJobs({ limit: 20 }),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      const hasRunningJob = jobs.some(
        (job) => job.status === 'pending' || job.status === 'running',
      );
      return historyOpen || hasRunningJob ? 4000 : false;
    },
  });

  const historyItems: HistoryItem[] = useMemo(
    () =>
      (jobsData ?? []).map((job) => ({
        id: job.id,
        status: job.status,
        created_at: job.created_at,
        label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
        meta: `${Number(job.summary?.accepted_count ?? 0)} records enriched`,
      })),
    [jobsData],
  );

  useEffect(() => {
    const initialJobId = sourceRecords.length ? null : (jobsData?.[0]?.id ?? null);
    if (initialJobId !== null) dispatch({ type: 'initialJobResolved', jobId: initialJobId });
  }, [dispatch, jobsData, sourceRecords.length]);

  const resolvedJobId = activeJobId;
  const {
    data: detailData,
    isLoading: isDetailLoading,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useQuery({
    queryKey: queryKeys.dataEnrichment.detail(resolvedJobId ?? 0),
    queryFn: () => dataEnrichmentApi.getDataEnrichmentJob(resolvedJobId ?? 0),
    enabled: resolvedJobId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job?.status ?? '');
      return status === 'pending' || status === 'running' ? 2500 : false;
    },
  });
  const activeJob = activeEnrichmentJob(detailData?.job, jobsData, resolvedJobId);
  const isRunning = activeJob?.status === 'pending' || activeJob?.status === 'running';
  const products = detailData?.enriched_products ?? EMPTY_ENRICHED_PRODUCTS;
  const productSummary = useMemo(
    () => summarizeProducts(products, selectedProductId),
    [products, selectedProductId],
  );
  const { resolvedProductId, selectedProduct, completedCount, semanticCount } = productSummary;

  const createMutation = useMutation({
    mutationFn: () =>
      dataEnrichmentApi.createDataEnrichmentJob({
        source_run_id: initialPrefill.source_run_id ?? null,
        source_record_ids: sourceRecordIds,
        source_records: sourceRecords,
        options: { max_source_records: 500, llm_enabled: llmEnabled },
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

  return (
    <div className="page-stack h-full">
      <EnrichmentHeader
        description={enrichmentDescription(
          sourceRecords.length,
          completedCount,
          semanticCount,
          activeJob,
        )}
        llmEnabled={llmEnabled}
        sourceCount={sourceRecords.length}
        canStart={sourceRecordIds.length > 0}
        pending={createMutation.isPending}
        activeJob={activeJob}
        error={error}
        onLlmChange={(enabled) => dispatch({ type: 'llmChanged', enabled })}
        onStart={() => createMutation.mutate()}
      />
      <EnrichmentResults
        products={products}
        sourceRecords={sourceRecords}
        selectedProduct={selectedProduct}
        resolvedProductId={resolvedProductId}
        resolvedJobId={resolvedJobId}
        completedCount={completedCount}
        running={isRunning}
        detailLoading={isDetailLoading}
        detailFetching={isDetailFetching}
        llmEnabled={Boolean(activeJob?.options?.llm_enabled)}
        onRefresh={() => void refetchDetail()}
        onHistory={() => dispatch({ type: 'historyChanged', open: true })}
        onSelect={(id) => dispatch({ type: 'productSelected', productId: id })}
      />
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
