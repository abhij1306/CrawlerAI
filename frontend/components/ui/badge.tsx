'use client';

import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';
import { badgeVariants } from './badge-variants';

const toneText = {
  neutral: 'text-muted',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  accent: 'text-accent',
  info: 'text-info',
} as const;

const toneBox = {
  neutral: 'border-border bg-background-alt',
  success: 'border-success-border bg-success-bg',
  warning: 'border-warning-border bg-warning-bg',
  danger: 'border-danger-border bg-danger-bg',
  accent: 'border-accent-border bg-accent-soft',
  info: 'border-info-border bg-info-bg',
} as const;

export type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: keyof typeof toneText;
  flat?: boolean;
} & React.HTMLAttributes<HTMLSpanElement>;

export function Badge({
  children,
  tone = 'neutral',
  flat,
  className,
  ...props
}: Readonly<BadgeProps>) {
  return (
    <span
      {...props}
      className={cn(
        badgeVariants(),
        toneText[tone],
        !flat && 'rounded-sm border px-2 py-0.5',
        !flat && toneBox[tone],
        className,
      )}
    >
      <span
        className={cn('size-1 rounded-full bg-current', tone === 'accent' && 'animate-pulse')}
        aria-hidden
      />
      {children}
    </span>
  );
}
