import { useCallback, useSyncExternalStore } from 'react';

/**
 * Reactive media query, following the useSyncExternalStore pattern already used
 * by ThemeToggle.
 *
 * The app previously read matchMedia exactly once, inside a useState
 * initialiser, so rotating a device or resizing a window changed nothing. This
 * subscribes properly.
 */
function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener('change', onStoreChange);
      return () => list.removeEventListener('change', onStoreChange);
    },
    [query],
  );

  const getSnapshot = useCallback(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  }, [query]);

  // Server/prerender has no viewport; assume desktop so the shell renders its
  // normal layout rather than flashing the mobile one.
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

/**
 * Below Tailwind's `md` breakpoint (768px).
 *
 * Kept in sync with the `max-md:` variants the mobile layout uses — if this
 * number changes, those change with it.
 */
const MOBILE_MEDIA_QUERY = '(max-width: 767px)';

export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_MEDIA_QUERY);
}
