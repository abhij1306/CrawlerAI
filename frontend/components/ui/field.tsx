import { useId } from 'react';
import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';

function FieldLabel({ label, required }: Readonly<{ label: string; required?: boolean }>) {
  return (
    <>
      {label}
      {required ? <span className="ml-0.5 text-danger">*</span> : null}
    </>
  );
}

function FieldMessages({
  hint,
  error,
  hintId,
  errorId,
}: Readonly<{ hint?: string; error?: ReactNode; hintId?: string; errorId?: string }>) {
  if (error) {
    return (
      <span id={errorId} role="alert" className="text-base text-danger-text">
        {error}
      </span>
    );
  }
  return hint ? (
    <span id={hintId} className="text-base text-muted">
      {hint}
    </span>
  ) : null;
}

/**
 * Field — wraps a control with a label, optional hint, and an inline
 * error. Supports both standard nested child elements (for CrawlerAI backwards
 * compatibility) and the modern accessible render-prop pattern.
 */
export function Field({
  label,
  hint,
  error,
  required,
  className,
  children,
}: Readonly<{
  label: string;
  hint?: string;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children:
    | ReactNode
    | ((props: { id: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }) => ReactNode);
}>) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy =
    [error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(' ') || undefined;

  const isRenderProp = typeof children === 'function';

  if (isRenderProp) {
    return (
      <div className={cn('grid gap-1.5', className)}>
        <label htmlFor={id} className="text-base font-medium text-secondary">
          <FieldLabel label={label} required={required} />
        </label>
        {children({
          id,
          'aria-invalid': error ? true : undefined,
          'aria-describedby': describedBy,
        })}
        <FieldMessages hint={hint} error={error} hintId={hintId} errorId={errorId} />
      </div>
    );
  }

  // Backwards compatibility fallback with native implicit labeling
  return (
    <label className={cn('grid gap-1.5 cursor-text', className)}>
      <span className="text-base font-medium text-secondary">
        <FieldLabel label={label} required={required} />
      </span>
      {children}
      <FieldMessages hint={hint} error={error} />
    </label>
  );
}
