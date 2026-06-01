'use client';

import {
  ArrowLeft,
  MoreHorizontal,
  Pause,
  Play,
  RotateCw,
  Settings,
  Trash2,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useReducer, useRef } from 'react';

import type {
  MonitorJob,
  MonitorStatus,
  MonitorUpdatePayload,
  AlertCreatePayload,
  AlertUpdatePayload,
} from '../../lib/api/types';
import { trapFocus } from '../../lib/focus-trap';
import { formatNextRun, formatRelativeTime } from '../../lib/format/date';
import { formatSeconds } from '../../lib/format/time';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { ConfirmDialog } from '../ui/confirm-dialog';
import { KVTile } from '../ui/patterns';
import { MonitorForm } from './monitor-form';
import { MonitorPriorityBadge, MonitorStatusBadge } from './monitor-badges';
import { AlertForm } from './alert-form';

type MonitorHeaderProps = Readonly<{
  monitor: MonitorJob;
  runPending: boolean;
  runError: string;
  onRunNow: () => void;
  onUpdateStatus: (status: MonitorStatus) => Promise<void>;
  onDelete: () => Promise<void>;
  onSave: (
    payload: MonitorUpdatePayload | AlertCreatePayload | AlertUpdatePayload,
  ) => Promise<void>;
}>;

type MonitorHeaderState = {
  menuOpen: boolean;
  editOpen: boolean;
  deleteOpen: boolean;
  statusPending: boolean;
  deletePending: boolean;
};

type MonitorHeaderAction =
  | { type: 'menuToggled' }
  | { type: 'editOpened' }
  | { type: 'editClosed' }
  | { type: 'deleteOpened' }
  | { type: 'deleteClosed' }
  | { type: 'statusStarted' }
  | { type: 'statusSettled' }
  | { type: 'deleteStarted' }
  | { type: 'deleteSettled' };

const initialMonitorHeaderState: MonitorHeaderState = {
  menuOpen: false,
  editOpen: false,
  deleteOpen: false,
  statusPending: false,
  deletePending: false,
};

function monitorHeaderReducer(
  state: MonitorHeaderState,
  action: MonitorHeaderAction,
): MonitorHeaderState {
  switch (action.type) {
    case 'menuToggled':
      return { ...state, menuOpen: !state.menuOpen };
    case 'editOpened':
      return { ...state, menuOpen: false, deleteOpen: false, editOpen: true };
    case 'editClosed':
      return { ...state, editOpen: false };
    case 'deleteOpened':
      return { ...state, menuOpen: false, editOpen: false, deleteOpen: true };
    case 'deleteClosed':
      return { ...state, deleteOpen: false };
    case 'statusStarted':
      return { ...state, statusPending: true };
    case 'statusSettled':
      return { ...state, statusPending: false };
    case 'deleteStarted':
      return { ...state, deletePending: true };
    case 'deleteSettled':
      return { ...state, deletePending: false };
  }
}

export function MonitorHeader({
  monitor,
  runPending,
  runError,
  onRunNow,
  onUpdateStatus,
  onDelete,
  onSave,
}: MonitorHeaderProps) {
  const [state, dispatch] = useReducer(monitorHeaderReducer, initialMonitorHeaderState);
  const { menuOpen, editOpen, deleteOpen, statusPending, deletePending } = state;
  const menuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const deleteDialogRef = useRef<HTMLDialogElement | null>(null);
  const deleteConfirmRef = useRef<HTMLButtonElement | null>(null);
  const deletePreviousFocusRef = useRef<HTMLElement | null>(null);
  const deletePendingRef = useRef(deletePending);
  const active = monitor.status === 'active';
  const isAlert = Boolean(monitor.poll_interval_seconds);
  const parentHref = isAlert ? '/alerts' : '/monitors';
  const parentLabel = isAlert ? 'Product Alerts' : 'Monitors';
  const visibleDomains = monitor.domains.slice(0, 3).join(', ');
  const hiddenDomains = Math.max(0, monitor.domains.length - 3);

  useEffect(() => {
    deletePendingRef.current = deletePending;
  }, [deletePending]);

  useEffect(() => {
    if (!deleteOpen) {
      return;
    }
    const previousFocusRef = deletePreviousFocusRef;
    const menuTrigger = menuTriggerRef.current;
    const previousFocus = previousFocusRef.current;
    const frame = window.requestAnimationFrame(() => deleteConfirmRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (deletePendingRef.current) {
          return;
        }
        event.preventDefault();
        dispatch({ type: 'deleteClosed' });
        return;
      }
      trapFocus(event, deleteDialogRef.current);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      const restoreTarget = previousFocus?.isConnected ? previousFocus : menuTrigger;
      restoreTarget?.focus();
      previousFocusRef.current = null;
    };
  }, [deleteOpen]);

  async function updateStatus(status: MonitorStatus) {
    dispatch({ type: 'statusStarted' });
    try {
      await onUpdateStatus(status);
    } finally {
      dispatch({ type: 'statusSettled' });
    }
  }

  async function remove() {
    dispatch({ type: 'deleteStarted' });
    try {
      await onDelete();
      dispatch({ type: 'deleteClosed' });
    } finally {
      dispatch({ type: 'deleteSettled' });
    }
  }

  function openEditDialog() {
    dispatch({ type: 'editOpened' });
  }

  function openDeleteDialog() {
    deletePreviousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : menuTriggerRef.current;
    dispatch({ type: 'deleteOpened' });
  }

  return (
    <div className="border-border card-gradient rounded-lg border p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <Link
            href={parentHref}
            className="text-muted hover:text-foreground type-caption inline-flex items-center gap-1"
          >
            <ArrowLeft className="size-3.5" />
            {parentLabel}
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="type-heading-2 m-0 truncate">
              {isAlert ? monitor.urls[0] : monitor.name}
            </h2>
            <MonitorStatusBadge status={monitor.status} />
            <MonitorPriorityBadge priority={monitor.priority} />
          </div>
          <p className="text-secondary type-body-sm">
            every{' '}
            {isAlert
              ? formatSeconds(monitor.poll_interval_seconds ?? 0)
              : `${monitor.schedule_interval_hours}h`}{' '}
            · {monitor.urls.length} URL
            {monitor.urls.length === 1 ? '' : 's'} · {visibleDomains}
            {hiddenDomains ? ` +${hiddenDomains}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="neutral"
            disabled={statusPending}
            onClick={() => void updateStatus(active ? 'paused' : 'active')}
          >
            {active ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            {active ? 'Pause' : 'Resume'}
          </Button>
          <Button type="button" variant="neutral" onClick={openEditDialog}>
            <Settings className="size-3.5" />
            Edit
          </Button>
          <Button type="button" onClick={onRunNow} disabled={runPending}>
            <RotateCw className={cn('size-3.5', runPending && 'animate-spin')} />
            {runPending ? 'Running...' : 'Run Now'}
          </Button>
          <div className="relative">
            <Button
              ref={menuTriggerRef}
              type="button"
              variant="quiet"
              size="icon"
              aria-label="More actions"
              onClick={() => dispatch({ type: 'menuToggled' })}
            >
              <MoreHorizontal className="size-4" />
            </Button>
            {menuOpen ? (
              <div className="border-border bg-background-elevated shadow-card absolute right-0 z-20 mt-1 w-36 rounded-md border py-1">
                <button
                  type="button"
                  onClick={openDeleteDialog}
                  className="text-danger hover:bg-danger-bg flex w-full items-center gap-2 px-3 py-2 text-sm"
                >
                  <Trash2 className="size-3.5" />
                  Delete
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
      {runError ? <p className="text-danger type-caption mt-3">{runError}</p> : null}
      <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <KVTile
          label={isAlert ? 'Last Checked' : 'Last Run'}
          value={formatRelativeTime(isAlert ? monitor.last_checked_at : monitor.last_run_at)}
        />
        <KVTile label="Next Run" value={formatNextRun(monitor.next_run_at)} />
        <KVTile label="Tracked" value={monitor.tracked_fields.join(', ')} />
        <KVTile
          label={isAlert ? 'Condition' : 'Retention'}
          value={isAlert ? monitor.condition || 'Any delta' : `${monitor.retention_days} days`}
        />
      </div>
      {editOpen ? (
        <div className="fixed inset-0 z-[100] bg-[color-mix(in_srgb,var(--bg-base)_34%,black)]">
          <dialog
            open
            aria-labelledby="monitor-edit-title"
            className="border-border bg-background shadow-card fixed top-0 right-0 z-[101] h-dvh w-[min(560px,100vw)] overflow-y-auto border-l p-5"
          >
            <div className="mb-5 flex items-center justify-between gap-4">
              <h2 id="monitor-edit-title" className="type-heading-3">
                Edit {isAlert ? 'alert' : 'monitor'}
              </h2>
              <Button
                type="button"
                variant="quiet"
                size="icon"
                aria-label="Close"
                onClick={() => dispatch({ type: 'editClosed' })}
              >
                <X className="size-4" />
              </Button>
            </div>
            {isAlert ? (
              <AlertForm
                initial={monitor}
                submitLabel="Save Changes"
                onCancel={() => dispatch({ type: 'editClosed' })}
                onSubmit={async (payload) => {
                  await onSave(payload);
                  dispatch({ type: 'editClosed' });
                }}
              />
            ) : (
              <MonitorForm
                initial={monitor}
                submitLabel="Save Changes"
                onCancel={() => dispatch({ type: 'editClosed' })}
                onSubmit={async (payload) => {
                  await onSave(payload);
                  dispatch({ type: 'editClosed' });
                }}
              />
            )}
          </dialog>
        </div>
      ) : null}
      {deleteOpen ? (
        <ConfirmDialog
          dialogRef={deleteDialogRef}
          confirmRef={deleteConfirmRef}
          titleId="monitor-delete-title"
          descriptionId="monitor-delete-description"
          title={`Delete this ${isAlert ? 'alert' : 'monitor'}?`}
          description={
            <>
              This permanently deletes the {isAlert ? 'alert' : 'monitor'}, its snapshots, events,
              URL state, and notifications.
            </>
          }
          pending={deletePending}
          confirmLabel={`Delete ${isAlert ? 'Alert' : 'Monitor'}`}
          onCancel={() => dispatch({ type: 'deleteClosed' })}
          onConfirm={() => void remove()}
        />
      ) : null}
    </div>
  );
}
