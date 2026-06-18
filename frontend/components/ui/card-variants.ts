import { cva } from 'class-variance-authority';

export const cardVariants = cva(
  'relative overflow-hidden rounded-xl border border-border card-gradient p-[var(--card-padding,var(--space-5))] transition-[border-color,box-shadow] hover:border-border-strong',
  {
    variants: {
      animate: {
        true: 'animate-fade-in',
        false: '',
      },
    },
    defaultVariants: {
      animate: false,
    },
  },
);
