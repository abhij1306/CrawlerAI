import type { RouteObject } from 'react-router-dom';
import { Navigate, RouterProvider, createBrowserRouter, useParams } from 'react-router-dom';

import { AppShell } from '../../components/layout/app-shell';
import { AuthShell } from '../../components/layout/auth-shell';
import { QueryProvider } from '../../components/ui/query-provider';
import { RequireAdmin, RequireSession } from './auth-guards';
import { RouteErrorBoundary } from './error-boundary';
import { appRoutes, type AppRoute } from './route-registry';

function routeObject(route: AppRoute): RouteObject {
  return {
    path: route.path,
    lazy: async () => ({ Component: (await route.lazy()).default }),
    HydrateFallback: AppHydrateFallback,
    errorElement: <RouteErrorBoundary />,
  };
}

// Rendered by the data router during initial hydration while the matched route's
// lazy chunk is still loading. Without it React Router renders `null` (a blank
// screen) on first load / refresh and logs the "No `HydrateFallback` element
// provided" warning. On the heavy lazy routes that blank window reads as a hang.
function AppHydrateFallback() {
  return (
    <div className="app-shell-feedback" aria-busy="true" aria-live="polite">
      <div className="card-gradient w-full max-w-sm space-y-3 rounded-lg border border-border p-6">
        <div className="skeleton h-5 w-36" />
        <div className="skeleton h-3 w-full" />
      </div>
    </div>
  );
}

function RunDetailRedirect() {
  const params = useParams();
  return <Navigate to={`/crawl?run_id=${encodeURIComponent(params.run_id ?? '')}`} replace />;
}

function CrawlModeRedirect({ module, mode }: Readonly<{ module: string; mode?: string }>) {
  const search = new URLSearchParams({ module });
  if (mode) search.set('mode', mode);
  return <Navigate to={`/crawl?${search.toString()}`} replace />;
}

const publicRoutes = appRoutes.filter((route) => route.access === 'public').map(routeObject);
const authenticatedRoutes = appRoutes
  .filter((route) => route.access === 'authenticated')
  .map(routeObject);
const adminRoutes = appRoutes.filter((route) => route.access === 'admin').map(routeObject);

const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/dashboard" replace /> },
  {
    element: <AuthShell />,
    children: publicRoutes,
  },
  {
    element: <RequireSession />,
    children: [
      {
        element: <AppShell />,
        children: [
          ...authenticatedRoutes,
          {
            element: <RequireAdmin />,
            children: adminRoutes,
          },
          {
            path: '/crawl/category',
            element: <CrawlModeRedirect module="category" mode="category" />,
          },
          {
            path: '/crawl/pdp',
            element: <CrawlModeRedirect module="pdp" mode="single" />,
          },
          {
            path: '/crawl/bulk',
            element: <CrawlModeRedirect module="pdp" mode="batch" />,
          },
          { path: '/runs/:run_id', element: <RunDetailRedirect /> },
          { path: '*', element: <Navigate to="/dashboard" replace /> },
        ],
      },
    ],
  },
]);

export function App() {
  return (
    <QueryProvider>
      <RouterProvider router={router} />
    </QueryProvider>
  );
}
