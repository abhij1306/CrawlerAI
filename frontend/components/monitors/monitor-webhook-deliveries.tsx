'use client';

import { useQuery } from '@tanstack/react-query';

import { alertsApi } from '../../lib/api';
import { formatRelativeTime } from '../../lib/format/date';
import { Skeleton } from '../ui/primitives';
import { DataRegionError } from '../ui/patterns';
import { MonitorEmptyState } from './monitor-empty-state';

export function MonitorWebhookDeliveries({ monitorId }: Readonly<{ monitorId: number }>) {
  const query = useQuery({
    queryKey: ['alert-deliveries', monitorId],
    queryFn: () => alertsApi.deliveries(monitorId),
  });

  if (query.error) {
    return (
      <DataRegionError
        message={query.error instanceof Error ? query.error.message : 'Delivery log failed.'}
      />
    );
  }
  if (query.isPending) {
    return <Skeleton className="h-40 w-full rounded-lg" />;
  }
  if (!query.data?.length) {
    return <MonitorEmptyState kind="events" />;
  }
  return (
    <div className="divide-border border-border rounded-lg border">
      {query.data.map((delivery) => (
        <div key={delivery.id} className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="type-caption-mono text-accent">{delivery.status}</span>
            <span className="type-control">attempt {delivery.attempt}</span>
            {delivery.response_code ? (
              <span className="text-secondary type-caption">HTTP {delivery.response_code}</span>
            ) : null}
            <span className="type-caption">{formatRelativeTime(delivery.created_at)}</span>
          </div>
          {delivery.error_message ? (
            <p className="text-danger type-caption mt-1">{delivery.error_message}</p>
          ) : null}
          <p className="text-secondary type-caption mt-1 truncate">
            {JSON.stringify(delivery.payload_preview)}
          </p>
        </div>
      ))}
    </div>
  );
}
