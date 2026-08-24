import { ExternalLink, Loader2 } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Ref } from 'react';

import { KVTile } from '../../components/ui/patterns';
import { Badge } from '../../components/ui/primitives';
import { SafeExternalLink } from '../../components/ui/safe-external-link';
import type { EnrichedProduct } from '../../lib/api/data-enrichment';
import { cn } from '../../lib/utils';

function formatPriceObject(value: Record<string, unknown>) {
  const amount = value.amount ?? value.price_min;
  const currency = (value.currency as string) || '';
  return typeof amount === 'number' ? `${currency} ${amount.toFixed(2)}`.trim() : null;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value !== 'object') return String(value);
  const record = value as Record<string, unknown>;
  return formatPriceObject(record) ?? JSON.stringify(record);
}

interface EnrichedProductSidebarProps {
  products: EnrichedProduct[];
  resolvedProductId: number | null;
  onSelect: (id: number) => void;
}

export function EnrichedProductSidebar({
  products,
  resolvedProductId,
  onSelect,
}: Readonly<EnrichedProductSidebarProps>) {
  const rowGapPx = 4;
  const [rowHeightPx, setRowHeightPx] = useState(92);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(520);
  const [scrollContainer, setScrollContainer] = useState<HTMLDivElement | null>(null);
  const firstRowRef = useRef<HTMLButtonElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const shouldVirtualize = products.length > 80;
  const virtualRowHeightPx = rowHeightPx + rowGapPx;
  const productWindowKey = products.map((p) => p.id).join(',');
  const [prevWindowKey, setPrevWindowKey] = useState(productWindowKey);
  if (productWindowKey !== prevWindowKey) {
    setPrevWindowKey(productWindowKey);
    setScrollTop(0);
  }
  const visibleRange = useMemo(() => {
    if (!shouldVirtualize) {
      return { start: 0, end: products.length, topSpacer: 0, bottomSpacer: 0 };
    }
    const overscan = 6;
    const start = Math.max(0, Math.floor(scrollTop / virtualRowHeightPx) - overscan);
    const visibleCount = Math.ceil(viewportHeight / virtualRowHeightPx) + overscan * 2;
    const end = Math.min(products.length, start + visibleCount);
    return {
      start,
      end,
      topSpacer: start * virtualRowHeightPx,
      bottomSpacer: Math.max(0, (products.length - end) * virtualRowHeightPx),
    };
  }, [products.length, scrollTop, shouldVirtualize, viewportHeight, virtualRowHeightPx]);
  const visibleProducts = useMemo(
    () => (shouldVirtualize ? products.slice(visibleRange.start, visibleRange.end) : products),
    [products, shouldVirtualize, visibleRange.end, visibleRange.start],
  );
  const setScrollContainerRef = useCallback((node: HTMLDivElement | null) => {
    setScrollContainer(node);
    if (node) {
      setViewportHeight(node.clientHeight || 520);
    }
  }, []);
  const handleScroll = useCallback(
    (event: React.UIEvent<HTMLDivElement>) => {
      if (!shouldVirtualize || scrollFrameRef.current !== null) {
        return;
      }
      const node = event.currentTarget;
      const nextScrollTop = node.scrollTop;
      const nextViewportHeight = node.clientHeight;
      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = null;
        setScrollTop(nextScrollTop);
        setViewportHeight(nextViewportHeight);
      });
    },
    [shouldVirtualize],
  );

  useEffect(() => {
    scrollContainer?.scrollTo({ top: 0 });
  }, [productWindowKey, scrollContainer]);

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!scrollContainer || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setViewportHeight(entry.contentRect.height || 520);
      }
    });
    observer.observe(scrollContainer);
    return () => observer.disconnect();
  }, [scrollContainer]);

  useEffect(() => {
    const node = firstRowRef.current;
    if (!node) {
      return;
    }
    const updateRowHeight = () => setRowHeightPx(node.getBoundingClientRect().height || 92);
    updateRowHeight();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(updateRowHeight);
    observer.observe(node);
    return () => observer.disconnect();
  }, [visibleProducts]);

  return (
    <div className="flex min-h-0 w-full shrink-0 flex-col bg-background-alt/10 lg:w-80">
      <div className="border-b border-divider bg-subtle-panel/30 p-3">
        <span className="type-caption-mono uppercase">Record Selector ({products.length})</span>
      </div>
      <div
        ref={setScrollContainerRef}
        className="flex-1 overflow-y-auto p-2"
        onScroll={handleScroll}
      >
        {visibleRange.topSpacer ? <div style={{ height: visibleRange.topSpacer }} /> : null}
        <div className="space-y-1">
          {visibleProducts.map((product) => (
            <EnrichedProductSidebarRow
              key={product.id}
              measureRef={product.id === visibleProducts[0]?.id ? firstRowRef : undefined}
              product={product}
              active={product.id === resolvedProductId}
              onSelect={onSelect}
            />
          ))}
        </div>
        {visibleRange.bottomSpacer ? <div style={{ height: visibleRange.bottomSpacer }} /> : null}
      </div>
    </div>
  );
}

const EnrichedProductSidebarRow = memo(function EnrichedProductSidebarRow({
  measureRef,
  product,
  active,
  onSelect,
}: Readonly<{
  measureRef?: Ref<HTMLButtonElement>;
  product: EnrichedProduct;
  active: boolean;
  onSelect: (id: number) => void;
}>) {
  const isProcessing = product.status === 'pending' || product.status === 'running';
  const title = product.source_url
    ? product.source_url.replace(/^https?:\/\/(www\.)?/, '')
    : `Record #${product.source_record_id}`;
  return (
    <button
      ref={measureRef}
      type="button"
      onClick={() => onSelect(product.id)}
      className={cn(
        'flex w-full flex-col gap-1.5 rounded-md border p-3 text-left transition-colors',
        active
          ? 'border-accent bg-accent-subtle/50'
          : 'border-border bg-background hover:bg-background-elevated',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-base opacity-75">
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
});

interface EnrichedProductDetailProps {
  product: EnrichedProduct | null;
}

function displayValue(value: string | null) {
  return value || '--';
}

function displayList(values: string[] | null) {
  return values?.join(', ') || '--';
}

export function EnrichedProductDetail({ product }: Readonly<EnrichedProductDetailProps>) {
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
            <Badge tone="neutral" className="font-mono text-base">
              Record #{product.source_record_id}
            </Badge>
          </div>
          {product.source_url ? (
            <SafeExternalLink
              href={product.source_url}
              className="type-body-sm mt-1 flex items-center gap-1 truncate text-accent hover:underline"
            >
              {product.source_url}
              <ExternalLink className="size-3 shrink-0" />
            </SafeExternalLink>
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
              <KVTile label="Color Family" value={displayValue(product.color_family)} />
              <KVTile label="Size Normalized" value={displayList(product.size_normalized)} />
              <KVTile label="Size System" value={displayValue(product.size_system)} />
              <KVTile label="Gender Normalized" value={displayValue(product.gender_normalized)} />
              <KVTile
                label="Materials Normalized"
                value={displayList(product.materials_normalized)}
              />
              <KVTile label="Availability" value={displayValue(product.availability_normalized)} />
            </div>
          </div>

          <div className="space-y-4 rounded-lg border border-border bg-subtle-panel/20 p-4">
            <h3 className="type-label-mono flex items-center gap-1.5 uppercase">
              <span className="size-1.5 rounded-full bg-info" />
              Taxonomy &amp; Context
            </h3>
            <div className="grid grid-cols-1 gap-4">
              <KVTile label="Category Path" value={displayValue(product.category_path)} />
              <KVTile label="Audience" value={displayList(product.audience)} />
            </div>
          </div>

          <div className="space-y-4 rounded-lg border border-border bg-subtle-panel/20 p-4">
            <h3 className="type-label-mono flex items-center gap-1.5 uppercase">
              <span className="size-1.5 rounded-full bg-success" />
              AI &amp; Semantic Enrichment
            </h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
              <TagTile label="Intent Attributes" values={product.intent_attributes} tone="accent" />
              <TagTile label="Style Tags" values={product.style_tags} tone="neutral" />
              <TagTile label="AI Discovery Tags" values={product.ai_discovery_tags} tone="info" />
              <TagTile
                label="Suggested Bundles"
                values={product.suggested_bundles}
                tone="success"
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
                          className="rounded-full border border-border bg-background-elevated px-2 py-0.5 text-base text-secondary"
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

function TagTile({
  label,
  values,
  tone,
}: Readonly<{
  label: string;
  values: string[] | null | undefined;
  tone: 'accent' | 'neutral' | 'info' | 'success';
}>) {
  return (
    <KVTile
      label={label}
      value={
        values?.length ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {values.map((value) => (
              <Badge key={value} tone={tone} className="text-base font-normal">
                {value}
              </Badge>
            ))}
          </div>
        ) : (
          '--'
        )
      }
    />
  );
}
