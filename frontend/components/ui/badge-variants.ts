/**
 * Badge token maps. Each family maps a value → bridged semantic token
 * classes. No raw hex; all classes resolve to the `@theme inline` bridge
 * in globals.css.
 *
 * Refined-minimal: statuses are a 6px dot + colored text — no tint pill,
 * no pill border (approved sample: refined-minimal-dashboard/runs-history).
 * All maps therefore render on a transparent box; tone lives in the text
 * (and the `bg-current` dot) only.
 *
 * Families:
 *  - status:         success | warning | danger | info
 *  - sentiment:      positive | neutral | negative
 *  - classification: owned | competitor | third-party  (citation classification)
 *  - run-status:     draft | queued | running | analyzing | completed | partial | failed | cancelled
 *  - neutral:        the default grey chip
 */

export const statusBadge = {
  success: 'bg-transparent text-success-text border-transparent',
  warning: 'bg-transparent text-warning-text border-transparent',
  danger: 'bg-transparent text-danger-text border-transparent',
  info: 'bg-transparent text-info-text border-transparent',
} as const;

export const sentimentBadge = {
  positive: 'bg-transparent text-success-text border-transparent',
  neutral: 'bg-transparent text-secondary border-transparent',
  negative: 'bg-transparent text-danger-text border-transparent',
} as const;

export const classificationBadge = {
  owned: 'bg-transparent text-info-text border-transparent',
  competitor: 'bg-transparent text-warning-text border-transparent',
  'third-party': 'bg-transparent text-secondary border-transparent',
} as const;

export const runStatusBadge = {
  draft: 'bg-transparent text-muted border-transparent',
  queued: 'bg-transparent text-muted border-transparent',
  running: 'bg-transparent text-accent-text border-transparent',
  analyzing: 'bg-transparent text-accent-text border-transparent',
  completed: 'bg-transparent text-success-text border-transparent',
  partial: 'bg-transparent text-warning-text border-transparent',
  failed: 'bg-transparent text-danger-text border-transparent',
  cancelled: 'bg-transparent text-muted border-transparent',
} as const;

export const neutralBadge = 'bg-transparent text-secondary border-transparent';

export type StatusValue = keyof typeof statusBadge;
export type SentimentValue = keyof typeof sentimentBadge;
export type ClassificationValue = keyof typeof classificationBadge;
export type RunStatusValue = keyof typeof runStatusBadge;

/** Shared typography for every badge family (dot + text, no pill anatomy). */
export const badgeBase =
  'inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium capitalize';
