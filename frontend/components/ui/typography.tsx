import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

export function Title({
  children,
  kicker,
  className,
}: Readonly<{ children: ReactNode; kicker?: string; className?: string }>) {
  return (
    <div className={cn('space-y-1', className)}>
      {kicker ? <p className="type-kicker m-0 mb-1.5">{kicker}</p> : null}
      <h1 className="type-auth-title m-0">{children}</h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="mt-1.5 max-w-2xl text-base leading-relaxed text-muted">{children}</p>;
}
