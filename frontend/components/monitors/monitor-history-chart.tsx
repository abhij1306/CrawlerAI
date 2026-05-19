'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { monitorsApi } from '../../lib/api';
import type { MonitorJob } from '../../lib/api/types';
import { formatJobsTimestamp } from '../../lib/format/date';
import { Button } from '../ui/primitives';
import { DataRegionError } from '../ui/patterns';
import { MonitorEmptyState } from './monitor-empty-state';

export function MonitorHistoryChart({
  monitor,
}: Readonly<{ monitor: MonitorJob }>) {
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
    return [...history]
      .reverse()
      .map((snapshot) => ({
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
    return <div className="skeleton h-80 w-full rounded-[var(--radius-lg)]" />;
  }
  if (!rows.length) {
    return <MonitorEmptyState kind="history" />;
  }

  return (
    <div className="space-y-4">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 12, right: 20, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="time" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
            <YAxis tick={{ fill: 'var(--muted)', fontSize: 11 }} allowDecimals={false} />
            <Tooltip
              contentStyle={{
                background: 'var(--bg-panel)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
              }}
            />
            <Line type="monotone" dataKey="records" stroke="var(--accent)" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="changes" stroke="var(--warning)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
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
            <Button type="button" variant="secondary" size="sm" onClick={() => setExpanded((value) => !value)}>
              {expanded ? 'Show less' : 'Show more'}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
