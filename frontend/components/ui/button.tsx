'use client';

import type { ComponentPropsWithoutRef } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { Slot } from '@radix-ui/react-slot';
import { cn } from '../../lib/utils';

export const buttonVariants = cva(
  'focus-ring inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border text-[length:var(--text-sm)] font-semibold leading-none whitespace-nowrap no-underline transition-[background-color,color,border-color,transform] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale',
  {
    variants: {
      variant: {
        primary: 'button-primary-surface active:scale-[0.98]',
        secondary:
          'border-border bg-background-elevated text-foreground hover:border-border-strong hover:bg-background-alt',
        ghost:
          'border-transparent bg-transparent text-secondary hover:bg-accent-subtle hover:text-foreground',
        accent:
          'ui-on-accent-surface border-accent bg-accent hover:border-accent-hover hover:bg-accent-hover active:scale-[0.98]',
        danger:
          'border-transparent bg-danger-bg text-danger hover:border-danger/20 hover:bg-danger-bg',
      },
      size: {
        sm: 'h-7 px-2.5 text-[length:var(--text-xs)]',
        md: 'h-8 px-3',
        lg: 'h-9 px-4',
        icon: 'size-8 p-0',
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
