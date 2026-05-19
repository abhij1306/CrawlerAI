'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { use } from 'react';
import { useState } from 'react';

import { monitorsApi } from '../../../lib/api';
import type { MonitorStatus, MonitorUpdatePayload } from '../../../lib/api/types';
import { MonitorEvents } from '../../../components/monitors/monitor-events';
import { MonitorHeader } from '../../../components/monitors/monitor-header';
import { MonitorHistoryChart } from '../../../components/monitors/monitor-history-chart';
import { MonitorSnapshotTable } from '../../../components/monitors/monitor-snapshot-table';
import { MonitorDetailSkeleton } from '../../../components/monitors/monitor-skeleton';
import { InlineAlert, PageHeader, SurfacePanel, TabBar } from '../../../components/ui/patterns';

type TabValue = 'events' | 'history' | 'snapshot';

const tabs: Array<{ value: TabValue; label: string }> = [
  { value: 'events', label: 'Events' },
  { value: 'history', label: 'History' },
  { value: 'snapshot', label: 'Current Snapshot' },
];

export default function MonitorDetailPage({
  params,
}: Readonly<{
  params: Promise<{ id: string }> | { id: string };
}>) {
  const resolvedParams = isThenable(params) ? use(params) : params;
  const monitorId = resolvedParams.id;
  const monitorIdNumber = Number(monitorId);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabValue>('events');
  const [notice, setNotice] = useState('');
  const [runError, setRunError] = useState('');

  const monitorQuery = useQuery({
    queryKey: ['monitor', monitorId],
    queryFn: () => monitorsApi.get(monitorId),
  });

  const runMutation = useMutation({
    mutationFn: () => monitorsApi.runNow(monitorId),
    onSuccess: (response) => {
      setNotice(`Run dispatched · run_id: ${response.run_id}`);
      setRunError('');
      queryClient.invalidateQueries({ queryKey: ['monitor', monitorId] });
    },
    onError: (error) => {
      setRunError(error instanceof Error ? error.message : 'Run dispatch failed.');
    },
  });

  const statusMutation = useMutation({
    mutationFn: (status: MonitorStatus) => monitorsApi.update(monitorId, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor', monitorId] }),
  });

  const editMutation = useMutation({
    mutationFn: (payload: MonitorUpdatePayload) =>
      monitorsApi.update(monitorId, {
        name: payload.name,
        tracked_fields: payload.tracked_fields,
        schedule_interval_hours: payload.schedule_interval_hours,
        priority: payload.priority,
        retention_days: payload.retention_days,
        settings: payload.settings,
      }),
    onSuccess: () => {
      setNotice('Monitor saved.');
      queryClient.invalidateQueries({ queryKey: ['monitor', monitorId] });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () => monitorsApi.archive(monitorId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor', monitorId] }),
  });

  if (monitorQuery.isPending) {
    return <MonitorDetailSkeleton />;
  }

  if (monitorQuery.error || !monitorQuery.data) {
    return (
      <div className="page-stack">
        <PageHeader title="Monitor" />
        <InlineAlert
          message={monitorQuery.error instanceof Error ? monitorQuery.error.message : 'Monitor not found.'}
        />
      </div>
    );
  }

  const monitor = monitorQuery.data;

  return (
    <div className="page-stack">
      <PageHeader title={monitor.name} description="Monitor detail and change history." />
      {notice ? <div className="alert-surface alert-success px-3 py-2 text-sm">{notice}</div> : null}
      <MonitorHeader
        monitor={monitor}
        runPending={runMutation.isPending}
        runError={runError}
        onRunNow={() => runMutation.mutate()}
        onUpdateStatus={(status) => statusMutation.mutateAsync(status).then(() => undefined)}
        onArchive={() => archiveMutation.mutateAsync().then(() => undefined)}
        onSave={(payload) => editMutation.mutateAsync(payload).then(() => undefined)}
      />
      <SurfacePanel>
        <div className="border-divider border-b px-4 pt-2">
          <TabBar
            value={tab}
            onChange={(value) => setTab(value as TabValue)}
            options={tabs}
            variant="underline"
          />
        </div>
        <div className="p-4">
          {tab === 'events' ? (
            <MonitorEvents monitorId={monitorIdNumber} onRunNow={() => runMutation.mutate()} />
          ) : null}
          {tab === 'history' ? <MonitorHistoryChart monitor={monitor} /> : null}
          {tab === 'snapshot' ? (
            <MonitorSnapshotTable monitor={monitor} onRunNow={() => runMutation.mutate()} />
          ) : null}
        </div>
      </SurfacePanel>
    </div>
  );
}

function isThenable(value: unknown): value is Promise<{ id: string }> {
  return typeof value === 'object' && value !== null && 'then' in value;
}
