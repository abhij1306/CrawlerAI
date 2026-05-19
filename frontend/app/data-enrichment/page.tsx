'use client';

// Next.js App Router entrypoint for `/data-enrichment`; invoked by file-system routing.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, History, Loader2, Play, RefreshCcw } from 'lucide-react';
import { useMemo, useState } from 'react';

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
import { api } from '../../lib/api';
import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';
import type {
  DataEnrichmentJob,
  DataEnrichmentSourceRecordInput,
  EnrichedProduct,
} from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { cn } from '../../lib/utils';

type PrefillPayload = {
  source_run_id?: number | null;
  records?: DataEnrichmentSourceRecordInput[];
};

const ENRICHED_FIELD_LABELS: Array<[keyof EnrichedProduct, string]> = [
  ['price_normalized', 'Price'],
  ['color_family', 'Color'],
  ['size_normalized', 'Size'],
  ['size_system', 'Size system'],
  ['gender_normalized', 'Gender'],
  ['materials_normalized', 'Materials'],
  ['availability_normalized', 'Availability'],
  ['seo_keywords', 'SEO keywords'],
  ['category_path', 'Category'],
  ['intent_attributes', 'Intent'],
  ['audience', 'Audience'],
  ['style_tags', 'Style'],
  ['ai_discovery_tags', 'Discovery tags'],
  ['suggested_bundles', 'Bundles'],
];

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
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);

  const sourceRecords = initialPrefill.records ?? [];
  const sourceRecordIds = sourceRecords
    .map((record) => record.id)
    .filter((id): id is number => typeof id === 'number');

  const jobsQuery = useQuery({
    queryKey: ['data-enrichment-jobs'],
    queryFn: () => api.listDataEnrichmentJobs({ limit: 20 }),
    refetchInterval: 4000,
  });

  const historyItems: HistoryItem[] = useMemo(() => {
    return (jobsQuery.data ?? []).map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
      meta: `${Number(job.summary?.accepted_count ?? 0)} records enriched`,
    }));
  }, [jobsQuery.data]);

  const defaultJobId = sourceRecords.length ? null : (jobsQuery.data?.[0]?.id ?? null);
  const resolvedJobId = activeJobId ?? defaultJobId;
  const detailQuery = useQuery({
    queryKey: ['data-enrichment-job', resolvedJobId],
    queryFn: () => api.getDataEnrichmentJob(resolvedJobId ?? 0),
    enabled: resolvedJobId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job?.status ?? '');
      return status === 'pending' || status === 'running' ? 2500 : false;
    },
  });
  const activeJob =
    detailQuery.data?.job ?? jobsQuery.data?.find((job) => job.id === resolvedJobId) ?? null;
  const isRunning = activeJob?.status === 'pending' || activeJob?.status === 'running';

  const products = detailQuery.data?.enriched_products ?? [];
  const resolvedProductId = selectedProductId ?? products[0]?.id ?? null;
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
      setError('');
      setActiveJobId(job.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['data-enrichment-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['data-enrichment-job', job.id] }),
      ]);
    },
    onError: (mutationError) => {
      setError(
        mutationError instanceof Error ? mutationError.message : 'Unable to start enrichment.',
      );
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
              style={{ fontSize: '12px' }}
              className="border-border bg-background-elevated text-foreground hover:bg-accent/[0.04] inline-flex h-7 cursor-pointer items-center gap-2 rounded-[var(--radius-md)] border px-2.5 transition-colors font-semibold"
            >
              <input
                type="checkbox"
                checked={llmEnabled}
                onChange={(event) => setLlmEnabled(event.target.checked)}
                className="border-divider text-accent focus:ring-accent h-3 w-3 cursor-pointer rounded"
              />
              LLM Enrichment
            </label>
            <Button
              type="button"
              variant="accent"
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
        <header className="border-divider flex flex-wrap items-center justify-between gap-4 border-b px-4 py-3">
          <div className="flex items-center gap-3">
            <h2 className="type-label-mono">
              {products.length > 0 ? 'ENRICHED OUTPUT' : 'SELECTED RECORDS'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void detailQuery.refetch()}
              disabled={!resolvedJobId || detailQuery.isFetching}
              className="text-muted hover:text-foreground type-label-mono px-2"
            >
              <RefreshCcw className="mr-1.5 size-3" />
              Refresh
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setHistoryOpen(true)}
              aria-label="Enrichment History"
              className="text-muted hover:text-foreground w-8 p-0"
            >
              <History className="size-3.5" />
            </Button>
          </div>
        </header>

        {isRunning && completedCount === 0 ? (
          <EnrichmentTableLoading llmEnabled={Boolean(activeJob?.options?.llm_enabled)} />
        ) : detailQuery.isLoading && !isRunning ? (
          <DataRegionLoading count={8} className="px-0" />
        ) : products.length ? (
          <div className="flex flex-col lg:flex-row h-[600px] divide-y lg:divide-y-0 lg:divide-x divide-divider">
            {/* Sidebar: List of products */}
            <div className="w-full lg:w-80 shrink-0 flex flex-col min-h-0 bg-background-alt/10">
              <div className="border-divider border-b p-3 bg-subtle-panel/30">
                <span className="type-caption-mono text-muted uppercase">Record Selector ({products.length})</span>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {products.map((product) => {
                  const isActive = product.id === resolvedProductId;
                  const isProcessing = product.status === 'pending' || product.status === 'running';
                  const title = product.source_url ? product.source_url.replace(/^https?:\/\/(www\.)?/, '') : `Record #${product.source_record_id}`;
                  const formattedPrice = formatValue(product.price_normalized);

                  return (
                    <button
                      key={product.id}
                      type="button"
                      onClick={() => setSelectedProductId(product.id)}
                      className={cn(
                        "w-full text-left rounded-[var(--radius-md)] border p-3 transition-colors flex flex-col gap-1.5",
                        isActive
                          ? "border-accent bg-accent-subtle/50"
                          : "border-border bg-background hover:bg-background-elevated"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-75">
                          #{product.source_record_id}
                        </Badge>
                        {isProcessing ? (
                          <div className="flex items-center gap-1 opacity-60">
                            <Loader2 className="text-accent size-3 animate-spin" />
                            <span className="type-caption-mono text-[10px]">Processing</span>
                          </div>
                        ) : null}
                      </div>
                      <div className="type-body-sm font-medium truncate w-full text-foreground" title={product.source_url}>
                        {title}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Content: Selected Product Detailed View */}
            <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-background">
              {selectedProduct ? (
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                  {/* Header info */}
                  <div className="border-divider border-b pb-4">
                    <div className="flex items-center gap-2">
                      <span className="type-heading-3">Enriched Record Details</span>
                      <Badge tone="neutral" className="font-mono text-xs">
                        Record #{selectedProduct.source_record_id}
                      </Badge>
                    </div>
                    {selectedProduct.source_url ? (
                      <a
                        href={selectedProduct.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent type-body-sm flex items-center gap-1 mt-1 hover:underline truncate"
                      >
                        {selectedProduct.source_url}
                        <ExternalLink className="size-3 shrink-0" />
                      </a>
                    ) : null}
                  </div>

                  {/* Detail Groups */}
                  <div className="space-y-6">
                    {/* Core Attributes (Row 1: Full width) */}
                    <div className="border-border bg-subtle-panel/20 rounded-[var(--radius-lg)] border p-4 space-y-4">
                      <h3 className="type-label-mono text-muted flex items-center gap-1.5 uppercase">
                        <span className="bg-accent size-1.5 rounded-full" />
                        Core Attributes
                      </h3>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                        <KVTile label="Price (Normalized)" mono value={formatValue(selectedProduct.price_normalized) || '--'} />
                        <KVTile label="Color Family" value={selectedProduct.color_family || '--'} />
                        <KVTile label="Size Normalized" value={selectedProduct.size_normalized?.join(', ') || '--'} />
                        <KVTile label="Size System" value={selectedProduct.size_system || '--'} />
                        <KVTile label="Gender Normalized" value={selectedProduct.gender_normalized || '--'} />
                        <KVTile label="Materials Normalized" value={selectedProduct.materials_normalized?.join(', ') || '--'} />
                        <KVTile label="Availability" value={selectedProduct.availability_normalized || '--'} />
                      </div>
                    </div>

                    {/* Taxonomy & Context (Row 2: Full width) */}
                    <div className="border-border bg-subtle-panel/20 rounded-[var(--radius-lg)] border p-4 space-y-4">
                      <h3 className="type-label-mono text-muted flex items-center gap-1.5 uppercase">
                        <span className="bg-info size-1.5 rounded-full" />
                        Taxonomy & Context
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="md:col-span-2">
                          <KVTile label="Category Path" value={selectedProduct.category_path || '--'} />
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 md:col-span-1">
                          <KVTile label="Audience" value={selectedProduct.audience?.join(', ') || '--'} />
                          <KVTile label="Taxonomy Version" value={selectedProduct.taxonomy_version || '--'} />
                        </div>
                      </div>
                    </div>

                    {/* Semantic & AI Insights (Row 3: Full width) */}
                    <div className="border-border bg-subtle-panel/20 rounded-[var(--radius-lg)] border p-4 space-y-4">
                      <h3 className="type-label-mono text-muted flex items-center gap-1.5 uppercase">
                        <span className="bg-success size-1.5 rounded-full" />
                        AI & Semantic Enrichment
                      </h3>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                        <KVTile
                          label="Intent Attributes"
                          value={
                            selectedProduct.intent_attributes?.length ? (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {selectedProduct.intent_attributes.map((attr) => (
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
                            selectedProduct.style_tags?.length ? (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {selectedProduct.style_tags.map((tag) => (
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
                            selectedProduct.ai_discovery_tags?.length ? (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {selectedProduct.ai_discovery_tags.map((tag) => (
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
                            selectedProduct.suggested_bundles?.length ? (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {selectedProduct.suggested_bundles.map((bundle) => (
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
                            selectedProduct.seo_keywords?.length ? (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {selectedProduct.seo_keywords.map((kw) => (
                                  <span key={kw} className="bg-background-elevated border-border text-secondary rounded-full border px-2 py-0.5 text-xs">
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
              ) : (
                <div className="flex-1 grid place-items-center text-center p-6">
                  <div className="text-muted type-body">Select a record from the list to view full enrichment details.</div>
                </div>
              )}
            </div>
          </div>
        ) : sourceRecords.length ? (
          <div className="divide-divider divide-y overflow-auto">
            {sourceRecords.map((record, index) => {
              const badgeValue = record.id ?? record.source_url;
              return (
                <div
                  key={record.id ?? record.source_url ?? index}
                  className="hover:bg-accent/[0.04] flex items-center gap-3 px-4 py-2.5 transition-colors"
                >
                  <span className="text-muted w-6 shrink-0 font-mono text-xs">{index + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="type-body-sm truncate font-medium">{recordTitle(record)}</div>
                    <div className="text-muted type-caption flex items-center gap-2">
                      {record.source_url ? (
                        <a
                          href={record.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent truncate opacity-80 hover:underline"
                          title={record.source_url}
                        >
                          {record.source_url}
                        </a>
                      ) : null}
                    </div>
                  </div>
                  {badgeValue ? (
                    <Badge
                      tone="neutral"
                      className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-60"
                    >
                      #{badgeValue}
                    </Badge>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <DataRegionEmpty
            title="No records selected"
            description="Open an ecommerce detail run and send selected records here to begin enrichment."
          />
        )}
      </TableSurface>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={resolvedJobId}
        onSelect={(id) => setActiveJobId(id)}
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
