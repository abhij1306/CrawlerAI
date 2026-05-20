'use client';

import type { ReactNode, Ref, UIEventHandler } from 'react';

import { cn } from '../../lib/utils';

export function Table({
  children,
  className,
  wrapperClassName,
  wrapperRef,
  onWrapperScroll,
}: Readonly<{
  children: ReactNode;
  className?: string;
  wrapperClassName?: string;
  wrapperRef?: Ref<HTMLDivElement>;
  onWrapperScroll?: UIEventHandler<HTMLDivElement>;
}>) {
  return (
    <div
      ref={wrapperRef}
      onScroll={onWrapperScroll}
      className={cn('relative w-full overflow-auto', wrapperClassName)}
    >
      <table className={cn('w-full caption-bottom', className)}>{children}</table>
    </div>
  );
}

export function TableHeader({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableSectionElement>
>) {
  return (
    <thead {...props} className={cn('[&_tr]:border-b', className)}>
      {children}
    </thead>
  );
}

export function TableBody({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableSectionElement>
>) {
  return (
    <tbody {...props} className={cn('[&_tr:last-child]:border-0', className)}>
      {children}
    </tbody>
  );
}

export function TableRow({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableRowElement>
>) {
  return (
    <tr
      {...props}
      className={cn(
        'border-border odd:bg-panel even:bg-background-alt hover:bg-accent-subtle h-[var(--table-row-height)] border-b transition-colors',
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TableHead({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.ThHTMLAttributes<HTMLTableCellElement>
>) {
  // Data-table headers use the shared CSV-style mono header treatment.
  return (
    <th
      {...props}
      className={cn(
        'text-muted bg-background-alt h-[var(--table-header-height)] px-4 text-left align-middle [font-family:var(--table-header-font-family)] text-[length:var(--table-header-font-size)] font-bold tracking-[var(--table-header-tracking)]',
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TableCell({
  children,
  className,
  colSpan,
  ...props
}: Readonly<
  {
    children?: ReactNode;
    className?: string;
    colSpan?: number;
  } & React.TdHTMLAttributes<HTMLTableCellElement>
>) {
  return (
    <td
      {...props}
      className={cn(
        'text-primary px-4 py-0 align-middle font-sans text-sm leading-normal font-normal',
        className,
      )}
      colSpan={colSpan}
    >
      {children}
    </td>
  );
}
