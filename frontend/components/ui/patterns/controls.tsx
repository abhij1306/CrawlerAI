import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils';

type TabBarOption<T extends string> = { value: T; label: ReactNode; icon?: ReactNode };

export function TabBar<T extends string>({
  value,
  onChange,
  options,
  compact = false,
  className,
  variant = 'pill',
  size = 'md',
  fullWidth = false,
}: Readonly<{
  value: T;
  onChange: (value: T) => void;
  options: ReadonlyArray<TabBarOption<T>>;
  compact?: boolean;
  className?: string;
  variant?: 'pill' | 'underline';
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
}>) {
  const padX = compact
    ? size === 'sm'
      ? 'px-2'
      : 'px-2.5'
    : size === 'lg'
      ? 'px-4'
      : size === 'sm'
        ? 'px-2.5'
        : 'px-3';
  const heightClass =
    size === 'lg'
      ? 'h-[var(--control-height-lg)]'
      : size === 'sm'
        ? 'h-[var(--control-height-sm)]'
        : 'h-[var(--control-height)]';
  const gapClass = size === 'lg' ? 'gap-2' : 'gap-1.5';

  if (variant === 'underline') {
    return (
      <div
        className={cn(
          '-mb-px flex items-stretch bg-transparent p-0',
          heightClass,
          fullWidth && 'w-full',
          className,
        )}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn(
              'type-control relative -mb-px inline-flex shrink-0 items-center justify-center font-sans tracking-normal whitespace-nowrap transition-all',
              fullWidth && 'flex-1',
              padX,
              value === option.value
                ? 'border-accent text-accent border-b-2'
                : 'text-secondary hover:text-foreground hover:border-border border-b-2 border-transparent',
            )}
          >
            {tabBarOptionContent(option, gapClass)}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'border-border bg-background-alt inline-flex items-center gap-0.5 rounded-md border p-0.5 shadow-none transition-all',
        heightClass,
        fullWidth && 'flex w-full',
        className,
      )}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'type-control relative z-10 inline-flex h-full min-w-[72px] shrink-0 items-center justify-center rounded-sm font-sans text-sm tracking-normal whitespace-nowrap transition-[background-color,color,border-color,box-shadow] duration-150 ease-out select-none',
            fullWidth && 'flex-1',
            padX,
            value === option.value
              ? 'border-border bg-panel text-foreground border shadow-xs'
              : 'text-muted hover:text-foreground border border-transparent bg-transparent',
          )}
        >
          {tabBarOptionContent(option, gapClass)}
        </button>
      ))}
    </div>
  );
}

function tabBarOptionContent<T extends string>(option: TabBarOption<T>, gapClass: string) {
  if (!option.icon) return option.label;
  return (
    <span className={cn('inline-flex items-center', gapClass)}>
      <span className="shrink-0">{option.icon}</span>
      <span>{option.label}</span>
    </span>
  );
}

export function ProgressBar({ percent }: Readonly<{ percent: number }>) {
  return (
    <div className="space-y-1">
      <div className="bg-border h-1 overflow-hidden rounded-full">
        <div
          className={cn(
            'bg-accent h-full rounded-full transition-[width] duration-500',
            percent >= 100 && 'bg-success',
          )}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <div className="type-caption-mono">{percent}%</div>
    </div>
  );
}
