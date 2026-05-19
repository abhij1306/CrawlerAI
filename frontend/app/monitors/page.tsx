'use client';

import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { monitorsApi } from '../../lib/api';
import type { MonitorPriority, MonitorStatus } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { Button, Dropdown } from '../../components/ui/primitives';
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

export default function MonitorsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<MonitorStatus | 'all'>('all');
  const [priorityFilter, setPriorityFilter] = useState<MonitorPriority | 'all'>('all');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [runningId, setRunningId] = useState<number | null>(null);

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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
    onError: (mutationError) =>
      setError(mutationError instanceof Error ? mutationError.message : 'Monitor update failed.'),
  });

  const archiveMutation = useMutation({
    mutationFn: monitorsApi.archive,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
    onError: (mutationError) =>
      setError(mutationError instanceof Error ? mutationError.message : 'Archive failed.'),
  });

  async function runNow(id: number) {
    setRunningId(id);
    setError('');
    setNotice('');
    try {
      const response = await monitorsApi.runNow(id);
      setNotice(`Run dispatched · run_id: ${response.run_id}`);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'Run dispatch failed.');
    } finally {
      setRunningId(null);
    }
  }

  const monitors = useMemo(() => monitorsQuery.data ?? [], [monitorsQuery.data]);

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
      {notice ? <div className="alert-surface alert-success px-3 py-2 text-sm">{notice}</div> : null}
      {error ? <InlineAlert message={error} /> : null}
      <SurfacePanel className="overflow-visible">
        <div className="border-divider flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <TabBar
            value={statusFilter}
            onChange={(value) => setStatusFilter(value as MonitorStatus | 'all')}
            options={statusOptions}
            compact
          />
          <div className="w-44">
            <Dropdown
              value={priorityFilter}
              onChange={(value) => setPriorityFilter(value)}
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
                onArchive={(id) => archiveMutation.mutate(id)}
              />
            ))}
          </div>
        ) : (
          <div className="p-4">
            <MonitorEmptyState kind="list" />
          </div>
        )}
      </SurfacePanel>
    </div>
  );
}
