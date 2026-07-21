import { cn } from '../../lib/utils';

export function Toggle({
  checked,
  onChange,
  ariaLabel,
}: Readonly<{ checked: boolean; onChange: (v: boolean) => void; ariaLabel: string }>) {
  const trackClass = checked ? 'toggle-track-on' : 'toggle-track-off';
  return (
    <button
      type="button"
      role="switch"
      aria-label={ariaLabel}
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'focus-ring relative inline-flex h-[20px] w-[34px] shrink-0 cursor-pointer items-center rounded-full transition-[background-color]',
        trackClass,
      )}
    >
      <span
        className={cn(
          'toggle-thumb-shadow inline-block h-[14px] w-[14px] rounded-full transition-transform',
          checked ? 'translate-x-[14px]' : 'translate-x-[2px]',
          'toggle-thumb',
        )}
      />
    </button>
  );
}
