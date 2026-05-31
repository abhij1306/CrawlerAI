'use client';

import type { ComponentPropsWithoutRef, Ref } from 'react';
import type { VariantProps } from 'class-variance-authority';

import { Slot } from '@radix-ui/react-slot';
import { cn } from '../../lib/utils';
import { buttonVariants } from './button-variants';

export interface ButtonProps
  extends ComponentPropsWithoutRef<'button'>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({ className, variant, size, asChild = false, ref, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button';
  return <Comp ref={ref} {...props} className={cn(buttonVariants({ variant, size }), className)} />;
}
