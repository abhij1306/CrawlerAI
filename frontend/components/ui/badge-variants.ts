/**
 * Badge token maps. Each family maps a value → bridged semantic token
 * classes. No raw hex; all classes resolve to the `@theme inline` bridge
 * in globals.css.
 *
 * Refined-minimal: statuses are a 6px dot + colored text — no tint pill,
 * no pill border (approved sample: refined-minimal-dashboard/runs-history).
 * Maps therefore carry no box classes; tone lives in the text
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
  success: 'text-success-text',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
  info: 'text-info-text',
} as const;

export const sentimentBadge = {
  positive: 'text-success-text',
  neutral: 'text-secondary',
  negative: 'text-danger-text',
} as const;

export const classificationBadge = {
  owned: 'text-info-text',
  competitor: 'text-warning-text',
  'third-party': 'text-secondary',
} as const;

export const runStatusBadge = {
  draft: 'text-muted',
  queued: 'text-muted',
  running: 'text-accent-text',
  analyzing: 'text-accent-text',
  completed: 'text-success-text',
  partial: 'text-warning-text',
  failed: 'text-danger-text',
  cancelled: 'text-muted',
} as const;

export const neutralBadge = 'text-secondary';

export type StatusValue = keyof typeof statusBadge;
export type SentimentValue = keyof typeof sentimentBadge;
export type ClassificationValue = keyof typeof classificationBadge;
export type RunStatusValue = keyof typeof runStatusBadge;

/** Shared typography for every badge family (dot + text, no pill anatomy). */
export const badgeBase =
  'inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium capitalize';
