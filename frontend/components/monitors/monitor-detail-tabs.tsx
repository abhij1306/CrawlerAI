'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';

import type { MonitorJob } from '../../lib/api/types';
import { Skeleton } from '../ui/primitives';
import { SurfacePanel, TabBar } from '../ui/patterns';
import { MonitorEvents } from './monitor-events';
import { MonitorSnapshotTable } from './monitor-snapshot-table';
import { MonitorWebhookDeliveries } from './monitor-webhook-deliveries';

type MonitorDetailTab = 'events' | 'history' | 'snapshot' | 'deliveries';

const baseTabs: Array<{ value: MonitorDetailTab; label: string }> = [
  { value: 'events', label: 'Events' },
  { value: 'history', label: 'History' },
  { value: 'snapshot', label: 'Current Snapshot' },
];

function isMonitorDetailTab(value: unknown): value is MonitorDetailTab {
  return (
    value === 'events' || value === 'history' || value === 'snapshot' || value === 'deliveries'
  );
}

const MonitorHistoryChart = dynamic(
  () => import('./monitor-history-chart').then((module) => module.MonitorHistoryChart),
  {
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
    ssr: false,
  },
);

export function MonitorDetailTabs({
  monitor,
  monitorId,
  onRunNow,
  showDeliveries = false,
}: Readonly<{
  monitor: MonitorJob;
  monitorId: number;
  onRunNow: () => void;
  showDeliveries?: boolean;
}>) {
  const [tab, setTab] = useState<MonitorDetailTab>('events');
  const tabs = showDeliveries
    ? [...baseTabs, { value: 'deliveries' as const, label: 'Webhook Log' }]
    : baseTabs;

  return (
    <SurfacePanel>
      <div className="border-divider border-b px-4 pt-2">
        <TabBar
          value={tab}
          onChange={(value) => {
            if (isMonitorDetailTab(value)) setTab(value);
          }}
          options={tabs}
          variant="underline"
        />
      </div>
      <div className="p-4">
        {tab === 'events' ? <MonitorEvents monitorId={monitorId} onRunNow={onRunNow} /> : null}
        {tab === 'history' ? <MonitorHistoryChart monitor={monitor} /> : null}
        {tab === 'snapshot' ? <MonitorSnapshotTable monitor={monitor} onRunNow={onRunNow} /> : null}
        {tab === 'deliveries' && showDeliveries ? (
          <MonitorWebhookDeliveries monitorId={monitorId} />
        ) : null}
      </div>
    </SurfacePanel>
  );
}
