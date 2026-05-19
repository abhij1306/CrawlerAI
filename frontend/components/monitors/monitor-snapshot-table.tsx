'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { monitorsApi } from '../../lib/api';
import type { MonitorJob, MonitorSnapshotRecord } from '../../lib/api/types';
import { formatRelativeTime } from '../../lib/format/date';
import { Input, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/primitives';
import { DataRegionError } from '../ui/patterns';
import { MonitorEmptyState } from './monitor-empty-state';

type SortKey = 'source_url' | 'created_at' | string;

export function MonitorSnapshotTable({
  monitor,
  onRunNow,
}: Readonly<{ monitor: MonitorJob; onRunNow: () => void }>) {
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('source_url');
  const [sortAsc, setSortAsc] = useState(true);
  const snapshotQuery = useQuery({
    queryKey: ['monitor-current-snapshot', monitor.id],
    queryFn: () => monitorsApi.currentSnapshot(String(monitor.id)),
  });

  const rows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const trackedFieldKeys = monitor.tracked_fields;
    const filtered = (snapshotQuery.data ?? []).filter((record) => {
      if (!normalizedQuery) return true;
      if (record.source_url.toLowerCase().includes(normalizedQuery)) return true;
      return trackedFieldKeys.some((key) =>
        String(cellValue(record, key)).toLowerCase().includes(normalizedQuery),
      );
    });
    return [...filtered].sort((left, right) => {
      const leftValue = cellValue(left, sortKey);
      const rightValue = cellValue(right, sortKey);
      const result = String(leftValue).localeCompare(String(rightValue), undefined, {
        numeric: true,
      });
      return sortAsc ? result : -result;
    });
  }, [monitor.tracked_fields, query, snapshotQuery.data, sortAsc, sortKey]);

  if (snapshotQuery.error) {
    return <DataRegionError message={snapshotQuery.error instanceof Error ? snapshotQuery.error.message : 'Snapshot failed.'} />;
  }
  if (snapshotQuery.isPending) {
    return <Skeleton className="h-72 w-full rounded-[var(--radius-lg)]" />;
  }
  if (!snapshotQuery.data?.length) {
    return <MonitorEmptyState kind="snapshot" onRunNow={onRunNow} />;
  }

  function setSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortAsc((value) => !value);
    } else {
      setSortKey(nextKey);
      setSortAsc(true);
    }
  }

  return (
    <div className="space-y-3">
      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search URL"
        className="max-w-sm"
      />
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <SortableHead label="URL" onClick={() => setSort('source_url')} />
              {monitor.tracked_fields.map((field) => (
                <SortableHead key={field} label={field} onClick={() => setSort(field)} />
              ))}
              <SortableHead label="last_changed" onClick={() => setSort('created_at')} />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((record) => (
              <TableRow key={record.id}>
                <TableCell className="max-w-[320px] truncate">
                  <a href={record.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                    {hostPath(record.source_url)}
                  </a>
                </TableCell>
                {monitor.tracked_fields.map((field) => (
                  <TableCell key={field}>{formatValue(record.field_values[field])}</TableCell>
                ))}
                <TableCell>{formatRelativeTime(record.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function SortableHead({ label, onClick }: Readonly<{ label: string; onClick: () => void }>) {
  return (
    <TableHead>
      <button type="button" onClick={onClick} className="type-caption text-muted hover:text-foreground">
        {label}
      </button>
    </TableHead>
  );
}

function cellValue(record: MonitorSnapshotRecord, sortKey: SortKey) {
  if (sortKey === 'source_url') return record.source_url;
  if (sortKey === 'created_at') return record.created_at;
  return record.field_values[sortKey] ?? '';
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === '') return 'empty';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function hostPath(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}
