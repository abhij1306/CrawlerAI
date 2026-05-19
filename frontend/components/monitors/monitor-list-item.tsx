'use client';

import Link from 'next/link';
import { MoreHorizontal, Pause, Play, RotateCw, Trash2 } from 'lucide-react';
import { forwardRef, useEffect, useRef, useState } from 'react';

import type { MonitorJob } from '../../lib/api/types';
import { formatNextRun, formatRelativeTime } from '../../lib/format/date';
import { cn } from '../../lib/utils';
import { Button } from '../ui/primitives';
import { MonitorPriorityBadge, MonitorStatusBadge } from './monitor-badges';

interface MonitorListItemProps {
  monitor: MonitorJob;
  onRunNow: (id: number) => void;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
  onArchive: (id: number) => void;
  running?: boolean;
}

export function MonitorListItem({
  monitor,
  onRunNow,
  onPause,
  onResume,
  onArchive,
  running = false,
}: Readonly<MonitorListItemProps>) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const firstActionRef = useRef<HTMLButtonElement>(null);
  const id = monitor.id;
  const active = monitor.status === 'active';

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
        'group grid gap-3 px-4 py-4 transition-colors hover:bg-background-alt md:grid-cols-[minmax(0,1fr)_auto]',
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
          <Link href={`/monitors/${id}`} className="type-subheading text-foreground truncate">
            {monitor.name}
          </Link>
          <MonitorStatusBadge status={monitor.status} />
          <MonitorPriorityBadge priority={monitor.priority} />
        </div>
        <div className="text-secondary type-body-sm mt-2 flex flex-wrap gap-x-3 gap-y-1">
          <span>{monitor.urls.length} URLs</span>
          <span>every {monitor.schedule_interval_hours}h</span>
          <span>{formatNextRun(monitor.next_run_at)}</span>
          <span>{monitor.change_count ?? 0} changes</span>
          {monitor.last_run_at ? <span>last {formatRelativeTime(monitor.last_run_at)}</span> : null}
        </div>
      </div>
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
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
            variant="ghost"
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
              className="border-border bg-background-elevated absolute right-0 z-20 mt-1 w-36 rounded-[var(--radius-md)] border py-1 shadow-card"
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
                label="Archive"
                onClick={() => {
                  setOpen(false);
                  onArchive(id);
                }}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const ActionButton = forwardRef<HTMLButtonElement, {
  icon: typeof Pause;
  label: string;
  onClick: () => void;
}>(function ActionButton({
  icon: Icon,
  label,
  onClick,
}, ref) {
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
});
