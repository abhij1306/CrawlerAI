import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';
import { Button } from './button';

type AppDialogProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}>;

export function AppDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: AppDialogProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay-scrim fixed inset-0 z-[100]" />
        <DialogPrimitive.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-[101] flex max-h-[85vh] w-[640px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-background-elevated shadow-elevated focus:outline-none',
            className,
          )}
        >
          <header className="flex items-start justify-between gap-4 border-b border-divider px-4 py-3">
            <div>
              <DialogPrimitive.Title className="type-subheading">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-1 text-sm text-muted">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="quiet" size="icon" aria-label="Close dialog">
                <X className="size-3.5" />
              </Button>
            </DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">{children}</div>
          {footer ? (
            <footer className="flex items-center justify-end gap-2 border-t border-divider px-4 py-3">
              {footer}
            </footer>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

type AppDrawerProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}>;

export function AppDrawer({
  open,
  onOpenChange,
  title,
  icon,
  children,
  className,
}: AppDrawerProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[100] bg-black/20" />
        <DialogPrimitive.Content
          className={cn(
            'animate-in slide-in-from-right-4 fixed top-0 right-0 z-[101] flex h-full w-[380px] max-w-full flex-col overflow-hidden border-l border-divider bg-background-elevated shadow-xl duration-200 focus:outline-none',
            className,
          )}
        >
          <header className="flex items-center justify-between border-b border-divider px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              {icon}
              <DialogPrimitive.Title className="type-subheading truncate">
                {title}
              </DialogPrimitive.Title>
            </div>
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="quiet" size="icon" aria-label="Close drawer">
                <X className="size-3.5" />
              </Button>
            </DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

type ConfirmDialogProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  pending?: boolean;
  danger?: boolean;
  error?: string;
  onConfirm: () => void;
}>;

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  pending = false,
  danger = false,
  error,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => !pending && onOpenChange(nextOpen)}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay-scrim fixed inset-0 z-[100]" />
        <DialogPrimitive.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-[101] w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2',
            'border-border card-gradient rounded-lg border p-5',
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="m-0 text-base leading-snug font-semibold text-foreground">
                {title}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="mt-2 text-sm leading-relaxed text-secondary">
                {description}
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close asChild>
              <Button
                type="button"
                variant="quiet"
                size="icon"
                aria-label="Close"
                disabled={pending}
              >
                <X className="size-4" />
              </Button>
            </DialogPrimitive.Close>
          </div>
          {error ? (
            <div
              role="alert"
              className="mt-4 rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm leading-normal text-danger"
            >
              {error}
            </div>
          ) : null}
          <div className="mt-5 flex justify-end gap-2">
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="quiet" disabled={pending}>
                {cancelLabel}
              </Button>
            </DialogPrimitive.Close>
            <Button
              type="button"
              variant={danger ? 'destructive' : 'action'}
              disabled={pending}
              onClick={onConfirm}
            >
              {pending ? 'Working...' : confirmLabel}
            </Button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
