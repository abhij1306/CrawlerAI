import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

export function Field({
  label,
  hint,
  children,
  className,
}: Readonly<{ label: string; hint?: string; children: ReactNode; className?: string }>) {
  return (
    <label className={cn('grid gap-1.5', className)}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}
