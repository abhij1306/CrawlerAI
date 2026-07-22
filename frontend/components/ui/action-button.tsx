import type { ComponentType } from 'react';

import { Button } from './button';

/**
 * Canonical small action button (audit 6.8): destructive variant when `danger`,
 * secondary otherwise, with an optional leading icon.
 */
export function ActionButton({
  icon: Icon,
  label,
  danger,
  disabled,
  onClick,
}: Readonly<{
  icon?: ComponentType<{ className?: string }>;
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}>) {
  return (
    <Button
      type="button"
      variant={danger ? 'destructive' : 'secondary'}
      size="sm"
      disabled={disabled}
      onClick={onClick}
      title={label}
      className="min-w-0"
    >
      {Icon ? <Icon className="size-3.5" /> : null}
      {label}
    </Button>
  );
}
