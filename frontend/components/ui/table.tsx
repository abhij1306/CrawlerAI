import type { HTMLAttributes, ReactNode, Ref, TdHTMLAttributes, ThHTMLAttributes } from 'react';

import { cn } from '../../lib/utils';

/**
 * Dense analytics table (refined-minimal):
 *  - sticky 30px header (--table-header-height), --text-sm uppercase, 0.07em tracking
 *  - 38px rows (--table-row-height), --text-base secondary-text cells
 *  - neutral row hover, tabular numerals for numeric columns (add `numeric`)
 * The wrapper is scroll-capable so the sticky header pins on vertical scroll.
 */
export function Table({
  children,
  className,
  wrapperClassName,
  wrapperRef,
}: Readonly<{
  children: ReactNode;
  className?: string;
  wrapperClassName?: string;
  wrapperRef?: Ref<HTMLDivElement>;
}>) {
  return (
    <div ref={wrapperRef} className={cn('relative w-full overflow-auto', wrapperClassName)}>
      <table
        className={cn('w-full border-collapse text-[length:var(--table-font-size)]', className)}
      >
        {children}
      </table>
    </div>
  );
}

export function TableHeader({
  children,
  className,
  ...props
}: Readonly<HTMLAttributes<HTMLTableSectionElement>>) {
  return (
    <thead {...props} className={cn(className)}>
      {children}
    </thead>
  );
}

export function TableBody({
  children,
  className,
  ...props
}: Readonly<HTMLAttributes<HTMLTableSectionElement>>) {
  return (
    <tbody {...props} className={cn(className)}>
      {children}
    </tbody>
  );
}

export function TableRow({
  children,
  className,
  ...props
}: Readonly<HTMLAttributes<HTMLTableRowElement>>) {
  return (
    <tr
      {...props}
      className={cn(
        'h-[var(--table-row-height)] border-b border-border-subtle bg-panel transition-colors hover:bg-background',
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
  numeric,
  ...props
}: Readonly<ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>) {
  return (
    <th
      {...props}
      className={cn(
        'sticky top-0 z-10 h-[var(--table-header-height)] border-b border-border bg-background px-3 align-middle text-[length:var(--table-header-font-size)] font-medium uppercase tracking-[0.07em] text-muted',
        numeric ? 'text-right tabular-nums' : 'text-left',
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
  numeric,
  ...props
}: Readonly<TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>) {
  return (
    <td
      {...props}
      className={cn(
        'px-3 py-0 align-middle text-secondary',
        numeric ? 'text-right tabular-nums' : 'text-left',
        className,
      )}
    >
      {children}
    </td>
  );
}
export type TableProps = {
  children: ReactNode;
  className?: string;
  wrapperClassName?: string;
  wrapperRef?: Ref<HTMLDivElement>;
};
