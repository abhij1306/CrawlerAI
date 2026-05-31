'use client';

import type { CSSProperties, ReactNode } from 'react';

function colorWithAlpha(color: string | undefined, alphaPercent: number) {
  const normalized = String(color ?? '').trim();
  if (!normalized) {
    return 'var(--accent-subtle)';
  }
  return `color-mix(in srgb, ${normalized} ${alphaPercent}%, transparent)`;
}

export function Metric({
  label,
  value,
  loading = false,
}: Readonly<{ label: string; value: ReactNode; loading?: boolean }>) {
  return (
    <div className="border-border card-gradient hover:border-border-strong relative space-y-2 overflow-hidden rounded-lg border px-5 py-4 transition-[border-color]">
      <p className="type-label">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div className="type-metric text-2xl">{value}</div>
      )}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon,
  iconColor,
  stripeColor,
  sub,
  loading = false,
}: Readonly<{
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  iconColor?: string;
  stripeColor?: string;
  sub?: ReactNode;
  loading?: boolean;
}>) {
  return (
    <div className="border-border card-gradient hover:border-border-strong relative overflow-hidden rounded-lg border px-5 py-4 transition-[border-color]">
      <div
        className="metric-stripe absolute inset-x-0 top-0 h-0.5"
        style={{ '--metric-stripe-color': stripeColor ?? 'var(--accent)' } as CSSProperties}
        aria-hidden
      />
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <p className="type-label">{label}</p>
        {icon ? (
          <div
            className="grid size-[22px] place-items-center rounded-sm"
            style={
              {
                '--metric-icon-bg': colorWithAlpha(stripeColor, 10),
                '--metric-icon-color': iconColor ?? stripeColor ?? 'var(--accent)',
              } as CSSProperties
            }
          >
            {icon}
          </div>
        ) : null}
      </div>
      {loading ? (
        <div className="skeleton mt-2.5 h-9 w-28" aria-hidden />
      ) : (
        <div className="type-metric mt-2 text-2xl">{value}</div>
      )}
      {sub && !loading ? (
        <div className="text-muted mt-1.5 text-sm leading-normal">{sub}</div>
      ) : null}
    </div>
  );
}
