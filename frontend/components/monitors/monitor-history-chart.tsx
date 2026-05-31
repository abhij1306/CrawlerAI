'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import dynamic from 'next/dynamic';

import { monitorsApi } from '../../lib/api';
import type { MonitorJob } from '../../lib/api/types';
import { formatJobsTimestamp } from '../../lib/format/date';
import { Button } from '../ui/primitives';
import { DataRegionError } from '../ui/patterns';
import { MonitorEmptyState } from './monitor-empty-state';

const MonitorHistoryLineChart = dynamic(() => import('./monitor-history-line-chart'), {
  ssr: false,
  loading: () => <div className="skeleton size-full rounded-lg" />,
});

export function MonitorHistoryChart({ monitor }: Readonly<{ monitor: MonitorJob }>) {
  const [expanded, setExpanded] = useState(false);
  const historyQuery = useQuery({
    queryKey: ['monitor-history', monitor.id],
    queryFn: () => monitorsApi.history(String(monitor.id), { page: 1 }),
  });
  const snapshotQuery = useQuery({
    queryKey: ['monitor-current-snapshot', monitor.id],
    queryFn: () => monitorsApi.currentSnapshot(String(monitor.id)),
  });

  const rows = useMemo(() => {
    const history = historyQuery.data?.items ?? [];
    return [...history].reverse().map((snapshot) => ({
      time: formatJobsTimestamp(snapshot.created_at),
      records: snapshot.record_count,
      changes: snapshot.change_count,
    }));
  }, [historyQuery.data?.items]);

  const currentRecords = snapshotQuery.data ?? [];
  const visibleRecords = expanded ? currentRecords : currentRecords.slice(0, 10);

  if (historyQuery.error || snapshotQuery.error) {
    const error = historyQuery.error ?? snapshotQuery.error;
    return <DataRegionError message={error instanceof Error ? error.message : 'History failed.'} />;
  }
  if (historyQuery.isPending || snapshotQuery.isPending) {
    return <div className="skeleton h-80 w-full rounded-lg" />;
  }
  if (!rows.length) {
    return <MonitorEmptyState kind="history" />;
  }

  return (
    <div className="space-y-4">
      <div className="h-72 w-full">
        <MonitorHistoryLineChart rows={rows} />
      </div>
      {currentRecords.length ? (
        <div className="space-y-2">
          <div className="field-label">Latest URLs</div>
          <div className="grid gap-2 md:grid-cols-2">
            {visibleRecords.map((record) => (
              <div key={record.id} className="text-secondary type-body-sm flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="border-accent bg-accent-subtle size-3 rounded-sm border"
                />
                <span className="truncate">{record.source_url}</span>
              </div>
            ))}
          </div>
          {currentRecords.length > 10 ? (
            <Button
              type="button"
              variant="neutral"
              size="sm"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? 'Show less' : 'Show more'}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
