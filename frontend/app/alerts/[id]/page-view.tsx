'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
import { use, useMemo, useState } from 'react';

import { alertsApi } from '../../../lib/api';
import type { MonitorStatus, AlertUpdatePayload } from '../../../lib/api/types';
import { isThenable } from '../../../lib/params';
import { alertToMonitor } from '../alert-helpers';
import { MonitorEvents } from '../../../components/monitors/monitor-events';
import { MonitorHeader } from '../../../components/monitors/monitor-header';
import { MonitorSnapshotTable } from '../../../components/monitors/monitor-snapshot-table';
import { MonitorDetailSkeleton } from '../../../components/monitors/monitor-skeleton';
import { Skeleton } from '../../../components/ui/primitives';
import { MonitorWebhookDeliveries } from '../../../components/monitors/monitor-webhook-deliveries';
import { InlineAlert, PageHeader, SurfacePanel, TabBar } from '../../../components/ui/patterns';

type TabValue = 'events' | 'history' | 'snapshot' | 'deliveries';

const tabs: Array<{ value: TabValue; label: string }> = [
  { value: 'events', label: 'Events' },
  { value: 'history', label: 'History' },
  { value: 'snapshot', label: 'Current Snapshot' },
  { value: 'deliveries', label: 'Webhook Log' },
];

const MonitorHistoryChart = dynamic(
  () =>
    import('../../../components/monitors/monitor-history-chart').then(
      (module) => module.MonitorHistoryChart,
    ),
  {
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
    ssr: false,
  },
);

export default function AlertDetailPage({
  params,
}: Readonly<{
  params: Promise<{ id: string }> | { id: string };
}>) {
  const resolvedParams = isThenable(params) ? use(params) : params;
  const alertId = resolvedParams.id;
  const parsedAlertId = Number.parseInt(alertId, 10);
  const alertIdNumber = Number.isInteger(parsedAlertId) && parsedAlertId > 0 ? parsedAlertId : null;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabValue>('events');
  const [notice, setNotice] = useState('');
  const [runError, setRunError] = useState('');

  const alertQuery = useQuery({
    queryKey: ['alert', alertId],
    queryFn: () => alertsApi.get(alertId),
  });

  const monitor = useMemo(
    () => (alertQuery.data ? alertToMonitor(alertQuery.data) : null),
    [alertQuery.data],
  );

  const runMutation = useMutation({
    mutationFn: () => alertsApi.test(alertId),
    onSuccess: (response) => {
      setNotice(`Poll completed · run_id: ${response.run_id}`);
      setRunError('');
      queryClient.invalidateQueries({ queryKey: ['alert', alertId] });
    },
    onError: (error) => {
      setRunError(error instanceof Error ? error.message : 'Alert poll failed.');
    },
  });

  const statusMutation = useMutation({
    mutationFn: (status: MonitorStatus) => alertsApi.update(alertId, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert', alertId] }),
  });

  const editMutation = useMutation({
    mutationFn: (payload: AlertUpdatePayload) => alertsApi.update(alertId, payload),
    onSuccess: () => {
      setNotice('Alert saved.');
      queryClient.invalidateQueries({ queryKey: ['alert', alertId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => alertsApi.remove(alertId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['alerts'] });
      router.push('/alerts');
    },
  });

  if (alertQuery.isPending) {
    return <MonitorDetailSkeleton />;
  }

  if (alertQuery.error || !monitor || alertIdNumber === null) {
    return (
      <div className="page-stack">
        <PageHeader title="Product Alert" />
        <InlineAlert
          message={
            alertQuery.error instanceof Error ? alertQuery.error.message : 'Alert not found.'
          }
        />
      </div>
    );
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Product Alert"
        description="Alert configuration, deltas, and webhook delivery log."
      />
      {notice ? <InlineAlert tone="success" message={notice} /> : null}
      <MonitorHeader
        monitor={monitor}
        runPending={runMutation.isPending}
        runError={runError}
        onRunNow={() => runMutation.mutate()}
        onUpdateStatus={(status) => statusMutation.mutateAsync(status).then(() => undefined)}
        onDelete={() => deleteMutation.mutateAsync().then(() => undefined)}
        onSave={(payload) =>
          editMutation.mutateAsync(payload as AlertUpdatePayload).then(() => undefined)
        }
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
            <MonitorEvents monitorId={alertIdNumber} onRunNow={() => runMutation.mutate()} />
          ) : null}
          {tab === 'history' ? <MonitorHistoryChart monitor={monitor} /> : null}
          {tab === 'snapshot' ? (
            <MonitorSnapshotTable monitor={monitor} onRunNow={() => runMutation.mutate()} />
          ) : null}
          {tab === 'deliveries' ? <MonitorWebhookDeliveries monitorId={alertIdNumber} /> : null}
        </div>
      </SurfacePanel>
    </div>
  );
}
