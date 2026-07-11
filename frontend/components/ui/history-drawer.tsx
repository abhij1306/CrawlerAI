import { Ban, History, Trash2 } from 'lucide-react';

import { AppDrawer } from './dialog';
import { Badge } from './primitives';
import { cn } from '../../lib/utils';

export type HistoryItem = {
  id: number;
  status: string;
  created_at: string;
  label?: string;
  meta?: string;
  deletable?: boolean;
  cancellable?: boolean;
};

const STATUS_TONE_MAP: Record<string, 'success' | 'danger' | 'neutral' | 'warning' | 'info'> = {
  complete: 'success',
  completed: 'success',
  success: 'success',
  failed: 'danger',
  error: 'danger',
  running: 'info',
  pending: 'neutral',
  cancelled: 'warning',
};

export function HistoryDrawer({
  open,
  onClose,
  items,
  activeId,
  onSelect,
  onDelete,
  onCancel,
  title = 'Run History',
}: Readonly<{
  open: boolean;
  onClose: () => void;
  items: HistoryItem[];
  activeId?: number | null;
  onSelect: (id: number) => void;
  onDelete?: (id: number) => void;
  onCancel?: (id: number) => void;
  title?: string;
}>) {
  return (
    <AppDrawer
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
      title={title}
      icon={<History className="size-4 shrink-0 text-muted" />}
    >
      <div className="flex-1 overflow-auto">
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted">
            <History className="mb-3 size-8 opacity-20" />
            <p className="text-xs">No history found.</p>
          </div>
        ) : (
          <div className="divide-y divide-divider">
            {items.map((item) => (
              <div
                key={item.id}
                className={cn(
                  'hover:bg-background-alt flex items-stretch transition-colors',
                  activeId === item.id && 'bg-background-alt',
                )}
              >
                <button
                  type="button"
                  className="flex min-w-0 flex-1 flex-col gap-1.5 p-3.5 text-left"
                  onClick={() => {
                    onSelect(item.id);
                    onClose();
                  }}
                >
                  <div className="type-caption flex w-full items-center justify-between">
                    <span
                      className={cn(
                        'text-accent type-label-mono font-medium',
                        activeId === item.id && 'font-bold',
                      )}
                    >
                      #{item.id}
                    </span>
                    <Badge
                      tone={STATUS_TONE_MAP[(item.status ?? '').toLowerCase()] ?? 'neutral'}
                      className="origin-right scale-90"
                    >
                      {item.status}
                    </Badge>
                  </div>
                  {item.label && (
                    <div className="type-body max-w-[260px] truncate font-semibold text-foreground">
                      {item.label}
                    </div>
                  )}
                  <div className="flex w-full items-center justify-between">
                    <span>{item.meta ?? 'No details'}</span>
                    <span className="type-caption-mono">{formatShortDate(item.created_at)}</span>
                  </div>
                </button>
                {onCancel && item.cancellable ? (
                  <button
                    type="button"
                    className="m-2 self-center rounded-md p-2 text-muted hover:bg-danger/10 hover:text-danger"
                    aria-label={`Kill run ${item.id}`}
                    title="Kill run"
                    onClick={() => onCancel(item.id)}
                  >
                    <Ban className="size-3.5" />
                  </button>
                ) : null}
                {onDelete && item.deletable !== false ? (
                  <button
                    type="button"
                    className="m-2 self-center rounded-md p-2 text-muted hover:bg-danger/10 hover:text-danger"
                    aria-label={`Delete history item ${item.id}`}
                    onClick={() => onDelete(item.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </AppDrawer>
  );
}

function formatShortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
