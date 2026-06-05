'use client';

import { ClipboardCheck, Sparkles } from 'lucide-react';

import { Button } from '../ui/primitives';

export function CrawlActionButtons({
  canSubmit,
  canSubmitDesign,
  designSubmitting,
  isSubmitting,
  onPageAudit,
  onDesignCrawl,
}: Readonly<{
  canSubmit: boolean;
  canSubmitDesign: boolean;
  designSubmitting: boolean;
  isSubmitting: boolean;
  onPageAudit: () => void;
  onDesignCrawl: () => void;
}>) {
  return (
    <div className="flex flex-wrap gap-2 justify-self-start lg:justify-self-end">
      <Button
        variant="neutral"
        size="sm"
        type="button"
        disabled={!canSubmitDesign}
        className="min-w-[112px]"
        onClick={onPageAudit}
      >
        <ClipboardCheck className="size-3" />
        Page Audit
      </Button>
      <Button
        variant="neutral"
        size="sm"
        type="button"
        disabled={!canSubmitDesign}
        className="min-w-[120px]"
        onClick={onDesignCrawl}
      >
        {designSubmitting ? (
          <>
            <span
              className="inline-block size-1.5 animate-pulse rounded-full bg-current opacity-80"
              aria-hidden="true"
            />
            Starting…
          </>
        ) : (
          <>
            <Sparkles className="size-3" />
            Design Crawl
          </>
        )}
      </Button>
      <Button
        variant="action"
        size="sm"
        type="submit"
        disabled={!canSubmit}
        className="min-w-[120px]"
      >
        {isSubmitting ? (
          <>
            <span
              className="inline-block size-1.5 animate-pulse rounded-full bg-current opacity-80"
              aria-hidden="true"
            />
            Starting…
          </>
        ) : (
          'Start Crawl'
        )}
      </Button>
    </div>
  );
}
