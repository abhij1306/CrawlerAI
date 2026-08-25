import * as React from 'react';
import { useId } from 'react';
import { createPortal } from 'react-dom';
import type { ReactElement, ReactNode } from 'react';
import { cn } from '../../lib/utils';

/**
 * Tooltip — Portal-based positioning to prevent clipping.
 * Styled with the floating background-elevated surface, text-base, and border-strong tokens.
 */
export function Tooltip({
  children,
  content,
  className,
  align = 'center',
}: Readonly<{
  children: ReactElement<React.HTMLAttributes<HTMLElement>>;
  content: string;
  className?: string;
  align?: 'center' | 'start';
}>) {
  const tooltipId = useId();
  const child = React.Children.only(children);
  const anchorRef = React.useRef<HTMLDivElement>(null);
  const tooltipRef = React.useRef<HTMLDivElement>(null);
  const [open, setOpen] = React.useState(false);
  const [position, setPosition] = React.useState<{ left: number; top: number }>({
    left: 0,
    top: 0,
  });
  const childProps = child.props;
  const enhancedChild = React.cloneElement(child, {
    'aria-describedby': [childProps['aria-describedby'], tooltipId].filter(Boolean).join(' '),
    onMouseEnter: (event: React.MouseEvent<HTMLElement>) => {
      childProps.onMouseEnter?.(event);
      setOpen(true);
    },
    onMouseLeave: (event: React.MouseEvent<HTMLElement>) => {
      childProps.onMouseLeave?.(event);
      setOpen(false);
    },
    onFocus: (event: React.FocusEvent<HTMLElement>) => {
      childProps.onFocus?.(event);
      setOpen(true);
    },
    onBlur: (event: React.FocusEvent<HTMLElement>) => {
      childProps.onBlur?.(event);
      setOpen(false);
    },
  });

  const updatePosition = React.useCallback(() => {
    if (!anchorRef.current || !tooltipRef.current) {
      return;
    }
    const anchorRect = anchorRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const margin = 12;
    const idealLeft =
      align === 'start'
        ? anchorRect.left
        : anchorRect.left + anchorRect.width / 2 - tooltipRect.width / 2;
    const maxLeft = window.innerWidth - tooltipRect.width - margin;
    const nextLeft = Math.min(Math.max(idealLeft, margin), Math.max(margin, maxLeft));
    const nextTop = Math.max(margin, anchorRect.top - tooltipRect.height - 8);
    setPosition({ left: nextLeft, top: nextTop });
  }, [align, setPosition]);
  const updatePositionEvent = React.useEffectEvent(updatePosition);

  React.useLayoutEffect(() => {
    if (!open) {
      return;
    }
    updatePosition();
  }, [open, content, updatePosition]);

  React.useEffect(() => {
    if (!open) {
      return;
    }
    const handleLayout = () => updatePositionEvent();
    window.addEventListener('resize', handleLayout);
    window.addEventListener('scroll', handleLayout, true);
    return () => {
      window.removeEventListener('resize', handleLayout);
      window.removeEventListener('scroll', handleLayout, true);
    };
  }, [open]);

  return (
    <div ref={anchorRef} className={cn('relative flex items-center', className)}>
      {enhancedChild}
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={tooltipRef}
              id={tooltipId}
              role="tooltip"
              className={cn(
                'pointer-events-none fixed w-max max-w-[min(320px,calc(100vw-24px))]',
                'bg-background-elevated border border-border-strong rounded-md px-2 py-1 shadow-elevated',
                'text-foreground z-[200] text-base leading-normal font-medium break-words',
              )}
              style={{ left: `${position.left}px`, top: `${position.top}px` }}
            >
              {content}
              <div
                className="absolute -bottom-[5px] size-2.5 border-r border-b border-border-strong bg-background-elevated"
                style={{
                  left: align === 'start' ? '12px' : '50%',
                  transform: align === 'start' ? 'rotate(45deg)' : 'translateX(-50%) rotate(45deg)',
                }}
              />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
export const TooltipProvider = ({ children }: { children: ReactNode }) => children;
