import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils';
import { InlineAlert } from '../alert';
import { Skeleton } from '../primitives';
import { EmptyPanel, SkeletonRows, SurfacePanel } from './sections';

export function TableSurface({
  children,
  className,
  contentClassName,
}: Readonly<{
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}>) {
  return (
    <SurfacePanel className={cn('overflow-visible', className)}>
      <div className={cn('min-h-0 w-full min-w-0', contentClassName)}>{children}</div>
    </SurfacePanel>
  );
}

export function DataRegionLoading({
  count = 6,
  className,
}: Readonly<{ count?: number; className?: string }>) {
  return (
    <div className={cn('p-5', className)}>
      <SkeletonRows count={count} />
    </div>
  );
}

export function DataRegionEmpty({
  title,
  description,
  className,
}: Readonly<{ title: string; description: string; className?: string }>) {
  return (
    <div className={cn('p-5', className)}>
      <EmptyPanel title={title} description={description} />
    </div>
  );
}

export function DataRegionError({
  message,
  className,
}: Readonly<{ message: string; className?: string }>) {
  return (
    <div className={cn('p-5', className)}>
      <InlineAlert message={message} />
    </div>
  );
}

export function NavList<T>({
  items,
  selectedKey,
  onSelect,
  getKey,
  getLabel,
  getMeta,
  getBadge,
  className,
}: Readonly<{
  items: ReadonlyArray<T>;
  selectedKey: string;
  onSelect: (key: string) => void;
  getKey: (item: T) => string;
  getLabel: (item: T) => ReactNode;
  getMeta?: (item: T) => ReactNode;
  getBadge?: (item: T) => ReactNode;
  className?: string;
}>) {
  return (
    <div className={cn('space-y-2', className)}>
      {items.map((item) => {
        const key = getKey(item);
        const isActive = key === selectedKey;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isActive}
            onClick={() => onSelect(key)}
            className={cn(
              'w-full rounded-lg border p-3 text-left transition-colors',
              isActive
                ? 'border-accent bg-accent-subtle'
                : 'border-border bg-background hover:bg-background-elevated',
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="type-control truncate text-foreground">{getLabel(item)}</div>
                {getMeta ? (
                  <div className="type-caption mt-2 flex flex-wrap gap-2">{getMeta(item)}</div>
                ) : null}
              </div>
              {getBadge ? getBadge(item) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function DetailRow({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className={cn('border-border bg-background rounded-lg border px-6 py-4', className)}>
      {children}
    </div>
  );
}

export function KVTile({
  label,
  value,
  mono = false,
  className,
}: Readonly<{ label: string; value: ReactNode; mono?: boolean; className?: string }>) {
  return (
    <div className={cn('bg-background-elevated rounded-md px-2.5 py-2', className)}>
      <div className="type-micro-label">{label}</div>
      <div
        className={cn(
          'text-foreground pt-1',
          mono ? 'type-caption-mono !text-foreground font-medium' : 'type-control',
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function MetricPulse({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="grid grid-cols-4 gap-3 max-sm:grid-cols-2">{children}</div>;
}

export function MetricPulseItem({
  label,
  value,
  icon: Icon,
  trend,
  pulse,
}: Readonly<{
  label: string;
  value: ReactNode;
  icon?: LucideIcon;
  trend?: ReactNode;
  pulse?: boolean;
}>) {
  return (
    <div className="relative flex flex-col gap-2 rounded-lg border border-border bg-panel px-4 py-3.5 shadow-card">
      <div className="flex items-center gap-2 text-xs font-medium tracking-[0.07em] text-muted uppercase">
        {Icon && <Icon className="size-3.5 text-subtle" />}
        {label}
        {pulse ? (
          <div
            className="ml-auto h-1.5 w-1.5 animate-pulse rounded-full bg-success"
            aria-hidden="true"
          />
        ) : null}
      </div>
      <div className="text-[27px] leading-none font-semibold tracking-[-0.03em] text-foreground tabular-nums">
        {value}
      </div>
      {trend ? <div className="mt-auto">{trend}</div> : null}
    </div>
  );
}

export function MetricPulseSkeleton() {
  return (
    <div className="relative flex flex-col gap-2 rounded-lg border border-border bg-panel px-4 py-3.5 shadow-card">
      <Skeleton className="h-3 w-16" />
      <Skeleton className="mt-2 h-8 w-24" />
    </div>
  );
}
