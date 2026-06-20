import type { ReactNode } from 'react';
import { Plus } from 'lucide-react';

import type { CrawlRun } from '../../lib/api/types';
import { getDomain, isSafeHttpUrl } from '../../lib/format/domain';
import { InlineAlert, PageHeader, SectionHeader } from '../ui/patterns';
import { Button, Card } from '../ui/primitives';

type RefreshPanelError = {
  key: string;
  label: string;
  error: unknown;
};

type RunPageHeaderProps = {
  run: CrawlRun | undefined;
  onNewCrawl: () => void;
};

export function RunPageHeader({ run, onNewCrawl }: Readonly<RunPageHeaderProps>) {
  const title: ReactNode = run?.url && isSafeHttpUrl(run.url) ? (
    <span className="inline-flex items-baseline gap-1.5">
      Run Details:{' '}
      <a
        href={run.url}
        target="_blank"
        rel="noreferrer"
        className="link-accent type-body leading-inherit underline-offset-2 hover:underline"
      >
        {getDomain(run.url).toLowerCase()}
      </a>
    </span>
  ) : (
    'Crawl Results'
  );

  return (
    <PageHeader
      title={title}
      actions={
        <Button variant="action" type="button" size="sm" onClick={onNewCrawl}>
          <Plus className="size-3" />
          New Crawl
        </Button>
      }
    />
  );
}

export function RunLoadError({
  onNewCrawl,
}: Readonly<{ error: unknown; onNewCrawl: () => void }>) {
  return (
    <div className="page-stack">
      <PageHeader
        title="Crawl Studio"
        actions={
          <Button variant="action" type="button" size="sm" onClick={onNewCrawl}>
            <Plus className="size-3" />
            New Crawl
          </Button>
        }
      />
      <Card className="space-y-3 px-6 py-8">
        <SectionHeader
          title="Unable to Load Crawl"
          description="The run workspace could not be restored."
        />
        <div className="text-danger type-body">
          Unable to load this crawl. Retry or start a new crawl.
        </div>
      </Card>
    </div>
  );
}

export function RunLoadingState({ runId }: Readonly<{ runId: number }>) {
  return (
    <Card className="space-y-3 px-6 py-8">
      <SectionHeader
        title="Loading Crawl"
        description="Fetching run details and restoring the workspace."
      />
      <div className="text-muted type-body leading-relaxed">Run #{runId} is loading.</div>
    </Card>
  );
}

export function RunPanelErrorState({
  panels,
  onRetry,
}: Readonly<{ panels: RefreshPanelError[]; onRetry: () => void }>) {
  if (!panels.length) return null;

  return (
    <Card className="space-y-3">
      <SectionHeader
        title="Some live panels failed to refresh"
        description="Data may be stale until these requests recover."
      />
      <InlineAlert
        message={
          <div className="space-y-1">
            {panels.map((panel) => (
              <div key={panel.key}>
                Unable to refresh {panel.label}:{' '}
                Refresh failed. Retry to restore current data.
              </div>
            ))}
          </div>
        }
      />
      <div>
        <Button variant="neutral" type="button" size="sm" onClick={onRetry}>
          Retry failed panels
        </Button>
      </div>
    </Card>
  );
}
