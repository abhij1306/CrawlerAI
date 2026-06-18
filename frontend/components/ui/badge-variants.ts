import { cva } from 'class-variance-authority';

export const badgeVariants = cva(
  'inline-flex min-h-[20px] items-center gap-1.5 whitespace-nowrap text-2xs leading-[1.4] font-semibold tracking-wide capitalize',
);
