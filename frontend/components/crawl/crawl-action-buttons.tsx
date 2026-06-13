import { Button } from '../ui/primitives';

export function CrawlActionButtons({
  canSubmit,
  isSubmitting,
}: Readonly<{
  canSubmit: boolean;
  isSubmitting: boolean;
}>) {
  return (
    <div className="flex flex-wrap gap-2 justify-self-start lg:justify-self-end">
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
