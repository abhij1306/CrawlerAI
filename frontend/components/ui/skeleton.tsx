import { cn } from '../../lib/utils';

export function Skeleton({ className }: Readonly<{ className?: string }>) {
  return <div className={cn('skeleton', className)} aria-hidden="true" />;
}
