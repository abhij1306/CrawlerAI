'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { use } from 'react';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { monitorsApi } from '../../../lib/api';
import type { MonitorStatus, MonitorUpdatePayload } from '../../../lib/api/types';
import { isThenable } from '../../../lib/params';
import { MonitorDetailTabs } from '../../../components/monitors/monitor-detail-tabs';
import { MonitorHeader } from '../../../components/monitors/monitor-header';
import { MonitorDetailSkeleton } from '../../../components/monitors/monitor-skeleton';
import { InlineAlert, PageHeader } from '../../../components/ui/patterns';

export default function MonitorDetailPage({
  params,
}: Readonly<{
  params: Promise<{ id: string }> | { id: string };
}>) {
  const resolvedParams = isThenable(params) ? use(params) : params;
  const monitorId = resolvedParams.id;
  const monitorIdNumber = Number(monitorId);
  const router = useRouter();
  const queryClient = useQueryClient();
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
    mutationFn: (payload: MonitorUpdatePayload) => monitorsApi.update(monitorId, payload),
    onSuccess: () => {
      setNotice('Monitor saved.');
      queryClient.invalidateQueries({ queryKey: ['monitor', monitorId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => monitorsApi.remove(monitorId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['monitors'] });
      router.push('/monitors');
    },
  });

  if (monitorQuery.isPending) {
    return <MonitorDetailSkeleton />;
  }

  if (monitorQuery.error || !monitorQuery.data) {
    return (
      <div className="page-stack">
        <PageHeader title="Monitor" />
        <InlineAlert
          message={
            monitorQuery.error instanceof Error ? monitorQuery.error.message : 'Monitor not found.'
          }
        />
      </div>
    );
  }

  const monitor = monitorQuery.data;

  return (
    <div className="page-stack">
      <PageHeader title={monitor.name} description="Monitor detail and change history." />
      {notice ? (
        <div className="alert-surface alert-success px-3 py-2 text-sm">{notice}</div>
      ) : null}
      <MonitorHeader
        monitor={monitor}
        runPending={runMutation.isPending}
        runError={runError}
        onRunNow={() => runMutation.mutate()}
        onUpdateStatus={(status) => statusMutation.mutateAsync(status).then(() => undefined)}
        onDelete={() => deleteMutation.mutateAsync().then(() => undefined)}
        onSave={(payload) => editMutation.mutateAsync(payload).then(() => undefined)}
      />
      <MonitorDetailTabs
        monitor={monitor}
        monitorId={monitorIdNumber}
        onRunNow={() => runMutation.mutate()}
      />
    </div>
  );
}
