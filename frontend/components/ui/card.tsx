'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import type { VariantProps } from 'class-variance-authority';

import { cn } from '../../lib/utils';
import { cardVariants } from './card-variants';

export type CardProps = ComponentPropsWithoutRef<'section'> &
  VariantProps<typeof cardVariants> & {
    children: ReactNode;
  };

export function Card({ children, className, animate, ...props }: Readonly<CardProps>) {
  return (
    <section {...props} className={cn(cardVariants({ animate }), className)}>
      {children}
    </section>
  );
}
