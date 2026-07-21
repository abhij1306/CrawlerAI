import { Award, CheckCircle2, Clock } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils';

export function RunWorkspaceShell({
  header,
  actions,
  tabs,
  summary,
  content,
}: Readonly<{
  header: ReactNode;
  actions?: ReactNode;
  tabs: ReactNode;
  summary?: ReactNode;
  content: ReactNode;
}>) {
  return (
    <div className="page-stack">
      <div className="card-gradient flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-6 py-4">
        <div className="min-w-0 flex-1">{header}</div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      <div className="page-stack">
        <div className="flex flex-wrap items-stretch justify-between gap-3 border-b border-divider">
          <div className="flex items-end">{tabs}</div>
          {summary ? <div className="self-center py-2">{summary}</div> : null}
        </div>
        {content}
      </div>
    </div>
  );
}

// Refined-minimal run-workspace chips: 24px radius-999 pills; duration is a
// neutral panel chip, verdict/quality carry a semantic tint (mockup .chip-success).
const TINT_BOX = {
  success: 'border-success-border bg-success-bg text-success-text',
  warning: 'border-warning-border bg-warning-bg text-warning-text',
  danger: 'border-danger-border bg-danger-bg text-danger-text',
} as const;
const NEUTRAL_MUTED_BOX = 'border-border bg-panel text-muted';
const NEUTRAL_PANEL_BOX = 'border-border bg-panel text-secondary';

export function RunSummaryChips({
  duration,
  verdict,
  quality,
}: Readonly<{
  duration: string;
  verdict: string;
  quality: string;
}>) {
  const normalizedVerdict = verdict.toLowerCase();
  const normalizedQuality = quality.toLowerCase();
  const verdictBox =
    normalizedVerdict === 'success'
      ? TINT_BOX.success
      : normalizedVerdict === 'partial'
        ? TINT_BOX.warning
        : TINT_BOX.danger;
  const qualityBox =
    normalizedQuality === 'high'
      ? TINT_BOX.success
      : normalizedQuality === 'medium'
        ? TINT_BOX.warning
        : normalizedQuality === 'low'
          ? TINT_BOX.danger
          : NEUTRAL_MUTED_BOX;
  const chips = [
    { key: 'duration', value: duration, icon: Clock, box: NEUTRAL_PANEL_BOX },
    { key: 'verdict', value: verdict, icon: CheckCircle2, box: verdictBox },
    { key: 'quality', value: quality, icon: Award, box: qualityBox },
  ];

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <div
            key={chip.key}
            className={cn(
              'inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5',
              chip.box,
            )}
          >
            <Icon className="size-3 shrink-0" aria-hidden="true" />
            <span className="text-xs font-medium tabular-nums">{chip.value}</span>
          </div>
        );
      })}
    </div>
  );
}
