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
    <div className="border-border card-gradient hover:border-border-strong relative space-y-2 overflow-hidden rounded-[var(--radius-lg)] border px-5 py-4 transition-[border-color]">
      <p className="type-label">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div
          className="mono-body text-foreground leading-none font-bold tabular-nums"
          style={{ fontSize: 'var(--text-2xl)' }}
        >
          {value}
        </div>
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
    <div className="border-border card-gradient hover:border-border-strong relative overflow-hidden rounded-[var(--radius-lg)] border px-5 py-4 transition-[border-color]">
      <div
        className="absolute inset-x-0 top-0 h-0.5"
        style={{ background: stripeColor ?? 'var(--accent)' }}
        aria-hidden
      />
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <p className="type-label">{label}</p>
        {icon ? (
          <div
            className="grid size-[22px] place-items-center rounded-md"
            style={
              {
                background: colorWithAlpha(stripeColor, 10),
                color: iconColor ?? stripeColor ?? 'var(--accent)',
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
        <div
          className="mono-body text-foreground mt-2 leading-none font-bold tabular-nums"
          style={{ fontSize: 'var(--text-2xl)' }}
        >
          {value}
        </div>
      )}
      {sub && !loading ? (
        <div className="text-muted mt-1.5 text-sm leading-[var(--leading-normal)]">{sub}</div>
      ) : null}
    </div>
  );
}
