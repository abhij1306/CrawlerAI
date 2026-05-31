'use client';

import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useEffect, useMemo, useReducer } from 'react';

import { monitorsApi } from '../../lib/api';
import type { MonitorJob, MonitorPriority, MonitorStatus } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { Button, Dropdown } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/dialog';
import { InlineAlert, PageHeader, SurfacePanel, TabBar } from '../../components/ui/patterns';
import { MonitorEmptyState } from '../../components/monitors/monitor-empty-state';
import { MonitorListItem } from '../../components/monitors/monitor-list-item';
import { MonitorListSkeleton } from '../../components/monitors/monitor-skeleton';

const statusOptions: Array<{ value: MonitorStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
  { value: 'archived', label: 'Archived' },
];

const priorityOptions: Array<{ value: MonitorPriority | 'all'; label: string }> = [
  { value: 'all', label: 'All priorities' },
  { value: 'on_demand', label: 'On-Demand' },
  { value: 'priority', label: 'Priority' },
  { value: 'background', label: 'Background' },
];

type MonitorsPageState = {
  statusFilter: MonitorStatus | 'all';
  priorityFilter: MonitorPriority | 'all';
  notice: string;
  error: string;
  runningId: number | null;
  deleteTargetId: number | null;
};

type MonitorsPageAction =
  | { type: 'statusFilterChanged'; value: MonitorStatus | 'all' }
  | { type: 'priorityFilterChanged'; value: MonitorPriority | 'all' }
  | { type: 'runStarted'; id: number }
  | { type: 'runSucceeded'; runId: number }
  | { type: 'runFailed'; message: string }
  | { type: 'runSettled' }
  | { type: 'deleteRequested'; id: number }
  | { type: 'deleteDialogClosed' }
  | { type: 'deleteSucceeded' }
  | { type: 'mutationSucceeded' }
  | { type: 'mutationFailed'; message: string };

const initialMonitorsPageState: MonitorsPageState = {
  statusFilter: 'all',
  priorityFilter: 'all',
  notice: '',
  error: '',
  runningId: null,
  deleteTargetId: null,
};

function monitorsPageReducer(
  state: MonitorsPageState,
  action: MonitorsPageAction,
): MonitorsPageState {
  switch (action.type) {
    case 'statusFilterChanged':
      return { ...state, statusFilter: action.value };
    case 'priorityFilterChanged':
      return { ...state, priorityFilter: action.value };
    case 'runStarted':
      return { ...state, runningId: action.id, error: '', notice: '' };
    case 'runSucceeded':
      return { ...state, notice: `Run dispatched · run_id: ${action.runId}`, error: '' };
    case 'runFailed':
    case 'mutationFailed':
      return { ...state, error: action.message };
    case 'runSettled':
      return { ...state, runningId: null };
    case 'deleteRequested':
      return { ...state, deleteTargetId: action.id };
    case 'deleteDialogClosed':
      return { ...state, deleteTargetId: null };
    case 'deleteSucceeded':
      return { ...state, notice: 'Monitor deleted.', error: '', deleteTargetId: null };
    case 'mutationSucceeded':
      return { ...state, error: '' };
  }
}

export default function MonitorsPage() {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(monitorsPageReducer, initialMonitorsPageState);
  const { statusFilter, priorityFilter, notice, error, runningId, deleteTargetId } = state;

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.MONITORS_LAST_VISIT, new Date().toISOString());
  }, []);

  const monitorsQuery = useQuery({
    queryKey: ['monitors', statusFilter, priorityFilter],
    queryFn: () =>
      monitorsApi.list({
        status: statusFilter === 'all' ? undefined : statusFilter,
        priority: priorityFilter === 'all' ? undefined : priorityFilter,
      }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: MonitorStatus }) =>
      monitorsApi.update(id, { status }),
    onSuccess: () => {
      dispatch({ type: 'mutationSucceeded' });
      return queryClient.invalidateQueries({ queryKey: ['monitors'] });
    },
    onError: (mutationError) =>
      dispatch({
        type: 'mutationFailed',
        message: mutationError instanceof Error ? mutationError.message : 'Monitor update failed.',
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: monitorsApi.remove,
    onSuccess: async (_data, deletedId) => {
      dispatch({ type: 'deleteSucceeded' });
      queryClient.setQueriesData<MonitorJob[]>({ queryKey: ['monitors'] }, (cached) =>
        cached?.filter((monitor) => monitor.id !== deletedId),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['monitors'] }),
        queryClient.invalidateQueries({ queryKey: ['sidebar-monitors'] }),
      ]);
    },
    onError: (mutationError) =>
      dispatch({
        type: 'mutationFailed',
        message: mutationError instanceof Error ? mutationError.message : 'Delete failed.',
      }),
  });

  const monitors = useMemo(() => monitorsQuery.data ?? [], [monitorsQuery.data]);

  async function runNow(id: number) {
    dispatch({ type: 'runStarted', id });
    try {
      const response = await monitorsApi.runNow(id);
      dispatch({ type: 'runSucceeded', runId: response.run_id });
    } catch (runError) {
      dispatch({
        type: 'runFailed',
        message: runError instanceof Error ? runError.message : 'Run dispatch failed.',
      });
    } finally {
      dispatch({ type: 'runSettled' });
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Monitors"
        description="Recurring crawl runs with field-level change tracking."
        actions={
          <Button asChild size="sm">
            <Link href="/monitors/new">
              <Plus className="size-3.5" />
              New Monitor
            </Link>
          </Button>
        }
      />
      {notice ? (
        <div className="alert-surface alert-success px-3 py-2 text-sm">{notice}</div>
      ) : null}
      {error ? <InlineAlert message={error} /> : null}
      <SurfacePanel className="overflow-visible">
        <div className="border-divider flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <TabBar
            value={statusFilter}
            onChange={(value) =>
              dispatch({ type: 'statusFilterChanged', value: value as MonitorStatus | 'all' })
            }
            options={statusOptions}
            compact
          />
          <div className="w-44">
            <Dropdown
              value={priorityFilter}
              onChange={(value) => dispatch({ type: 'priorityFilterChanged', value })}
              options={priorityOptions}
              ariaLabel="Priority"
              size="sm"
            />
          </div>
        </div>
        {monitorsQuery.isPending ? (
          <MonitorListSkeleton />
        ) : monitors.length ? (
          <div className="divide-border divide-y">
            {monitors.map((monitor) => (
              <MonitorListItem
                key={monitor.id}
                monitor={monitor}
                running={runningId === monitor.id}
                onRunNow={(id) => void runNow(id)}
                onPause={(id) => updateMutation.mutate({ id, status: 'paused' })}
                onResume={(id) => updateMutation.mutate({ id, status: 'active' })}
                onDelete={(id) => dispatch({ type: 'deleteRequested', id })}
              />
            ))}
          </div>
        ) : (
          <div className="p-4">
            <MonitorEmptyState kind="list" />
          </div>
        )}
      </SurfacePanel>
      <ConfirmDialog
        open={deleteTargetId !== null}
        onOpenChange={(open) => {
          if (!open) dispatch({ type: 'deleteDialogClosed' });
        }}
        title="Delete this monitor?"
        description="This permanently deletes the monitor, its snapshots, events, URL state, and notifications."
        confirmLabel="Delete Monitor"
        pending={deleteMutation.isPending}
        danger
        error={error || undefined}
        onConfirm={() => {
          if (deleteTargetId !== null) {
            deleteMutation.mutate(deleteTargetId);
          }
        }}
      />
    </div>
  );
}
