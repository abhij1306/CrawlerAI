'use client';

import { Badge } from '../ui/primitives';
import type { MonitorPriority, MonitorStatus } from '../../lib/api/types';

export function MonitorStatusBadge({ status }: Readonly<{ status: MonitorStatus }>) {
  const tone = status === 'active' ? 'info' : status === 'paused' ? 'warning' : 'neutral';
  return <Badge tone={tone}>{status}</Badge>;
}

export function MonitorPriorityBadge({ priority }: Readonly<{ priority: MonitorPriority }>) {
  if (priority === 'background') {
    return (
      <span className="text-muted type-caption rounded-[var(--radius-sm)] px-1.5 py-0.5">
        background
      </span>
    );
  }
  return <Badge tone={priority === 'on_demand' ? 'accent' : 'info'}>{priority}</Badge>;
}
