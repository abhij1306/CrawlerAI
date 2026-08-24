import * as React from 'react';
import { useId } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

/**
 * Tooltip — Portal-based positioning to prevent clipping.
 * Styled with the dense panel-strong surface, text-base, and border-strong tokens.
 */
export function Tooltip({
  children,
  content,
  className,
  align = 'center',
}: Readonly<{
  children: ReactNode;
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
  const enhancedChild = React.isValidElement(child)
    ? React.cloneElement(child, {
        'aria-describedby': tooltipId,
      } as React.HTMLAttributes<HTMLElement>)
    : child;

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
    <div
      ref={anchorRef}
      className={cn('relative flex items-center', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
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
                className="absolute -bottom-[5px] size-2.5 border-r border-b border-border-strong bg-panel-strong"
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
