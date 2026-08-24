import { cva } from 'class-variance-authority';

/**
 * Button CVA — token-driven surfaces. Variants map to semantic bridged
 * tokens only. Sizes use the control-height tokens via bridged
 * `h-*` utilities defined in globals.css.
 */
export const buttonVariants = cva(
  'focus-ring inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm border font-sans font-medium leading-none no-underline transition-[background-color,color,border-color,box-shadow] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'border-transparent bg-accent text-accent-fg hover:bg-accent-hover',
        secondary: 'border-border-strong bg-panel text-foreground hover:bg-background-alt',
        neutral: 'border-border bg-background-alt text-foreground hover:bg-panel-strong',
        ghost:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground',
        destructive: 'border-transparent bg-transparent text-danger-text hover:bg-danger-bg',
        topbar:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground',
        underline:
          'underline text-accent hover:text-accent-hover border-transparent bg-transparent',
        // Backwards compatibility aliases
        action: 'border-transparent bg-accent text-accent-fg hover:bg-accent-hover',
        accent: 'border-transparent bg-accent text-accent-fg hover:bg-accent-hover',
        quiet:
          'border-transparent bg-transparent text-secondary hover:bg-background-alt hover:text-foreground',
        download: 'border-border bg-background-alt text-foreground hover:bg-panel-strong',
        danger: 'border-transparent bg-transparent text-danger-text hover:bg-danger-bg',
      },
      size: {
        sm: 'h-[var(--control-height-sm)] px-2.5 text-sm',
        md: 'h-[var(--control-height)] px-3.5 text-sm',
        lg: 'h-[var(--control-height-lg)] px-4 text-base',
        icon: 'size-[var(--control-height)] px-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);
