import { useQueryErrorResetBoundary } from '@tanstack/react-query';
import { useEffect } from 'react';
import { isRouteErrorResponse, useRouteError } from 'react-router-dom';

import { Button } from '../../components/ui/button';

function errorMessage(error: unknown) {
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`.trim();
  if (import.meta.env.DEV && error instanceof Error) return error.message;
  return 'An unexpected rendering error occurred. Reload the screen to retry.';
}

export function RouteErrorBoundary() {
  const error = useRouteError();
  const { reset } = useQueryErrorResetBoundary();

  useEffect(() => reset(), [reset]);

  return (
    <main className="app-page-frame" role="alert">
      <div className="app-page-inner grid min-h-[50vh] place-items-center">
        <div className="border-border card-gradient max-w-lg space-y-4 rounded-lg border p-6 text-center">
          <div>
            <p className="type-subheading m-0">This screen could not be rendered</p>
            <p className="type-body mt-2">{errorMessage(error)}</p>
          </div>
          <Button type="button" onClick={() => globalThis.location.reload()}>
            Reload screen
          </Button>
        </div>
      </div>
    </main>
  );
}
