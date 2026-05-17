'use client';

// Next.js App Router error boundary; invoked by file-system routing.
import { Button } from '../components/ui/button';

export default function Error({
  reset,
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-3xl flex-col justify-center px-6 py-16">
      <div className="border-border bg-panel space-y-4 rounded-[var(--radius-md)] border p-6">
        <div>
          <p className="text-muted text-[length:var(--text-xs)] font-semibold uppercase">
            Application Error
          </p>
          <h1 className="text-foreground mt-2 text-[length:var(--text-xl)] font-semibold">
            Something went wrong.
          </h1>
        </div>
        <p className="text-secondary text-[length:var(--text-sm)]">
          The page hit an unexpected error. Try reloading this view.
        </p>
        <Button type="button" onClick={reset}>
          Try again
        </Button>
      </div>
    </main>
  );
}
