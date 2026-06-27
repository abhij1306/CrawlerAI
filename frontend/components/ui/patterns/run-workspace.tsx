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
  const verdictTone =
    normalizedVerdict === 'success'
      ? 'text-success'
      : normalizedVerdict === 'partial'
        ? 'text-warning'
        : 'text-danger';
  const qualityTone =
    normalizedQuality === 'high'
      ? 'text-success'
      : normalizedQuality === 'medium'
        ? 'text-warning'
        : normalizedQuality === 'low'
          ? 'text-danger'
          : 'text-muted';
  const chips = [
    { key: 'duration', value: duration, icon: Clock, tone: 'text-secondary' },
    { key: 'verdict', value: verdict, icon: CheckCircle2, tone: verdictTone },
    { key: 'quality', value: quality, icon: Award, tone: qualityTone },
  ];

  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <div
            key={chip.key}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background-alt px-2.5 py-1"
          >
            <Icon className={cn('size-3.5 shrink-0', chip.tone)} aria-hidden="true" />
            <span className={cn('type-body-sm tabular-nums', chip.tone)}>{chip.value}</span>
          </div>
        );
      })}
    </div>
  );
}
