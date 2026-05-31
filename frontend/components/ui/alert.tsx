'use client';

import type { ReactNode } from 'react';
import type { VariantProps } from 'class-variance-authority';

import { cn } from '../../lib/utils';
import { alertVariants } from './alert-variants';

export type InlineAlertProps = {
  message: ReactNode;
  className?: string;
} & VariantProps<typeof alertVariants>;

export function InlineAlert({ message, tone, className }: Readonly<InlineAlertProps>) {
  if (!message) return null;
  return (
    <div role="alert" className={cn(alertVariants({ tone }), className)}>
      {message}
    </div>
  );
}
