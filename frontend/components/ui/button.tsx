'use client';

import type { ComponentPropsWithoutRef } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { Slot } from '@radix-ui/react-slot';
import { cn } from '../../lib/utils';

export const buttonVariants = cva(
  'focus-ring inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border text-sm font-medium leading-none whitespace-nowrap no-underline transition-[background-color,color,border-color,box-shadow,opacity,transform] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale',
  {
    variants: {
      variant: {
        primary:
          'button-primary-surface shadow-xs hover:shadow-sm active:scale-[0.985] active:opacity-95',
        secondary:
          'border-border-strong bg-background-elevated text-foreground shadow-xs hover:bg-background-alt hover:border-accent',
        ghost:
          'border-transparent bg-transparent text-muted hover:bg-status-neutral-bg hover:text-foreground',
        accent:
          'ui-on-accent-surface border-accent bg-accent shadow-xs hover:border-accent-hover hover:bg-accent-hover active:opacity-90 active:scale-[0.98]',
        danger:
          'border-danger/30 bg-danger/10 text-danger hover:border-danger/45 hover:bg-danger/15',
      },
      size: {
        sm: 'min-h-[26px] px-[9px]',
        md: 'min-h-[var(--control-height)] px-3',
        lg: 'min-h-9 px-3.5',
        icon: 'size-[var(--control-height)] p-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);

export interface ButtonProps
  extends ComponentPropsWithoutRef<'button'>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: Readonly<ButtonProps>) {
  const Comp = asChild ? Slot : 'button';
  return <Comp {...props} className={cn(buttonVariants({ variant, size }), className)} />;
}
