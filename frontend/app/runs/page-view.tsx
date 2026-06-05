'use client';

// Next.js App Router entrypoint for `/runs`; invoked by file-system routing.
import Link from 'next/link';
import type { Route } from 'next';
import { useReducer } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightCircle, Copy, ExternalLink, Plus, Trash2 } from 'lucide-react';

import { Badge, Button, Dropdown, Input, Tooltip } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/dialog';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  StatusDot,
  SurfacePanel,
  TableSurface,
} from '../../components/ui/patterns';
import { api } from '../../lib/api';
import type { CrawlRun, RunStatus } from '../../lib/api/types';
import { formatRunsDate as formatDate } from '../../lib/format/date';
import { getDomain } from '../../lib/format/domain';
import { isSubduedStatus, runExecutionLabel, runExecutionTone } from '../../lib/ui/status';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { cn } from '../../lib/utils';

type StatusFilter = '' | RunStatus;

type RunsPageState = {
  domainFilter: string;
  statusFilter: StatusFilter;
  appliedDomainFilter: string;
  appliedStatusFilter: StatusFilter;
  pendingDeleteIds: Set<number>;
  actionError: string;
  deleteTarget: CrawlRun | null;
};

type RunsPageAction =
  | { type: 'domainFilterChanged'; value: string }
  | { type: 'statusFilterChanged'; value: StatusFilter }
  | { type: 'filtersApplied' }
  | { type: 'filtersReset' }
  | { type: 'deleteStarted'; runId: number }
  | { type: 'deleteSucceeded' }
  | { type: 'deleteFailed'; message: string }
  | { type: 'deleteSettled'; runId: number }
  | { type: 'deleteRequested'; run: CrawlRun }
  | { type: 'deleteDialogClosed' };

const initialRunsPageState: RunsPageState = {
  domainFilter: '',
  statusFilter: '',
  appliedDomainFilter: '',
  appliedStatusFilter: '',
  pendingDeleteIds: new Set(),
  actionError: '',
  deleteTarget: null,
};

function runsPageReducer(state: RunsPageState, action: RunsPageAction): RunsPageState {
  switch (action.type) {
    case 'domainFilterChanged':
      return { ...state, domainFilter: action.value };
    case 'statusFilterChanged':
      return { ...state, statusFilter: action.value };
    case 'filtersApplied':
      return {
        ...state,
        appliedDomainFilter: state.domainFilter.trim(),
        appliedStatusFilter: state.statusFilter,
      };
    case 'filtersReset':
      return {
        ...state,
        domainFilter: '',
        statusFilter: '',
        appliedDomainFilter: '',
        appliedStatusFilter: '',
      };
    case 'deleteStarted': {
      const pendingDeleteIds = new Set(state.pendingDeleteIds);
      pendingDeleteIds.add(action.runId);
      return { ...state, pendingDeleteIds, actionError: '' };
    }
    case 'deleteSucceeded':
      return { ...state, actionError: '', deleteTarget: null };
    case 'deleteFailed':
      return { ...state, actionError: action.message };
    case 'deleteSettled': {
      const pendingDeleteIds = new Set(state.pendingDeleteIds);
      pendingDeleteIds.delete(action.runId);
      return { ...state, pendingDeleteIds };
    }
    case 'deleteRequested':
      return { ...state, deleteTarget: action.run };
    case 'deleteDialogClosed':
      return { ...state, deleteTarget: null };
  }
}

/* ─── Run row ────────────────────────────────────────────────────────────── */
function RunRow({
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
      {/* Domain + URL */}
      <TableCell className="overflow-visible">
        <div className="flex items-center gap-2.5">
          <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
          <div className="flex min-w-0 items-center gap-2">
            <Tooltip content={run.url} align="start">
              <Link
                href={`/crawl?run_id=${run.id}`}
                className="link-accent text-primary block max-w-[280px] truncate text-sm font-medium no-underline transition-colors"
              >
                {domain || `Run #${run.id}`}
              </Link>
            </Tooltip>

            <div className="flex items-center gap-1 opacity-10 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  void navigator.clipboard.writeText(run.url);
                }}
                className="text-muted hover:text-accent inline-flex min-h-6 min-w-6 items-center justify-center transition-colors"
                title="Copy URL"
                aria-label="Copy URL"
              >
                <Copy className="size-3" />
              </button>
              <a
                href={run.url}
                target="_blank"
                rel="noreferrer"
                className="text-muted hover:text-accent inline-flex min-h-6 min-w-6 items-center justify-center transition-colors"
                title="Open original URL"
                aria-label="Open original URL"
              >
                <ExternalLink className="size-3" />
              </a>
            </div>
          </div>
        </div>
      </TableCell>

      {/* Mode */}
      <TableCell>
        <span className="bg-background-elevated text-muted rounded-sm px-1.5 py-0.5 text-sm">
          {run.surface === 'design_system'
            ? `${formatRunType(run.run_type)} · Design System`
            : formatRunType(run.run_type)}
        </span>
      </TableCell>

      {/* Status */}
      <TableCell>
        <Badge
          tone={runExecutionTone(run.status, run.result_summary)}
          flat={isSubduedStatus(run.status)}
        >
          {runExecutionLabel(run.status, run.result_summary)}
        </Badge>
      </TableCell>

      {/* Records */}
      <TableCell className="text-right">
        <span
          className={cn('text-sm tabular-nums', recordCount > 0 ? 'text-primary' : 'text-muted')}
        >
          {recordCount > 0 ? recordCount.toLocaleString() : '—'}
        </span>
      </TableCell>

      {/* Date */}
      <TableCell className="text-right">
        <span className="text-muted text-sm tabular-nums">{formatDate(run.created_at)}</span>
      </TableCell>

      {/* Actions */}
      <TableCell className="text-right whitespace-nowrap">
        <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <Button variant="action" size="sm" asChild>
            <Link href={`/crawl?run_id=${run.id}` as Route}>
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
            {pendingDelete ? '…' : 'Delete'}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function RunsPage() {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(runsPageReducer, initialRunsPageState);
  const {
    domainFilter,
    statusFilter,
    appliedDomainFilter,
    appliedStatusFilter,
    pendingDeleteIds,
    actionError,
    deleteTarget,
  } = state;

  const query = useQuery({
    queryKey: ['runs', appliedDomainFilter, appliedStatusFilter],
    queryFn: () =>
      api.listCrawls({
        limit: 50,
        status: appliedStatusFilter || undefined,
        url_search: appliedDomainFilter || undefined,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: number) => api.deleteCrawl(runId),
    onMutate: (runId) => {
      dispatch({ type: 'deleteStarted', runId });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['runs'] });
      await queryClient.invalidateQueries({ queryKey: ['memory-runs'] });
      dispatch({ type: 'deleteSucceeded' });
    },
    onError: (error) => {
      dispatch({
        type: 'deleteFailed',
        message: error instanceof Error ? error.message : 'Unable to delete run.',
      });
    },
    onSettled: (_d, _e, runId) => {
      dispatch({ type: 'deleteSettled', runId });
    },
  });

  const visibleRuns = query.data?.items ?? [];

  function applyFilters() {
    dispatch({ type: 'filtersApplied' });
  }

  function resetFilters() {
    dispatch({ type: 'filtersReset' });
  }

  return (
    <div className="page-stack-lg h-full">
      <PageHeader
        title="Run History"
        actions={
          <Link href="/crawl" className="no-underline">
            <Button variant="action" size="sm">
              <Plus className="size-3.5" />
              New Crawl
            </Button>
          </Link>
        }
      />

      {/* ── Filters ── */}
      <SurfacePanel className="p-5">
        <div className="grid gap-4 md:grid-cols-[minmax(320px,1fr)_200px_auto_auto] md:items-center">
          <div className="min-w-0">
            <Input
              placeholder="Filter by domain or URL…"
              value={domainFilter}
              onChange={(e) => dispatch({ type: 'domainFilterChanged', value: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyFilters();
              }}
              className="text-mono-body"
            />
          </div>
          <Dropdown<StatusFilter>
            ariaLabel="Filter by status"
            value={statusFilter}
            onChange={(value) => dispatch({ type: 'statusFilterChanged', value })}
            options={[
              { value: '', label: 'All statuses' },
              { value: 'completed', label: 'Completed' },
              { value: 'running', label: 'Running' },
              { value: 'pending', label: 'Pending' },
              { value: 'paused', label: 'Paused' },
              { value: 'failed', label: 'Failed' },
              { value: 'killed', label: 'Killed' },
              { value: 'proxy_exhausted', label: 'Proxy Exhausted' },
            ]}
            className="w-full md:w-[200px]"
          />
          <Button onClick={applyFilters} size="sm">
            Filter
          </Button>
          <Button variant="quiet" onClick={resetFilters} size="sm">
            Reset
          </Button>
        </div>
      </SurfacePanel>

      {actionError ? <InlineAlert message={actionError} /> : null}

      {/* ── Table ── */}
      <TableSurface>
        {(() => {
          if (query.isError) {
            return <DataRegionError message="Unable to load run history." />;
          }
          if (query.isLoading) {
            return <DataRegionLoading count={8} />;
          }
          if (!visibleRuns.length) {
            return (
              <DataRegionEmpty
                title="No runs found"
                description="Submitted crawls will appear here."
              />
            );
          }
          return (
            <Table
              wrapperClassName="[--runs-table-offset:260px] max-h-[calc(100vh_-_var(--runs-table-offset))]"
              className="compact-data-table table-fixed"
            >
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[28%] whitespace-nowrap">Run</TableHead>
                  <TableHead className="w-[10%] whitespace-nowrap">Type</TableHead>
                  <TableHead className="w-[12%] whitespace-nowrap">Status</TableHead>
                  <TableHead className="w-[10%] text-right whitespace-nowrap">Records</TableHead>
                  <TableHead className="w-[15%] text-right whitespace-nowrap">Started</TableHead>
                  <TableHead className="w-[25%] text-right whitespace-nowrap">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRuns.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    pendingDelete={pendingDeleteIds.has(run.id)}
                    onDelete={() => dispatch({ type: 'deleteRequested', run })}
                  />
                ))}
              </TableBody>
            </Table>
          );
        })()}
      </TableSurface>

      {/* Total count */}
      {visibleRuns.length > 0 && (
        <p className="table-footer-rail rounded-md px-4 py-2">
          Showing {visibleRuns.length} of {query.data?.meta?.total ?? visibleRuns.length} runs
        </p>
      )}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) dispatch({ type: 'deleteDialogClosed' });
        }}
        title="Delete run"
        description={deleteTarget ? `Delete run ${deleteTarget.id}? This cannot be undone.` : ''}
        confirmLabel="Delete Run"
        pending={deleteTarget ? pendingDeleteIds.has(deleteTarget.id) : false}
        danger
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteMutation.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
}

function formatRunType(value: string) {
  if (value === 'crawl') return 'Single';
  if (value === 'batch') return 'Batch';
  if (value === 'csv') return 'CSV';
  return value;
}
