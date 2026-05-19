'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Plus, RotateCw } from 'lucide-react';

import { Button } from '../ui/primitives';
import { MutedPanelMessage } from '../ui/patterns';

type MonitorEmptyStateProps = Readonly<{
  kind: 'list' | 'events' | 'history' | 'snapshot';
  onRunNow?: () => void;
}>;

export function MonitorEmptyState({ kind, onRunNow }: MonitorEmptyStateProps) {
  const copy = emptyCopy[kind];
  return (
    <div className="space-y-3">
      <MutedPanelMessage title={copy.title} description={copy.description} />
      {kind === 'list' ? (
        <Button asChild size="sm">
          <Link href="/monitors/new">
            <Plus className="size-3.5" />
            New Monitor
          </Link>
        </Button>
      ) : copy.action && onRunNow ? (
        <Button type="button" size="sm" onClick={onRunNow}>
          <RotateCw className="size-3.5" />
          {copy.action}
        </Button>
      ) : null}
    </div>
  );
}

const emptyCopy: Record<
  MonitorEmptyStateProps['kind'],
  { title: string; description: string; action?: ReactNode }
> = {
  list: {
    title: 'No monitors yet',
    description: 'Create your first monitor to start tracking competitor prices.',
  },
  events: {
    title: 'No changes detected yet',
    description: 'Run Now to trigger an immediate check.',
    action: 'Run Now',
  },
  history: {
    title: 'History will appear after the first completed run',
    description: 'Snapshots are retained according to the monitor retention window.',
  },
  snapshot: {
    title: 'No snapshot yet',
    description: 'Run Now to capture the first data point.',
    action: 'Run Now',
  },
};
