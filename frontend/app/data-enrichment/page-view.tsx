import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, History, Loader2, Play, RefreshCcw } from 'lucide-react';
import { useMemo, useReducer, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';

import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  KVTile,
  PageHeader,
  TableSurface,
} from '../../components/ui/patterns';
import { Badge, Button } from '../../components/ui/primitives';
import { buttonVariants } from '../../components/ui/button-variants';
import { api } from '../../lib/api';
import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';
import type { DataEnrichmentSourceRecordInput, EnrichedProduct } from '../../lib/api/types';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { cn } from '../../lib/utils';

type PrefillPayload = {
  source_run_id?: number | null;
  records?: DataEnrichmentSourceRecordInput[];
};

type DataEnrichmentState = {
  llmEnabled: boolean;
  activeJobId: number | null;
  error: string;
  historyOpen: boolean;
  selectedProductId: number | null;
};

type DataEnrichmentAction =
  | { type: 'llmChanged'; enabled: boolean }
  | { type: 'jobCreated'; jobId: number }
  | { type: 'failed'; message: string }
  | { type: 'historyChanged'; open: boolean }
  | { type: 'productSelected'; productId: number | null }
  | { type: 'historyJobSelected'; jobId: number };

const INITIAL_DATA_ENRICHMENT_STATE: DataEnrichmentState = {
  llmEnabled: false,
  activeJobId: null,
  error: '',
  historyOpen: false,
  selectedProductId: null,
};

function dataEnrichmentReducer(
  state: DataEnrichmentState,
  action: DataEnrichmentAction,
): DataEnrichmentState {
  switch (action.type) {
    case 'llmChanged':
      return { ...state, llmEnabled: action.enabled };
    case 'jobCreated':
      return { ...state, error: '', activeJobId: action.jobId };
    case 'failed':
      return { ...state, error: action.message };
    case 'historyChanged':
      return { ...state, historyOpen: action.open };
    case 'productSelected':
      return { ...state, selectedProductId: action.productId };
    case 'historyJobSelected':
      return { ...state, activeJobId: action.jobId };
  }
}

function loadPrefill(): PrefillPayload {
  if (typeof window === 'undefined') return {};
  const stored = window.sessionStorage.getItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  if (!stored) return {};
  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
      records: Array.isArray(parsed.records) ? parsed.records : [],
    };
  } catch {
    return {};
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  }
}

export default function DataEnrichmentPage() {
  const queryClient = useQueryClient();
  const [initialPrefill] = useState(loadPrefill);
  const [state, dispatch] = useReducer(dataEnrichmentReducer, INITIAL_DATA_ENRICHMENT_STATE);
  const { llmEnabled, activeJobId, error, historyOpen, selectedProductId } = state;

  const sourceRecords = initialPrefill.records ?? [];
  const sourceRecordIds = sourceRecords
    .map((record) => record.id)
    .filter((id): id is number => typeof id === 'number');

  const { data: jobsData } = useQuery({
    queryKey: queryKeys.dataEnrichment.jobs(),
    queryFn: () => api.listDataEnrichmentJobs({ limit: 20 }),
    refetchInterval: 4000,
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

  const defaultJobId = sourceRecords.length ? null : (jobsData?.[0]?.id ?? null);
  const resolvedJobId = activeJobId ?? defaultJobId;
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

  const products = detailData?.enriched_products ?? [];
  const selectedProductExists = products.some((product) => product.id === selectedProductId);
  const resolvedProductId = selectedProductExists ? selectedProductId : (products[0]?.id ?? null);
  const selectedProduct = products.find((p) => p.id === resolvedProductId) ?? null;
  const completedCount = products.filter((product) => product.status === 'enriched').length;
  const semanticCount = products.filter((product) =>
    Boolean(product.intent_attributes?.length),
  ).length;

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

// EnrichedProductRow removed - replaced by split master-detail layout

function recordTitle(record: DataEnrichmentSourceRecordInput) {
  const title = record.data?.title;
  return typeof title === 'string' && title.trim()
    ? title
    : record.source_url?.replace(/^https?:\/\/(www\.)?/, '') || `Record #${record.id}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') {
    // Handle price object from EnrichmentStatus
    if ('amount' in value || 'price_min' in value) {
      const p = value as Record<string, unknown>;
      const amount = p.amount ?? p.price_min;
      const currency = (p.currency as string) || '';
      if (typeof amount === 'number') {
        return `${currency} ${amount.toFixed(2)}`.trim();
      }
    }
    return JSON.stringify(value);
  }
  return String(value);
}

interface EnrichedProductSidebarProps {
  products: EnrichedProduct[];
  resolvedProductId: number | null;
  onSelect: (id: number) => void;
}

function EnrichedProductSidebar({
  products,
  resolvedProductId,
  onSelect,
}: Readonly<EnrichedProductSidebarProps>) {
  return (
    <div className="flex min-h-0 w-full shrink-0 flex-col bg-background-alt/10 lg:w-80">
      <div className="border-b border-divider bg-subtle-panel/30 p-3">
        <span className="type-caption-mono uppercase">Record Selector ({products.length})</span>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {products.map((product) => {
          const isActive = product.id === resolvedProductId;
          const isProcessing = product.status === 'pending' || product.status === 'running';
          const title = product.source_url
            ? product.source_url.replace(/^https?:\/\/(www\.)?/, '')
            : `Record #${product.source_record_id}`;
          return (
            <button
              key={product.id}
              type="button"
              onClick={() => onSelect(product.id)}
              className={cn(
                'flex w-full flex-col gap-1.5 rounded-md border p-3 text-left transition-colors',
                isActive
                  ? 'border-accent bg-accent-subtle/50'
                  : 'border-border bg-background hover:bg-background-elevated',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-75">
                  #{product.source_record_id}
                </Badge>
                {isProcessing ? (
                  <div className="flex items-center gap-1 opacity-60">
                    <Loader2 className="size-3 animate-spin text-accent" />
                    <span className="type-caption-mono">Processing</span>
                  </div>
                ) : null}
              </div>
              <div
                className="type-body-sm w-full truncate font-medium text-foreground"
                title={product.source_url}
              >
                {title}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface EnrichedProductDetailProps {
  product: EnrichedProduct | null;
}

function EnrichedProductDetail({ product }: Readonly<EnrichedProductDetailProps>) {
  if (!product) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <div className="grid flex-1 place-items-center p-6 text-center">
          <div className="type-body text-muted">
            Select a record from the list to view full enrichment details.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        <div className="border-b border-divider pb-4">
          <div className="flex items-center gap-2">
            <span className="type-heading-3">Enriched Record Details</span>
            <Badge tone="neutral" className="font-mono text-xs">
              Record #{product.source_record_id}
            </Badge>
          </div>
          {product.source_url ? (
            <a
              href={product.source_url}
              target="_blank"
              rel="noreferrer"
              className="type-body-sm mt-1 flex items-center gap-1 truncate text-accent hover:underline"
            >
              {product.source_url}
              <ExternalLink className="size-3 shrink-0" />
            </a>
          ) : null}
        </div>

        <div className="space-y-6">
          <div className="space-y-4 rounded-lg border border-border bg-subtle-panel/20 p-4">
            <h3 className="type-label-mono flex items-center gap-1.5 uppercase">
              <span className="size-1.5 rounded-full bg-accent" />
              Core Attributes
            </h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
              <KVTile
                label="Price (Normalized)"
                value={formatValue(product.price_normalized) || '--'}
              />
              <KVTile label="Color Family" value={product.color_family || '--'} />
              <KVTile label="Size Normalized" value={product.size_normalized?.join(', ') || '--'} />
              <KVTile label="Size System" value={product.size_system || '--'} />
              <KVTile label="Gender Normalized" value={product.gender_normalized || '--'} />
              <KVTile
                label="Materials Normalized"
                value={product.materials_normalized?.join(', ') || '--'}
              />
              <KVTile label="Availability" value={product.availability_normalized || '--'} />
            </div>
          </div>

          <div className="space-y-4 rounded-lg border border-border bg-subtle-panel/20 p-4">
            <h3 className="type-label-mono flex items-center gap-1.5 uppercase">
              <span className="size-1.5 rounded-full bg-info" />
              Taxonomy &amp; Context
            </h3>
            <div className="grid grid-cols-1 gap-4">
              <KVTile label="Category Path" value={product.category_path || '--'} />
              <KVTile label="Audience" value={product.audience?.join(', ') || '--'} />
            </div>
          </div>

          <div className="space-y-4 rounded-lg border border-border bg-subtle-panel/20 p-4">
            <h3 className="type-label-mono flex items-center gap-1.5 uppercase">
              <span className="size-1.5 rounded-full bg-success" />
              AI &amp; Semantic Enrichment
            </h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <KVTile
                label="Intent Attributes"
                value={
                  product.intent_attributes?.length ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {product.intent_attributes.map((attr) => (
                        <Badge key={attr} tone="accent" className="text-xs font-normal">
                          {attr}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    '--'
                  )
                }
              />
              <KVTile
                label="Style Tags"
                value={
                  product.style_tags?.length ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {product.style_tags.map((tag) => (
                        <Badge key={tag} tone="neutral" className="text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    '--'
                  )
                }
              />
              <KVTile
                label="AI Discovery Tags"
                value={
                  product.ai_discovery_tags?.length ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {product.ai_discovery_tags.map((tag) => (
                        <Badge key={tag} tone="info" className="text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    '--'
                  )
                }
              />
              <KVTile
                label="Suggested Bundles"
                value={
                  product.suggested_bundles?.length ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {product.suggested_bundles.map((bundle) => (
                        <Badge key={bundle} tone="success" className="text-xs font-normal">
                          {bundle}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    '--'
                  )
                }
              />
            </div>
            <div className="pt-2">
              <KVTile
                label="SEO Keywords"
                value={
                  product.seo_keywords?.length ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {product.seo_keywords.map((kw) => (
                        <span
                          key={kw}
                          className="rounded-full border border-border bg-background-elevated px-2 py-0.5 text-xs text-secondary"
                        >
                          {kw}
                        </span>
                      ))}
                    </div>
                  ) : (
                    '--'
                  )
                }
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface SourceRecordListProps {
  records: DataEnrichmentSourceRecordInput[];
}

function SourceRecordList({ records }: Readonly<SourceRecordListProps>) {
  return (
    <div className="divide-y divide-divider overflow-auto">
      {records.map((record, index) => {
        const badgeValue = record.id ?? record.source_url;
        return (
          <div
            key={record.id ?? record.source_url ?? index}
            className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accent/[0.04]"
          >
            <span className="w-6 shrink-0 font-mono text-xs text-muted">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="type-body-sm truncate font-medium">{recordTitle(record)}</div>
              <div className="type-caption flex items-center gap-2">
                {record.source_url ? (
                  <a
                    href={record.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate text-accent opacity-80 hover:underline"
                    title={record.source_url}
                  >
                    {record.source_url}
                  </a>
                ) : null}
              </div>
            </div>
            {badgeValue ? (
              <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-60">
                #{badgeValue}
              </Badge>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
