'use client';

import { Badge } from '../ui/primitives';
import type { MonitorPriority, MonitorStatus } from '../../lib/api/types';

const STATUS_TONE_MAP: Record<MonitorStatus, 'info' | 'warning' | 'danger' | 'accent' | 'neutral'> =
  {
    active: 'info',
    paused: 'warning',
    error: 'danger',
    triggered: 'accent',
    archived: 'neutral',
  };

export function MonitorStatusBadge({ status }: Readonly<{ status: MonitorStatus }>) {
  const tone = STATUS_TONE_MAP[status] ?? 'neutral';
  return <Badge tone={tone}>{status}</Badge>;
}

export function MonitorPriorityBadge({ priority }: Readonly<{ priority: MonitorPriority }>) {
  if (priority === 'background') {
    return <span className="rounded-sm px-1.5 py-0.5">background</span>;
  }
  return <Badge tone={priority === 'on_demand' ? 'accent' : 'info'}>{priority}</Badge>;
}
