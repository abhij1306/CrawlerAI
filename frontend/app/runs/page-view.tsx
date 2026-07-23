import { Link } from 'react-router-dom';
import { useEffect } from 'react';

import { queryKeys } from '@/api/query-keys';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Search } from 'lucide-react';

import { Button, Card, Dropdown, Input } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/dialog';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  TableSurface,
} from '../../components/ui/patterns';
import { crawlsApi } from '../../lib/api/crawls';
import type { CrawlRun } from '../../lib/api/types';
import { Table, TableBody, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { RunRow } from './run-row';
import { useRunsPageState, type StatusFilter } from './use-runs-page-state';

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function RunsPage() {
  const queryClient = useQueryClient();
  const { state, dispatch } = useRunsPageState();
  const {
    domainFilter,
    statusFilter,
    appliedDomainFilter,
    appliedStatusFilter,
    pendingDeleteIds,
    actionError,
    deleteTarget,
  } = state;

  const {
    data: queryData,
    isLoading: isQueryLoading,
    isError: isQueryError,
  } = useQuery({
    queryKey: queryKeys.runs.list({
      url_search: appliedDomainFilter,
      status: appliedStatusFilter,
      limit: 50,
    }),
    queryFn: () =>
      crawlsApi.listCrawls({
        limit: 50,
        status: appliedStatusFilter || undefined,
        url_search: appliedDomainFilter || undefined,
      }),
  });

  useEffect(() => {
    const runs = queryData?.items ?? [];
    if (!runs.length) return;

    for (const run of runs) {
      queryClient.setQueryData<CrawlRun>(
        queryKeys.runs.detail(run.id),
        (current) => current ?? run,
      );
    }
  }, [queryClient, queryData?.items]);

  const deleteMutation = useMutation({
    mutationFn: (runId: number) => crawlsApi.deleteCrawl(runId),
    onMutate: (runId) => {
      dispatch({ type: 'deleteStarted', runId });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.runs.all });
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

  const visibleRuns = queryData?.items ?? [];

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
          <Link to="/crawl" className="no-underline">
            <Button variant="action" size="sm">
              <Plus className="size-3.5" />
              New Crawl
            </Button>
          </Link>
        }
      />

      {/* ── Filters ── */}
      <Card className="p-[10px_12px]">
        <div className="grid gap-4 md:grid-cols-[minmax(320px,1fr)_200px_auto_auto] md:items-center">
          <div className="relative min-w-0">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted" />
            <Input
              placeholder="Filter by domain or URL…"
              value={domainFilter}
              onChange={(e) => dispatch({ type: 'domainFilterChanged', value: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyFilters();
              }}
              className="mono-body pl-8"
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
      </Card>

      {actionError ? <InlineAlert message={actionError} /> : null}

      {/* ── Table ── */}
      <TableSurface>
        {(() => {
          if (isQueryError) {
            return <DataRegionError message="Unable to load run history." />;
          }
          if (isQueryLoading) {
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
          Showing {visibleRuns.length} of {queryData?.meta?.total ?? visibleRuns.length} runs
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
