'use client';

// Next.js App Router error boundary; invoked by file-system routing.
import { Button } from '../components/ui/button';

// skipcq: JS-0067
export default function ErrorBoundary({
  error: _error,
  reset,
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-3xl flex-col justify-center px-6 py-16">
      <div className="border-border bg-panel space-y-4 rounded-md border p-6">
        <div>
          <p className="type-label">Application Error</p>
          <h1 className="type-heading-2 mt-2">Something went wrong.</h1>
        </div>
        <p className="type-body-sm">The page hit an unexpected error. Try reloading this view.</p>
        <Button type="button" onClick={reset}>
          Try again
        </Button>
      </div>
    </main>
  );
}
