import { Link } from 'react-router-dom';
import { ArrowRightCircle, Copy, ExternalLink, Trash2 } from 'lucide-react';

import { Badge, Button, Tooltip } from '../../components/ui/primitives';
import { StatusDot } from '../../components/ui/patterns';
import { SafeExternalLink } from '../../components/ui/safe-external-link';
import { TableCell, TableRow } from '../../components/ui/table';
import type { CrawlRun } from '../../lib/api/types';
import { formatRunsDate as formatDate } from '../../lib/format/date';
import { getDomain } from '../../lib/format/domain';
import { isSubduedStatus, runExecutionLabel, runExecutionTone } from '../../lib/ui/status';
import { cn } from '../../lib/utils';

export function RunRow({
  run,
  pendingDelete,
  onDelete,
}: Readonly<{ run: CrawlRun; pendingDelete: boolean; onDelete: () => void }>) {
  const recordCount =
    typeof run.result_summary?.record_count === 'number' ? run.result_summary.record_count : 0;
  const canDelete = !['pending', 'running', 'paused'].includes(run.status);
  const domain = getDomain(run.url);

  return (
    <TableRow className="group">
      <TableCell className="overflow-visible">
        <div className="flex items-center gap-2.5">
          <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
          <div className="flex min-w-0 items-center gap-2">
            <Tooltip content={run.url} align="start">
              <Link
                to={`/crawl?run_id=${run.id}`}
                className="link-accent block max-w-[280px] truncate font-medium no-underline transition-colors"
              >
                {domain || `Run #${run.id}`}
              </Link>
            </Tooltip>

            <div className="flex items-center gap-1 opacity-10 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void navigator.clipboard.writeText(run.url);
                }}
                className="inline-flex min-h-6 min-w-6 items-center justify-center text-muted transition-colors hover:text-accent"
                title="Copy URL"
                aria-label="Copy URL"
              >
                <Copy className="size-3" />
              </button>
              <SafeExternalLink
                href={run.url}
                className="inline-flex min-h-6 min-w-6 items-center justify-center text-muted transition-colors hover:text-accent"
                title="Open original URL"
                ariaLabel="Open original URL"
              >
                <ExternalLink className="size-3" />
              </SafeExternalLink>
            </div>
          </div>
        </div>
      </TableCell>

      <TableCell>
        <span className="rounded-sm bg-background-elevated px-1.5 py-0.5 text-muted">
          {formatRunType(run.run_type)}
        </span>
      </TableCell>

      <TableCell>
        <Badge
          tone={runExecutionTone(run.status, run.result_summary)}
          flat={isSubduedStatus(run.status)}
        >
          {runExecutionLabel(run.status, run.result_summary)}
        </Badge>
      </TableCell>

      <TableCell className="text-right">
        <span className={cn('tabular-nums', recordCount > 0 ? 'text-foreground' : 'text-subtle')}>
          {recordCount > 0 ? recordCount.toLocaleString() : '—'}
        </span>
      </TableCell>

      <TableCell className="text-right">
        <span className="text-muted tabular-nums">{formatDate(run.created_at)}</span>
      </TableCell>

      <TableCell className="text-right whitespace-nowrap">
        <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <Button variant="secondary" size="sm" asChild>
            <Link to={`/crawl?run_id=${run.id}`}>
              Open
              <ArrowRightCircle className="ml-1 size-3" />
            </Link>
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={onDelete}
            disabled={!canDelete || pendingDelete}
          >
            <Trash2 className="size-3" />
            {pendingDelete ? '...' : 'Delete'}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function formatRunType(value: string) {
  if (value === 'crawl') return 'Single';
  if (value === 'batch') return 'Batch';
  if (value === 'csv') return 'CSV';
  return value;
}
