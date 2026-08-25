import * as React from 'react';

import { cn } from '../../lib/utils';

function warnForMissingValue<T extends string>(value: T, options: Array<{ value: T }>) {
  if (
    import.meta.env.DEV &&
    options.length > 0 &&
    !options.some((option) => option.value === value)
  ) {
    console.warn(`Dropdown: value "${value}" not found in options`);
  }
}

export function Dropdown<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
  disabled = false,
  align = 'left',
  size = 'md',
}: Readonly<{
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: string }>;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
  align?: 'left' | 'center';
  size?: 'sm' | 'md';
}>) {
  warnForMissingValue(value, options);

  return (
    <div className={cn('relative', className)}>
      <select
        value={value}
        aria-label={ariaLabel}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value as T)}
        className={cn(
          'focus-ring border-border bg-panel-strong text-foreground hover:border-border-strong focus:border-accent w-full appearance-none rounded-sm border px-3 pr-9 text-base leading-snug font-normal transition-[background-color,border-color]',
          size === 'sm' ? 'h-8' : 'h-[var(--control-height)]',
          align === 'center' ? 'text-center' : 'text-left',
        )}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-3.5 -translate-y-1/2 text-muted"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4 6l4 4 4-4" />
      </svg>
    </div>
  );
}
