'use client';

import { Code2, ExternalLink, ImageOff, Layers, ChevronDown } from 'lucide-react';

import { Badge, Button } from '../../components/ui/primitives';
import { cn } from '../../lib/utils';
import { ExternalCandidateImage } from './product-intelligence-components';
import type { ProductIntelligenceController } from './use-product-intelligence';
import {
  candidateConfidence,
  formatExtractedPrice,
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
        <div className="border-divider bg-background text-muted group-open:bg-accent group-open:border-accent type-caption-mono flex size-6 shrink-0 items-center justify-center rounded-full border font-bold group-open:text-white">
          {group.candidates.length}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="text-foreground type-body truncate font-medium"
              title={group.sourceTitle}
            >
              {group.sourceTitle}
            </span>
            <Badge tone="neutral" className="type-label-mono h-4 px-1.5 uppercase opacity-60">
              Source
            </Badge>
          </div>
          <div className="mt-0.5 flex items-center gap-3">
            {group.sourceBrand && group.sourceBrand !== '--' ? (
              <span className="text-muted type-caption flex items-center gap-1.5">
                <Layers className="size-3 opacity-50" />
                {group.sourceBrand}
              </span>
            ) : null}
            {group.sourceBrand && group.sourceBrand !== '--' && group.sourcePrice ? (
              <span className="bg-divider h-1 w-1 rounded-full" />
            ) : null}
            {group.sourcePrice ? (
              <span className="text-foreground type-caption-mono font-medium">
                {formatPrice(group.sourcePrice, group.sourceCurrency)}
              </span>
            ) : null}
          </div>
        </div>
        <ChevronDown className="text-muted size-4 shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <div className="bg-background-alt/30 border-divider grid grid-cols-1 gap-3 border-t p-4 md:grid-cols-2 xl:grid-cols-3">
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
  return (
    <div
      className={cn(
        'group/card border-border bg-panel hover:border-accent/40 relative flex flex-col rounded-[var(--radius-md)] border p-3 transition-all hover:shadow-md',
        selected && 'border-accent/60 bg-accent-subtle/20 shadow-sm',
      )}
    >
      <div className="flex gap-4">
        <CandidateImage imageUrl={imageUrl} title={stringField(record.title)} score={score} />
        <div className="flex min-w-0 flex-1 flex-col justify-between py-0.5">
          <div className="space-y-1.5">
            <div className="flex items-start justify-between gap-3">
              <a
                href={candidate.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group/link text-foreground hover:text-accent type-body line-clamp-2 font-normal transition-colors"
              >
                {stringField(record.title) || candidate.url}
              </a>
              <input
                type="checkbox"
                checked={selected}
                onChange={(event) => {
                  event.stopPropagation();
                  if (candidate.url) controller.toggleUrl(candidate.url);
                }}
                aria-label={`Select product for batch crawl: ${stringField(record.title) || candidate.url}`}
                className="border-divider text-accent focus:ring-accent mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded"
              />
            </div>
            <div className="flex flex-col gap-1">
              {stringField(record.price) && stringField(record.price) !== '--' ? (
                <div className="text-foreground type-body font-semibold">
                  {formatExtractedPrice(record.price, record.currency)}
                </div>
              ) : null}
              {stringField(record.brand) || candidate.source_brand ? (
                <div className="text-muted type-label-mono uppercase">
                  {stringField(record.brand) || candidate.source_brand}
                </div>
              ) : null}
            </div>
          </div>
          <div className="text-muted/80 type-caption-mono mt-2 truncate" title={candidate.domain}>
            {candidate.domain}
          </div>
        </div>
      </div>
      <div className="border-divider mt-3 flex items-center justify-between border-t pt-2.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-muted hover:text-accent type-label-mono h-6 px-2 uppercase"
          onClick={() => controller.setJsonModalCandidate(candidate)}
        >
          <Code2 className="mr-1.5 size-3" /> Raw JSON
        </Button>
        <a
          href={candidate.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent type-label-mono flex items-center gap-1 uppercase hover:underline"
        >
          View Source <ExternalLink className="size-2.5" />
        </a>
      </div>
    </div>
  );
}

function CandidateImage({
  imageUrl,
  title,
  score,
}: {
  imageUrl: string;
  title: string;
  score: number;
}) {
  return (
    <div className="border-divider relative aspect-square w-[100px] shrink-0 overflow-hidden rounded-[var(--radius-md)] border bg-white p-1.5 shadow-sm">
      {imageUrl ? (
        <ExternalCandidateImage
          src={imageUrl}
          alt={title}
          className="size-full object-contain mix-blend-multiply"
        />
      ) : (
        <div className="text-muted/30 flex size-full items-center justify-center">
          <ImageOff className="size-8" />
        </div>
      )}
      <div
        className={cn(
          'type-caption-mono absolute right-1.5 bottom-1.5 rounded-md border px-1.5 py-0.5 font-bold shadow-sm',
          score >= 0.6
            ? 'bg-success border-success text-white'
            : score >= 0.4
              ? 'bg-warning border-warning text-white'
              : 'bg-background-elevated text-muted border-divider',
        )}
      >
        {Math.round(score * 100)}%
      </div>
    </div>
  );
}
