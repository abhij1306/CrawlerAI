import { useEffect } from 'react';
import type { ReactNode, RefObject } from 'react';

import { Button } from './button';

type ConfirmDialogProps = Readonly<{
  dialogRef: RefObject<HTMLDialogElement | null>;
  confirmRef: RefObject<HTMLButtonElement | null>;
  titleId: string;
  descriptionId: string;
  title: ReactNode;
  description: ReactNode;
  pending: boolean;
  confirmLabel: ReactNode;
  pendingLabel?: ReactNode;
  error?: string;
  overlayClassName?: string;
  onCancel: () => void;
  onConfirm: () => void;
}>;

export function ConfirmDialog({
  dialogRef,
  confirmRef,
  titleId,
  descriptionId,
  title,
  description,
  pending,
  confirmLabel,
  pendingLabel = 'Working...',
  error,
  overlayClassName = 'fixed inset-0 z-[100] grid place-items-center bg-[color-mix(in_srgb,var(--bg-base)_34%,black)] p-4',
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !pending) {
        event.preventDefault();
        onCancel();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [dialogRef, onCancel, pending]);

  return (
    <div className={overlayClassName}>
      <dialog
        ref={dialogRef}
        open
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="card-gradient relative m-0 w-[min(420px,100%)] rounded-lg border border-border p-5"
      >
        <h2 id={titleId} className="m-0 text-base leading-snug font-semibold text-foreground">
          {title}
        </h2>
        <p id={descriptionId} className="mt-2 text-sm leading-relaxed text-secondary">
          {description}
        </p>
        {error ? (
          <div
            role="alert"
            className="mt-4 rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm leading-normal text-danger"
          >
            {error}
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="quiet" disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            ref={confirmRef}
            type="button"
            variant="destructive"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? pendingLabel : confirmLabel}
          </Button>
        </div>
      </dialog>
    </div>
  );
}
