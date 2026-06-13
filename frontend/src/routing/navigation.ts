import { Navigate, UNSAFE_LocationContext, UNSAFE_NavigationContext } from 'react-router-dom';
import { useContext } from 'react';

export { Navigate };

export function usePathname() {
  const locationContext = useContext(UNSAFE_LocationContext);
  return (
    locationContext?.location.pathname ??
    (typeof window === 'undefined' ? '/' : window.location.pathname)
  );
}

export function useSearchParams() {
  const locationContext = useContext(UNSAFE_LocationContext);
  return new URLSearchParams(
    locationContext?.location.search ??
      (typeof window === 'undefined' ? '' : window.location.search),
  );
}

export function useRouter() {
  const navigationContext = useContext(UNSAFE_NavigationContext);
  const navigator = navigationContext?.navigator;
  return {
    push: (href: string) => {
      if (navigator) {
        navigator.push(href);
      } else {
        window.location.assign(href);
      }
    },
    replace: (href: string) => {
      if (navigator) {
        navigator.replace(href);
      } else {
        window.location.replace(href);
      }
    },
    back: () => window.history.back(),
    forward: () => window.history.forward(),
    refresh: () => window.location.reload(),
  };
}
