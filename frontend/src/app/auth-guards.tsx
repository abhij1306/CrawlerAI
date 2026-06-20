import { useQuery } from '@tanstack/react-query';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { httpErrorStatus } from '@/api/errors';
import { getAuthSessionQueryOptions } from '../../components/layout/auth-session-query';
import { ThemeToggle } from '../../components/ui/theme-toggle';
import { SessionProvider, useSession } from './session';

function SessionLoading() {
  return (
    <div className="app-shell-feedback" aria-busy="true" aria-live="polite">
      <div className="border-border card-gradient w-full max-w-sm space-y-3 rounded-lg border p-6">
        <div className="skeleton h-5 w-36" />
        <div className="skeleton h-3 w-full" />
      </div>
    </div>
  );
}

export function RequireSession() {
  const location = useLocation();
  const sessionQuery = useQuery(getAuthSessionQueryOptions());

  if (sessionQuery.isPending) return <SessionLoading />;
  if (httpErrorStatus(sessionQuery.error) === 401) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (sessionQuery.error || !sessionQuery.data) {
    return (
      <div className="app-shell-feedback" role="alert">
        <div className="border-border card-gradient max-w-sm rounded-lg border p-6 text-center">
          <p className="type-subheading">Unable to load session</p>
          <p className="text-secondary mt-1.5 text-sm leading-relaxed">
            Refresh to retry, or sign in again if the session expired.
          </p>
          <div className="mt-4 flex justify-center">
            <ThemeToggle compact />
          </div>
        </div>
      </div>
    );
  }

  return (
    <SessionProvider user={sessionQuery.data}>
      <Outlet />
    </SessionProvider>
  );
}

export function RequireAdmin() {
  const session = useSession();
  return session.role === 'admin' ? <Outlet /> : <Navigate to="/dashboard" replace />;
}
