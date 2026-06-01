'use client';

import {
  Check,
  CheckCircle2,
  ChevronDown,
  Code2,
  ExternalLink,
  ImageOff,
  Layers,
} from 'lucide-react';

import { Badge } from '../../components/ui/primitives';
import { cn } from '../../lib/utils';
import { ExternalCandidateImage } from './product-intelligence-components';
import type { ProductIntelligenceController } from './use-product-intelligence';
import {
  candidateConfidence,
  formatPrice,
  isRecord,
  stringField,
} from './product-intelligence-utils';
import type { CandidateGroup, ProductIntelligenceCandidate } from './product-intelligence-utils';

export function CandidateGroupSection({
  group,
  groupIndex,
  controller,
}: {
  group: CandidateGroup;
  groupIndex: number;
  controller: ProductIntelligenceController;
}) {
  return (
    <details className="group" open={groupIndex === 0}>
      <summary className="hover:bg-background-alt/50 flex cursor-pointer list-none items-center gap-4 px-4 py-3 transition-colors select-none">
        <div className="border-divider bg-background text-muted group-open:bg-accent group-open:border-accent type-caption-mono flex size-6 shrink-0 items-center justify-center rounded-full border group-open:!text-white">
          {group.candidates.length}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="type-body text-foreground truncate" title={group.sourceTitle}>
              {group.sourceTitle}
            </span>
            <Badge tone="neutral" className="h-4 px-1.5 opacity-70">
              Source
            </Badge>
          </div>
          <div className="mt-0.5 flex items-center gap-3">
            {group.sourceBrand && group.sourceBrand !== '--' ? (
              <span className="type-caption flex items-center gap-1.5">
                <Layers className="size-3 opacity-50" />
                {group.sourceBrand}
              </span>
            ) : null}
            {group.sourceBrand && group.sourceBrand !== '--' && group.sourcePrice ? (
              <span className="bg-divider size-1 rounded-full" />
            ) : null}
            {group.sourcePrice ? (
              <span className="type-caption-mono text-foreground text-sm">
                {formatPrice(group.sourcePrice, group.sourceCurrency)}
              </span>
            ) : null}
            {group.sourceUrl ? (
              <>
                <span className="bg-divider size-1 rounded-full" />
                <a
                  href={group.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link-accent type-caption truncate"
                  title={group.sourceUrl}
                >
                  Source PDP
                </a>
              </>
            ) : null}
          </div>
        </div>
        <ChevronDown className="text-muted size-4 shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <div className="bg-background-alt/30 border-divider grid grid-cols-1 gap-4 border-t p-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {group.candidates.map((candidate) => (
          <CandidateCard key={candidate.url} candidate={candidate} controller={controller} />
        ))}
      </div>
    </details>
  );
}

function CandidateCard({
  candidate,
  controller,
}: {
  candidate: ProductIntelligenceCandidate;
  controller: ProductIntelligenceController;
}) {
  const selected = controller.uniqueSelectedUrls.includes(candidate.url);
  const score = candidateConfidence(candidate);
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const record = isRecord(intelligence.canonical_record) ? intelligence.canonical_record : {};
  const imageUrl = stringField(record.image_url);
  const title = stringField(record.title) || candidate.url;
  const brand = stringField(record.brand) || candidate.source_brand;

  return (
    <div
      className={cn(
        'group/card border-border bg-panel hover:border-accent/40 hover:shadow-card relative flex flex-col justify-between rounded-md border p-3 transition-all',
        selected && 'border-accent/60 bg-accent-soft shadow-card',
      )}
    >
      <div className="flex flex-col">
        <CandidateImage imageUrl={imageUrl} title={title}>
          <div className="absolute top-2 left-2 z-10">
            <label className="focus-within:ring-accent/25 hover:border-border-strong flex size-6 cursor-pointer items-center justify-center rounded-md border border-transparent bg-transparent transition-[border-color,box-shadow] focus-within:ring-2">
              <input
                type="checkbox"
                checked={selected}
                onChange={(event) => {
                  event.stopPropagation();
                  if (candidate.url) controller.toggleUrl(candidate.url);
                }}
                aria-label={`Select product: ${title}`}
                className="sr-only"
              />
              <div
                className={cn(
                  'flex size-4 items-center justify-center rounded border shadow-xs transition-colors',
                  selected
                    ? 'bg-accent border-accent text-accent-fg'
                    : 'border-border-strong hover:border-accent bg-transparent text-transparent',
                )}
              >
                {selected ? <Check className="size-3 stroke-[3]" /> : null}
              </div>
            </label>
          </div>
          <div className="absolute top-2 right-2 z-10">
            <ConfidenceBadge score={score} />
          </div>
        </CandidateImage>

        <div className="mt-3 flex min-w-0 flex-col">
          {brand && brand !== '--' ? <div className="type-label truncate">{brand}</div> : null}
          <a
            href={candidate.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group/link type-body-sm text-foreground hover:text-accent mt-1 line-clamp-2 transition-colors"
            title={title}
          >
            {title}
          </a>
          <div className="mt-2 flex flex-col gap-1">
            <div className="type-caption truncate" title={candidate.domain}>
              {candidate.domain}
            </div>
          </div>
        </div>
      </div>

      <div className="border-divider mt-3 grid min-h-5 grid-cols-[auto_1fr_auto] items-center gap-2 border-t pt-1.5">
        <button
          type="button"
          className="focus-ring type-label text-secondary hover:text-foreground inline-flex h-5 items-center gap-1 rounded-xs px-1 transition-colors"
          onClick={() => controller.setJsonModalCandidate(candidate)}
        >
          <Code2 className="mr-1 size-3" />
          Raw JSON
        </button>
        {selected ? (
          <span className="text-success type-label flex h-5 items-center gap-1 justify-self-center">
            <CheckCircle2 className="size-3" />
            Selected
          </span>
        ) : null}
        <a
          href={candidate.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent type-label flex h-5 items-center gap-1 justify-self-end rounded-xs px-1 hover:underline"
        >
          Source
          <ExternalLink className="size-2.5" />
        </a>
      </div>
    </div>
  );
}

function CandidateImage({
  imageUrl,
  title,
  children,
}: {
  imageUrl: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="border-divider hover:shadow-card relative aspect-square w-full shrink-0 overflow-hidden rounded-md border bg-white p-1.5 shadow-xs transition-shadow">
      {imageUrl ? (
        <ExternalCandidateImage
          src={imageUrl}
          alt={title}
          className="size-full object-contain mix-blend-multiply transition-transform duration-300 group-hover/card:scale-[1.03]"
        />
      ) : (
        <div className="text-muted/30 bg-background-alt/20 flex size-full items-center justify-center">
          <ImageOff className="size-8" />
        </div>
      )}
      {children}
    </div>
  );
}

function ConfidenceBadge({ score }: { score: number }) {
  return (
    <div
      className={cn(
        'type-caption-mono rounded-md border px-1.5 py-0.5 font-normal !text-white shadow-xs',
        score >= 0.6
          ? 'bg-success border-success'
          : score >= 0.4
            ? 'bg-warning border-warning'
            : 'border-zinc-500 bg-zinc-500 dark:border-zinc-600 dark:bg-zinc-600',
      )}
    >
      {Math.round(score * 100)}%
    </div>
  );
}
