import { useId } from 'react';
import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';

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
        <label htmlFor={id} className="text-xs font-medium text-secondary">
          {label}
          {required ? <span className="ml-0.5 text-danger">*</span> : null}
        </label>
        {children({
          id,
          'aria-invalid': error ? true : undefined,
          'aria-describedby': describedBy,
        })}
        {hint && !error ? (
          <span id={hintId} className="text-xs text-muted">
            {hint}
          </span>
        ) : null}
        {error ? (
          <span id={errorId} role="alert" className="text-xs text-danger">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  // Backwards compatibility fallback with native implicit labeling
  return (
    <label className={cn('grid gap-1.5 cursor-text', className)}>
      <span className="text-xs font-medium text-secondary">
        {label}
        {required ? <span className="ml-0.5 text-danger">*</span> : null}
      </span>
      {children}
      {hint && !error ? <span className="text-xs text-muted">{hint}</span> : null}
      {error ? (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      ) : null}
    </label>
  );
}
export type FieldProps = {
  label: string;
  hint?: string;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children:
    | ReactNode
    | ((props: { id: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }) => ReactNode);
};
