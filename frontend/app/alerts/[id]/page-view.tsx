'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { use, useMemo, useState } from 'react';

import { alertsApi } from '../../../lib/api';
import type { MonitorStatus, AlertUpdatePayload } from '../../../lib/api/types';
import { isThenable } from '../../../lib/params';
import { alertToMonitor } from '../alert-helpers';
import { MonitorDetailTabs } from '../../../components/monitors/monitor-detail-tabs';
import { MonitorHeader } from '../../../components/monitors/monitor-header';
import { MonitorDetailSkeleton } from '../../../components/monitors/monitor-skeleton';
import { InlineAlert, PageHeader } from '../../../components/ui/patterns';

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
      <MonitorDetailTabs
        monitor={monitor}
        monitorId={alertIdNumber}
        onRunNow={() => runMutation.mutate()}
        showDeliveries
      />
    </div>
  );
}
