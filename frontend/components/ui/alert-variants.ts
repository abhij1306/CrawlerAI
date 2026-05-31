import { cva } from 'class-variance-authority';

export const alertVariants = cva('alert-surface', {
  variants: {
    tone: {
      danger: 'alert-danger',
      warning: 'alert-warning',
      neutral: 'alert-neutral',
      success: 'alert-success',
    },
  },
  defaultVariants: {
    tone: 'danger',
  },
});
