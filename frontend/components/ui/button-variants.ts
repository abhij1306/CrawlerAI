import { cva } from 'class-variance-authority';

export const buttonVariants = cva(
  'ui-button focus-ring inline-flex h-[var(--button-height)] items-center justify-center gap-1.5 rounded-md border px-[var(--button-padding-x)] text-sm font-sans font-medium leading-none whitespace-nowrap no-underline transition-[background-color,color,border-color,box-shadow] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale',
  {
    variants: {
      variant: {
        action: 'button-action-surface',
        download: 'button-download-surface',
        destructive: 'button-destructive-surface',
        neutral: 'button-neutral-surface',
        quiet: 'button-quiet-surface',
        topbar: 'button-topbar-surface',
        underline: 'button-link-surface',
        primary: 'button-action-surface',
        accent: 'button-action-surface',
        secondary: 'button-neutral-surface',
        ghost: 'button-quiet-surface',
        danger: 'button-destructive-surface',
      },
      size: {
        sm: 'ui-button-sm',
        md: 'ui-button-md',
        lg: 'ui-button-lg',
        icon: 'w-[var(--button-height)] px-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);
