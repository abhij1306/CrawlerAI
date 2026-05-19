'use client';

import { Skeleton } from '../ui/primitives';

export function MonitorListSkeleton() {
  return (
    <div className="divide-border divide-y">
      {Array.from({ length: 3 }, (_, index) => (
        <div key={index} className="space-y-3 px-4 py-4">
          <div className="flex items-center justify-between gap-4">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-7 w-28" />
          </div>
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}

export function MonitorDetailSkeleton() {
  return (
    <div className="page-stack">
      <div className="border-border card-gradient rounded-[var(--radius-lg)] border p-5">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="mt-3 h-3 w-96 max-w-full" />
        <div className="mt-4 grid gap-2 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      </div>
      <Skeleton className="h-80 w-full rounded-[var(--radius-lg)]" />
    </div>
  );
}
