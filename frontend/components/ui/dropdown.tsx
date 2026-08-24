import * as React from 'react';
import { useId } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../lib/utils';

const DROPDOWN_LISTBOX_ROLE = 'listbox';
const ESTIMATED_ITEM_HEIGHT_PX = 36;
const ESTIMATED_MENU_PADDING_PX = 8;

function sanitizeIdSegment(value: string) {
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-');
  return normalized.replace(/^-+/g, '').replace(/-+$/g, '') || 'option';
}

function activeOptionId<T extends string>(
  dropdownId: string,
  options: Array<{ value: T }>,
  activeIndex: number,
) {
  if (activeIndex < 0) return undefined;
  return `${dropdownId}-option-${activeIndex}-${sanitizeIdSegment(options[activeIndex].value)}`;
}

function warnForMissingValue<T extends string>(
  value: T,
  options: Array<{ value: T }>,
  activeIndex: number,
) {
  if (import.meta.env.DEV && activeIndex === -1 && options.length > 0) {
    console.warn(`Dropdown: value "${value}" not found in options`);
  }
}

function mountListbox(element: React.ReactNode, open: boolean, portal: boolean) {
  if (!open || typeof document === 'undefined') return null;
  return portal ? createPortal(element, document.body) : element;
}

type DropdownPosition = {
  top: number;
  left: number;
  width: number;
  side: 'top' | 'bottom';
};

function DropdownListbox<T extends string>({
  listboxRef,
  listboxId,
  dropdownId,
  options,
  value,
  align,
  portal,
  position,
  onChange,
  onClose,
  onMouseEnter,
  onMouseLeave,
}: {
  listboxRef: React.RefObject<HTMLDivElement | null>;
  listboxId: string;
  dropdownId: string;
  options: Array<{ value: T; label: string }>;
  value: T;
  align: 'left' | 'center';
  portal: boolean;
  position: DropdownPosition;
  onChange: (value: T) => void;
  onClose: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}) {
  const style = portal
    ? {
        top: `${position.top}px`,
        left: `${position.left}px`,
        minWidth: `${position.width}px`,
      }
    : {
        minWidth: '100%',
        top: position.side === 'top' ? 'auto' : '100%',
        bottom: position.side === 'top' ? '100%' : 'auto',
        transform: position.side === 'top' ? 'translateY(-4px)' : 'translateY(4px)',
      };
  return (
    <div
      ref={listboxRef}
      id={listboxId}
      role={DROPDOWN_LISTBOX_ROLE}
      tabIndex={-1}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={cn(
        'border-border bg-background-elevated z-[300] max-h-[320px] w-max overflow-y-auto rounded-lg border py-1',
        portal ? 'fixed' : 'absolute',
        position.side === 'bottom'
          ? 'animate-[dropdown-in_150ms_cubic-bezier(0.16,1,0.3,1)]'
          : 'animate-[dropdown-in-up_150ms_cubic-bezier(0.16,1,0.3,1)]',
      )}
      style={style}
    >
      {options.map((option, index) => (
        <button
          key={option.value}
          id={`${dropdownId}-option-${index}-${sanitizeIdSegment(option.value)}`}
          type="button"
          role="option"
          aria-selected={option.value === value}
          onClick={() => {
            onChange(option.value);
            onClose();
          }}
          onMouseDown={(event) => event.preventDefault()}
          className={cn(
            'text-sm flex w-full items-center py-2 leading-snug transition-colors',
            align === 'center' ? 'justify-center px-8' : 'justify-start px-3',
            option.value === value
              ? 'bg-accent-subtle text-accent font-medium'
              : 'text-foreground hover:bg-background-alt',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Dropdown<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
  disabled = false,
  align = 'left',
  size = 'md',
  portal = true,
}: Readonly<{
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: string }>;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
  align?: 'left' | 'center';
  size?: 'sm' | 'md';
  portal?: boolean;
}>) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const listboxRef = React.useRef<HTMLDivElement>(null);
  const [listboxPosition, setListboxPosition] = React.useState<DropdownPosition>({
    top: 0,
    left: 0,
    width: 0,
    side: 'bottom',
  });
  const closeTimerRef = React.useRef<number | undefined>(undefined);
  const dropdownId = useId().replace(/[^a-zA-Z0-9_-]+/g, '') || 'dropdown';
  const activeIndex = options.findIndex((o) => o.value === value);
  const listboxId = `${dropdownId}-listbox`;
  const activeDescendant = activeOptionId(dropdownId, options, activeIndex);
  warnForMissingValue(value, options, activeIndex);

  function scheduleClose() {
    closeTimerRef.current = window.setTimeout(() => setOpen(false), 120) as unknown as number;
  }

  function cancelClose() {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = undefined;
    }
  }

  const updatePosition = React.useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const menuHeight =
      listboxRef.current?.offsetHeight ??
      options.length * ESTIMATED_ITEM_HEIGHT_PX + ESTIMATED_MENU_PADDING_PX;
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const shouldFlip = spaceBelow < menuHeight && rect.top > menuHeight;

    setListboxPosition({
      top: shouldFlip ? rect.top - menuHeight - 4 : rect.bottom + 4,
      left: rect.left,
      width: rect.width,
      side: shouldFlip ? 'top' : 'bottom',
    });
  }, [options.length]);

  React.useLayoutEffect(() => {
    if (open) {
      updatePosition();
      const handleResize = () => updatePosition();
      const handleScroll = () => updatePosition();
      window.addEventListener('resize', handleResize);
      window.addEventListener('scroll', handleScroll, true);
      return () => {
        window.removeEventListener('resize', handleResize);
        window.removeEventListener('scroll', handleScroll, true);
      };
    }
  }, [open, updatePosition]);

  React.useEffect(() => {
    const closeTimer = closeTimerRef;
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
    };
  }, []);

  React.useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node) &&
        listboxRef.current &&
        !listboxRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open && (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown')) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (activeIndex + 1) % options.length;
      onChange(options[next].value);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (activeIndex - 1 + options.length) % options.length;
      onChange(options[prev].value);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setOpen(false);
    }
  }

  const selectedLabel = options[activeIndex]?.label ?? value;

  const listboxElement = (
    <DropdownListbox
      listboxRef={listboxRef}
      listboxId={listboxId}
      dropdownId={dropdownId}
      options={options}
      value={value}
      align={align}
      portal={portal}
      position={listboxPosition}
      onChange={onChange}
      onClose={() => setOpen(false)}
      onMouseEnter={cancelClose}
      onMouseLeave={scheduleClose}
    />
  );

  return (
    <div
      ref={containerRef}
      className={cn('relative', className)}
      onMouseEnter={() => {
        if (!disabled) {
          cancelClose();
          setOpen(true);
        }
      }}
      onMouseLeave={() => {
        if (open) scheduleClose();
      }}
    >
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-activedescendant={activeDescendant}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        className={cn(
          'focus-ring border-border bg-panel text-foreground hover:border-border-strong focus:border-accent flex w-full items-center gap-2 rounded-sm border px-3 text-sm leading-snug font-normal transition-[background-color,border-color]',
          size === 'sm' ? 'h-8' : 'h-[var(--control-height)]',
          align === 'center' ? 'justify-center text-center' : 'justify-between text-left',
          className,
        )}
      >
        <span className="truncate">{selectedLabel}</span>
        <svg
          className={cn(
            'text-muted size-3.5 shrink-0 transition-transform duration-150',
            open && 'rotate-180',
            align === 'center' ? 'absolute right-3' : 'relative',
          )}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>
      {mountListbox(listboxElement, open, portal)}
    </div>
  );
}
