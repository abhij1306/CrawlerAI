import { Children, isValidElement } from 'react';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { cn } from '../../lib/utils';

/**
 * Card — bg-panel, border, --radius-lg, --card-padding, shadow-card.
 * Composed from header / title / description / content / footer slots.
 * Supports legacy `animate` prop for backward compatibility in CrawlerAI.
 */
export function Card({
  children,
  className,
  animate,
  ...props
}: Readonly<ComponentPropsWithoutRef<'section'> & { animate?: boolean }>) {
  const hasCompound = Children.toArray(children).some(
    (child) =>
      isValidElement(child) &&
      (child.type === CardHeader || child.type === CardContent || child.type === CardFooter),
  );

  return (
    <section
      {...props}
      className={cn(
        'rounded-lg border border-border bg-panel shadow-card',
        hasCompound ? 'p-0' : 'p-[var(--card-padding)]',
        animate && 'animate-fade-in',
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'header'>>) {
  return (
    <header
      {...props}
      className={cn(
        'flex flex-col gap-1 border-b border-border-subtle p-[var(--card-padding)]',
        className,
      )}
    >
      {children}
    </header>
  );
}

export function CardTitle({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'h3'>>) {
  return (
    <h3 {...props} className={cn('text-lg font-semibold text-foreground', className)}>
      {children}
    </h3>
  );
}

export function CardDescription({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'p'>>) {
  return (
    <p {...props} className={cn('text-base text-secondary', className)}>
      {children}
    </p>
  );
}

export function CardContent({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'div'> & { children: ReactNode }>) {
  return (
    <div {...props} className={cn('p-[var(--card-padding)]', className)}>
      {children}
    </div>
  );
}

export function CardFooter({
  children,
  className,
  ...props
}: Readonly<ComponentPropsWithoutRef<'footer'>>) {
  return (
    <footer
      {...props}
      className={cn(
        'flex items-center gap-2 border-t border-border-subtle p-[var(--card-padding)]',
        className,
      )}
    >
      {children}
    </footer>
  );
}
