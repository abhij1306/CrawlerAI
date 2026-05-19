'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCheck, RotateCw } from 'lucide-react';
import { useState } from 'react';

import { api, monitorsApi } from '../../lib/api';
import type { MonitorEventType } from '../../lib/api/types';
import { formatRelativeTime } from '../../lib/format/date';
import { Button } from '../ui/primitives';
import { TabBar, DataRegionError } from '../ui/patterns';
import { MonitorEmptyState } from './monitor-empty-state';

const eventFilters: Array<{ value: MonitorEventType | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'field_changed', label: 'Field Changed' },
  { value: 'record_new', label: 'Record New' },
  { value: 'record_removed', label: 'Record Removed' },
];

export function MonitorEvents({
  monitorId,
  onRunNow,
}: Readonly<{ monitorId: number; onRunNow: () => void }>) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<MonitorEventType | 'all'>('all');
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ['monitor-events', monitorId, filter, page],
    queryFn: () =>
      monitorsApi.events(monitorId, {
        page,
        event_type: filter === 'all' ? undefined : filter,
      }),
  });
  const markReadMutation = useMutation({
    mutationFn: () => api.markMonitorNotificationsRead(monitorId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread'] });
    },
  });

  if (query.error) {
    return <DataRegionError message={query.error instanceof Error ? query.error.message : 'Events failed.'} />;
  }

  const events = query.data?.items ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabBar
          value={filter}
          onChange={(value) => {
            setFilter(value as MonitorEventType | 'all');
            setPage(1);
          }}
          options={eventFilters}
          compact
        />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => markReadMutation.mutate()}
          disabled={markReadMutation.isPending}
        >
          <CheckCheck className="size-3.5" />
          Mark all read
        </Button>
      </div>
      {query.isPending ? (
        <div className="skeleton h-32 w-full rounded-[var(--radius-lg)]" />
      ) : events.length ? (
        <div className="divide-border rounded-[var(--radius-lg)] border border-border">
          {events.map((event) => (
            <div key={event.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="type-caption-mono text-accent">{event.event_type}</span>
                {event.field_name ? <span className="type-control">{event.field_name}</span> : null}
                <span className="text-muted type-caption truncate">{hostPath(event.source_url)}</span>
              </div>
              <p className="text-secondary type-body-sm mt-1">
                {event.event_type === 'field_changed'
                  ? `${formatValue(event.old_value)} -> ${formatValue(event.new_value)}`
                  : event.event_type === 'record_new'
                    ? 'New product detected'
                    : 'Product no longer found'}
              </p>
              <p className="text-muted type-caption mt-1">{formatRelativeTime(event.detected_at)}</p>
            </div>
          ))}
        </div>
      ) : (
        <MonitorEmptyState kind="events" onRunNow={onRunNow} />
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>
          Previous
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={() => setPage((value) => value + 1)} disabled={!query.data || page * query.data.page_size >= query.data.total}>
          Next
        </Button>
        {query.isFetching ? <RotateCw className="text-muted size-4 animate-spin self-center" /> : null}
      </div>
    </div>
  );
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
