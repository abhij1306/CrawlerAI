import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '../../lib/utils';
import {
  badgeBase,
  classificationBadge,
  neutralBadge,
  runStatusBadge,
  sentimentBadge,
  statusBadge,
  type ClassificationValue,
  type RunStatusValue,
  type SentimentValue,
  type StatusValue,
} from './badge-variants';

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

/**
 * Badge — discriminated on `variant` so each family only accepts its own
 * values, and each value resolves to the correct bridged token classes.
 * Supports legacy `tone` and `flat` props for CrawlerAI backward compatibility.
 */
export type BadgeProps = {
  children: ReactNode;
  className?: string;
} & (
  | { variant: 'status'; value: StatusValue; tone?: never; flat?: never }
  | { variant: 'sentiment'; value: SentimentValue; tone?: never; flat?: never }
  | { variant: 'classification'; value: ClassificationValue; tone?: never; flat?: never }
  | { variant: 'run-status'; value: RunStatusValue; tone?: never; flat?: never }
  | { variant?: 'neutral'; value?: undefined; tone?: keyof typeof toneText; flat?: boolean }
) &
  Omit<HTMLAttributes<HTMLSpanElement>, 'children'>;

function badgeClasses(props: BadgeProps): string {
  if (props.variant && props.variant !== 'neutral') {
    switch (props.variant) {
      case 'status':
        return statusBadge[props.value];
      case 'sentiment':
        return sentimentBadge[props.value];
      case 'classification':
        return classificationBadge[props.value];
      case 'run-status':
        return runStatusBadge[props.value];
      default:
        return neutralBadge;
    }
  }

  // Backward compatible tone mapping
  const tone = props.tone ?? 'neutral';
  const flat = props.flat ?? false;

  if (flat) {
    return cn('border-transparent bg-transparent', toneText[tone]);
  }

  return cn(toneText[tone], toneBox[tone]);
}

export function Badge(props: Readonly<BadgeProps>) {
  const {
    children,
    className,
    variant: _variant,
    value: _value,
    tone: _tone,
    flat: _flat,
    ...rest
  } = props;

  return (
    <span className={cn(badgeBase, badgeClasses(props), className)} {...rest}>
      <span
        className={cn('size-1 rounded-full bg-current', props.tone === 'accent' && 'animate-pulse')}
        aria-hidden
      />
      {children}
    </span>
  );
}
export type { StatusValue, SentimentValue, ClassificationValue, RunStatusValue };
export {
  statusBadge,
  sentimentBadge,
  classificationBadge,
  runStatusBadge,
  neutralBadge,
  badgeBase,
};
