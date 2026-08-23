import { Copy, Download, Loader2 } from 'lucide-react';
import React from 'react';

import { AppDialog } from '../../components/ui/dialog';
import { Badge, Button } from '../../components/ui/primitives';
import type { ProductIntelligenceDiscoveryResponse } from '../../lib/api/product-intelligence';
import { decodeUrlsForDisplay } from '../../lib/crawl/format';
import { isSafeHttpUrl } from '../../lib/format/domain';
import { syntaxHighlightJsonNodes } from '../../lib/ui/syntax';
import { isRecord, searchProviderLabel } from './product-intelligence-utils';

function hideBrokenImage(event: React.SyntheticEvent<HTMLImageElement>): void {
  event.currentTarget.style.display = 'none';
}

export function ExternalCandidateImage({
  src,
  alt,
  className,
}: Readonly<{
  src: string;
  alt: string;
  className: string;
}>) {
  if (!isSafeHttpUrl(src)) return null;
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      className={`absolute inset-0 ${className}`}
      onError={hideBrokenImage}
    />
  );
}

export function JsonModal({
  candidate,
  onClose,
}: Readonly<{
  candidate: ProductIntelligenceDiscoveryResponse['candidates'][number];
  onClose: () => void;
}>) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const hasIntelligence = Object.keys(intelligence).length > 0;
  const text = JSON.stringify(
    decodeUrlsForDisplay(hasIntelligence ? intelligence : (candidate.payload ?? {})),
    null,
    2,
  );

  return (
    <AppDialog
      open
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
      title="Raw JSON"
      footer={
        <>
          <Button
            type="button"
            variant="quiet"
            size="sm"
            onClick={() => void navigator.clipboard.writeText(text)}
          >
            <Copy className="mr-1 size-3" /> Copy
          </Button>
          <Button
            type="button"
            variant="download"
            size="sm"
            onClick={() => {
              const blob = new Blob([text], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `candidate-${candidate.domain || 'data'}.json`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            <Download className="mr-1 size-3" /> Download
          </Button>
        </>
      }
    >
      <div className="p-4">
        <pre className="crawl-terminal crawl-terminal-json text-xs leading-relaxed">
          {syntaxHighlightJsonNodes(text)}
        </pre>
      </div>
    </AppDialog>
  );
}

export function DiscoveryStatus({
  provider,
  sourceCount,
  maxCandidates,
}: Readonly<{
  provider: string;
  sourceCount: number;
  maxCandidates: number;
}>) {
  const providerLabel = searchProviderLabel(provider);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-accent/30 bg-accent-subtle px-4 py-3 text-xs text-foreground">
      <Loader2 className="size-4 animate-spin text-accent" aria-hidden="true" />
      <div className="min-w-[180px] flex-1">
        <div className="font-medium">{providerLabel} discovery running</div>
        <div className="mt-0.5 text-muted">
          Searching {sourceCount} source product{sourceCount === 1 ? '' : 's'}, filtering source
          domains, ranking brand sites before aggregators.
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone="info" className="h-5 px-1.5 text-xs">
          {providerLabel}
        </Badge>
        <Badge tone="neutral" className="h-5 px-1.5 text-xs">
          Max {maxCandidates}/product
        </Badge>
      </div>
    </div>
  );
}

export function DiscoveryTableLoading({ provider }: Readonly<{ provider: string }>) {
  const providerLabel = searchProviderLabel(provider);
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <div className="relative">
        <div className="size-12 rounded-full border border-accent/25 bg-accent-subtle" />
        <Loader2
          className="absolute top-1/2 left-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-accent"
          aria-hidden="true"
        />
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">
          {providerLabel} is searching product candidates
        </div>
        <div className="mt-1 max-w-[520px] text-xs leading-5 text-muted">
          Querying Shopping, store links, and organic fallback, removing blocked/source domains,
          classifying domains, and scoring each result from title, brand, identifiers, price, and
          source authority.
        </div>
      </div>
      <div className="grid w-full max-w-[560px] gap-2 text-left sm:grid-cols-3">
        <DiscoveryLoadingStep label="Search" detail="Shopping-first request active" />
        <DiscoveryLoadingStep label="Filter" detail="Source domain excluded" />
        <DiscoveryLoadingStep label="Rank" detail="Evidence first" />
      </div>
    </div>
  );
}

function DiscoveryLoadingStep({ label, detail }: Readonly<{ label: string; detail: string }>) {
  return (
    <div className="rounded-md border border-divider bg-background-alt px-3 py-2">
      <div className="flex items-center gap-2 text-xs font-medium text-foreground">
        <span className="size-1.5 rounded-full bg-accent" />
        {label}
      </div>
      <div className="mt-1 text-xs text-muted">{detail}</div>
    </div>
  );
}
