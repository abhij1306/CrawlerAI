'use client';

import { Copy, Download, Loader2, X } from 'lucide-react';
import Image from 'next/image';
import React from 'react';

import { Badge, Button } from '../../components/ui/primitives';
import type { ProductIntelligenceDiscoveryResponse } from '../../lib/api/types';
import { decodeUrlsForDisplay } from '../../lib/crawl/format';
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
  return (
    <Image
      src={src}
      alt={alt}
      className={className}
      fill
      sizes="(max-width: 768px) 50vw, 180px"
      unoptimized
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
    <>
      <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="border-border bg-background-elevated fixed top-1/2 left-1/2 z-50 flex max-h-[80vh] w-[640px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-md border shadow-xl">
        <div className="border-divider flex items-center justify-between border-b px-4 py-3">
          <h3 className="type-subheading">Raw JSON</h3>
          <Button type="button" variant="quiet" size="icon" onClick={onClose} aria-label="Close">
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre className="crawl-terminal crawl-terminal-json text-xs leading-relaxed">
            {syntaxHighlightJsonNodes(text)}
          </pre>
        </div>
        <div className="border-divider flex items-center justify-end gap-2 border-t px-4 py-3">
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
        </div>
      </div>
    </>
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
    <div className="border-accent/30 bg-accent-subtle text-foreground flex flex-wrap items-center gap-3 rounded-md border px-4 py-3 text-xs">
      <Loader2 className="text-accent size-4 animate-spin" aria-hidden="true" />
      <div className="min-w-[180px] flex-1">
        <div className="font-medium">{providerLabel} discovery running</div>
        <div className="text-muted mt-0.5">
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
        <div className="border-accent/25 bg-accent-subtle size-12 rounded-full border" />
        <Loader2
          className="text-accent absolute top-1/2 left-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin"
          aria-hidden="true"
        />
      </div>
      <div>
        <div className="text-foreground text-sm font-medium">
          {providerLabel} is searching product candidates
        </div>
        <div className="text-muted mt-1 max-w-[520px] text-xs leading-5">
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
    <div className="border-divider bg-background-alt rounded-md border px-3 py-2">
      <div className="text-foreground flex items-center gap-2 text-xs font-medium">
        <span className="bg-accent size-1.5 rounded-full" />
        {label}
      </div>
      <div className="text-muted mt-1 text-xs">{detail}</div>
    </div>
  );
}
