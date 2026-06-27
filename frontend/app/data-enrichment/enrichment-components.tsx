import { Loader2 } from 'lucide-react';
import React from 'react';

import { Badge } from '../../components/ui/primitives';

export function EnrichmentStatus({
  sourceCount,
  llmEnabled,
}: Readonly<{
  sourceCount: number;
  llmEnabled: boolean;
}>) {
  return (
    <div className="animate-in fade-in flex flex-wrap items-center gap-3 rounded-md border border-accent/30 bg-accent-subtle px-4 py-3 text-xs text-foreground duration-300">
      <Loader2 className="size-4 animate-spin text-accent" aria-hidden="true" />
      <div className="min-w-[180px] flex-1">
        <div className="font-normal">Enrichment running</div>
        <div className="mt-0.5 text-muted">
          Processing {sourceCount} record{sourceCount === 1 ? '' : 's'}. Normalizing price, color,
          size, and category. {llmEnabled ? 'LLM refinement active.' : 'Deterministic rules only.'}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge
          tone={llmEnabled ? 'accent' : 'neutral'}
          className="h-5 px-1.5 text-xs font-normal tracking-tight uppercase"
        >
          {llmEnabled ? 'LLM ENABLED' : 'RULES ONLY'}
        </Badge>
        <Badge tone="info" className="h-5 px-1.5 text-xs font-normal tracking-tight uppercase">
          {sourceCount} RECORDS
        </Badge>
      </div>
    </div>
  );
}

export function EnrichmentTableLoading({ llmEnabled }: Readonly<{ llmEnabled: boolean }>) {
  return (
    <div className="animate-in fade-in zoom-in-95 flex min-h-[220px] flex-col items-center justify-center gap-4 px-6 py-10 text-center duration-500">
      <div className="relative">
        <div className="size-12 rounded-full border border-accent/25 bg-accent-subtle" />
        <Loader2
          className="absolute top-1/2 left-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-accent"
          aria-hidden="true"
        />
      </div>
      <div>
        <div className="text-sm font-normal text-foreground">
          Analyzing and enriching product records
        </div>
        <div className="mt-1 max-w-[520px] text-xs leading-5 text-muted">
          Executing deterministic attribute matching, category taxonomy alignment, and{' '}
          {llmEnabled ? 'LLM-driven semantic expansion.' : 'rule-based field normalization.'}
        </div>
      </div>
      <div className="grid w-full max-w-[640px] gap-2 text-left sm:grid-cols-2 lg:grid-cols-4">
        <EnrichmentLoadingStep label="Normalize" detail="Price, size & materials" />
        <EnrichmentLoadingStep label="Taxonomy" detail="Google Category match" />
        <EnrichmentLoadingStep label="Attributes" detail="Color & gender labels" />
        <EnrichmentLoadingStep
          label={llmEnabled ? 'LLM Refine' : 'SEO Build'}
          detail={llmEnabled ? 'Intent & semantic tags' : 'Keyword synthesis'}
        />
      </div>
    </div>
  );
}

function EnrichmentLoadingStep({ label, detail }: Readonly<{ label: string; detail: string }>) {
  return (
    <div className="rounded-md border border-divider bg-background-alt/50 px-3 py-2 transition-colors hover:bg-background-alt">
      <div className="flex items-center gap-2 text-xs font-normal tracking-tight text-foreground uppercase">
        <span className="size-1.5 animate-pulse rounded-full bg-accent" />
        {label}
      </div>
      <div className="mt-1 text-xs leading-tight text-muted">{detail}</div>
    </div>
  );
}
