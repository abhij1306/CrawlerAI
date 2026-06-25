import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils';
import { Card } from '../card';
import { Skeleton } from '../primitives';

export function SectionHeader({
  title,
  description,
  icon: Icon,
  action,
}: Readonly<{
  title: string;
  description?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
}>) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="text-muted size-3.5 shrink-0" />}
          <h2 className="type-heading-3 m-0">{title}</h2>
        </div>
        {description ? <div className="type-body-sm">{description}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function EmptyPanel({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  return (
    <div className="border-border-strong bg-subtle-panel grid min-h-32 place-items-center rounded-lg border border-dashed px-6 py-8 text-center">
      <div className="space-y-1">
        <p className="type-subheading m-0">{title}</p>
        <p className="type-body m-0">{description}</p>
      </div>
    </div>
  );
}

export function SectionCard({
  title,
  description,
  action,
  children,
  className,
}: Readonly<{
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}>) {
  return (
    <Card className={cn('section-card', className)}>
      <SectionHeader title={title} description={description} action={action} />
      {children}
    </Card>
  );
}

export function SurfacePanel({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <Card className={cn('p-0', className)}>{children}</Card>;
}

export function SurfaceSection({
  title,
  description,
  icon: Icon,
  action,
  children,
  className,
  bodyClassName,
}: Readonly<{
  title: string;
  description?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}>) {
  return (
    <SurfacePanel className={className}>
      <div className="border-divider border-b px-5 py-4">
        <SectionHeader title={title} description={description} icon={Icon} action={action} />
      </div>
      <div className={cn('p-5', bodyClassName)}>{children}</div>
    </SurfacePanel>
  );
}

export function MutedPanelMessage({
  title,
  description,
  className,
}: Readonly<{
  title: string;
  description: string;
  className?: string;
}>) {
  return (
    <div className={cn('surface-muted rounded-lg border border-dashed px-5 py-6', className)}>
      <p className="type-subheading m-0">{title}</p>
      <p className="type-body m-0 mt-1.5">{description}</p>
    </div>
  );
}

export function SkeletonRows({
  count = 5,
  className,
}: Readonly<{ count?: number; className?: string }>) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: count }, (_, index) => (
        <Skeleton key={index} className="h-8 w-full" />
      ))}
    </div>
  );
}

export function StatusDot({
  tone = 'neutral',
  className,
}: Readonly<{
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info';
  className?: string;
}>) {
  const toneClass =
    tone === 'success'
      ? 'bg-success'
      : tone === 'warning'
        ? 'bg-warning'
        : tone === 'danger'
          ? 'bg-danger'
          : tone === 'accent'
            ? 'bg-accent'
            : tone === 'info'
              ? 'bg-info'
              : 'bg-muted';

  return (
    <span
      className={cn('inline-block size-1.5 shrink-0 rounded-full', toneClass, className)}
      aria-hidden="true"
    />
  );
}
