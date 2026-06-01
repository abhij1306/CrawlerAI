'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { MoreHorizontal, Pause, Play, RotateCw, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Ref } from 'react';

import type { MonitorJob } from '../../lib/api/types';
import { formatNextRun, formatRelativeTime } from '../../lib/format/date';
import { formatSeconds } from '../../lib/format/time';
import { cn } from '../../lib/utils';
import { Button } from '../ui/primitives';
import { MonitorPriorityBadge, MonitorStatusBadge } from './monitor-badges';
import { formatMonitorValue, monitorHostPath } from './monitor-format';

interface MonitorListItemProps {
  monitor: MonitorJob;
  detailHref?: Route;
  onRunNow: (id: number) => void;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
  onDelete: (id: number) => void;
  running?: boolean;
}

export function MonitorListItem({
  monitor,
  detailHref,
  onRunNow,
  onPause,
  onResume,
  onDelete,
  running = false,
}: Readonly<MonitorListItemProps>) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const firstActionRef = useRef<HTMLButtonElement>(null);
  const id = monitor.id;
  const active = monitor.status === 'active';
  const isAlert = Boolean(monitor.poll_interval_seconds);
  const firstUrl = monitor.urls[0] ?? '';
  const currentValues = monitor.last_known_values ?? {};

  useEffect(() => {
    if (!open) return;
    firstActionRef.current?.focus();

    function closeMenu(restoreFocus: boolean) {
      setOpen(false);
      if (restoreFocus) buttonRef.current?.focus();
    }

    function onMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      closeMenu(false);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') closeMenu(true);
    }

    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);
  return (
    <div
      className={cn(
        'group hover:bg-background-alt grid gap-3 p-4 transition-colors md:grid-cols-[minmax(0,1fr)_auto]',
        open && 'relative z-10',
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className={cn(
              'size-2 rounded-full',
              active ? 'bg-info' : monitor.status === 'paused' ? 'bg-warning' : 'bg-muted',
            )}
            aria-hidden
          />
          <Link
            href={detailHref ?? (`/monitors/${id}` as Route)}
            className="type-subheading text-foreground truncate"
          >
            {isAlert ? monitorHostPath(firstUrl, 'Alert') : monitor.name}
          </Link>
          <MonitorStatusBadge status={monitor.status} />
          <MonitorPriorityBadge priority={monitor.priority} />
        </div>
        <div className="text-secondary type-body-sm mt-2 flex flex-wrap gap-x-3 gap-y-1">
          <span>{isAlert ? 'alert' : `${monitor.urls.length} URLs`}</span>
          <span>
            every{' '}
            {isAlert
              ? formatSeconds(monitor.poll_interval_seconds ?? 0)
              : `${monitor.schedule_interval_hours}h`}
          </span>
          <span>
            {monitor.last_checked_at
              ? `checked ${formatRelativeTime(monitor.last_checked_at)}`
              : formatNextRun(monitor.next_run_at)}
          </span>
          <span>{monitor.change_count ?? 0} changes</span>
          {monitor.last_run_at ? <span>last {formatRelativeTime(monitor.last_run_at)}</span> : null}
        </div>
        {isAlert ? (
          <div className="type-caption mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {monitor.tracked_fields.map((field) => (
              <span key={field}>
                {field}: {formatMonitorValue(currentValues[field])}
              </span>
            ))}
            {monitor.last_error ? <span className="text-danger">{monitor.last_error}</span> : null}
          </div>
        ) : null}
      </div>
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="neutral"
          size="sm"
          onClick={() => onRunNow(id)}
          disabled={running || monitor.status !== 'active'}
          title={monitor.status !== 'active' ? `Monitor is ${monitor.status}` : undefined}
          className="min-w-[92px]"
        >
          <RotateCw className={cn('size-3.5', running && 'animate-spin')} />
          {running ? 'Running...' : 'Run Now'}
        </Button>
        <div className="relative">
          <Button
            ref={buttonRef}
            type="button"
            variant="quiet"
            size="icon"
            aria-label="Monitor actions"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={`monitor-actions-${id}`}
            onClick={() => setOpen((value) => !value)}
          >
            <MoreHorizontal className="size-4" />
          </Button>
          {open ? (
            <div
              ref={menuRef}
              id={`monitor-actions-${id}`}
              role="menu"
              className="border-border bg-background-elevated shadow-card absolute right-0 z-20 mt-1 w-36 rounded-md border py-1"
            >
              <ActionButton
                ref={firstActionRef}
                icon={active ? Pause : Play}
                label={active ? 'Pause' : 'Resume'}
                onClick={() => {
                  setOpen(false);
                  active ? onPause(id) : onResume(id);
                }}
              />
              <ActionButton
                icon={Trash2}
                label="Delete"
                onClick={() => {
                  setOpen(false);
                  onDelete(id);
                }}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const ActionButton = function ActionButton({
  icon: Icon,
  label,
  onClick,
  ref,
}: {
  icon: typeof Pause;
  label: string;
  onClick: () => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      role="menuitem"
      onClick={onClick}
      className="text-secondary hover:bg-background-alt hover:text-foreground flex w-full items-center gap-2 px-3 py-2 text-left text-sm"
    >
      <Icon className="size-3.5" />
      {label}
    </button>
  );
};
