import { useMemo } from 'react';
import {
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams as useReactRouterSearchParams,
} from 'react-router-dom';

export { Navigate };

export function usePathname() {
  return useLocation().pathname;
}

export function useSearchParams() {
  const [searchParams] = useReactRouterSearchParams();
  return searchParams;
}

export function useRouter() {
  const navigate = useNavigate();

  return useMemo(
    () => ({
      push: (href: string) => navigate(href),
      replace: (href: string) => navigate(href, { replace: true }),
      back: () => navigate(-1),
      forward: () => navigate(1),
      refresh: () => window.location.reload(),
    }),
    [navigate],
  );
}
