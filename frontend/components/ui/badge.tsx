import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '../../lib/utils';

/** Shared typography for the badge (dot + text, no pill anatomy). */
const badgeBase =
  'inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium capitalize';

const toneText = {
  neutral: 'text-muted',
  success: 'text-success-text',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
  accent: 'text-accent-text',
  info: 'text-info-text',
} as const;

// Refined-minimal: semantic tones are dot + colored text (no tint pill).
// Only `neutral` keeps a subtle chip box for id/count chips.
const toneBox: Partial<Record<keyof typeof toneText, string>> = {
  neutral: 'rounded-full border border-border bg-panel px-2 py-0.5',
};

/**
 * Badge — semantic `tone` resolves to the correct bridged token classes;
 * `flat` drops the neutral chip box for subdued statuses.
 */
export type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: keyof typeof toneText;
  flat?: boolean;
} & Omit<HTMLAttributes<HTMLSpanElement>, 'children'>;

function badgeClasses(tone: keyof typeof toneText, flat: boolean): string {
  if (flat) {
    return toneText[tone];
  }

  return cn(toneText[tone], toneBox[tone]);
}

export function Badge(props: Readonly<BadgeProps>) {
  const { children, className, tone = 'neutral', flat = false, ...rest } = props;

  return (
    <span className={cn(badgeBase, badgeClasses(tone, flat), className)} {...rest}>
      <span
        className={cn('size-1.5 rounded-full bg-current', tone === 'accent' && 'animate-pulse')}
        aria-hidden
      />
      {children}
    </span>
  );
}
