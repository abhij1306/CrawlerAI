import { Trash2 } from 'lucide-react';
import { Outlet, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';

import { routeMetadataForPath } from '../../src/app/route-registry';
import { useSession } from '../../src/app/session';
import { Button } from '../ui/button';
import { ConfirmDialog } from '../ui/confirm-dialog';
import type { TopBarState } from './top-bar-context';
import { TopBarProvider, useTopBarHeader } from './top-bar-context';
import { ThemeToggle } from '../ui/theme-toggle';
import { useWorkspaceReset } from './use-workspace-reset';
import { LogoMark } from './logo-mark';
import { Sidebar } from './sidebar';

const resetDialogCopy = {
  title: 'Reset workspace data',
  description:
    'Delete crawl runs, records, logs, artifacts, runtime cookie files, learned domain memory, extraction preferences, saved cookie memory, field feedback, host protection memory, Product Intelligence data, and Data Enrichment data.',
  confirmLabel: 'Reset Workspace Data',
} as const;

export function AppShell({ children }: Readonly<{ children?: ReactNode }>) {
  const { pathname } = useLocation();
  const session = useSession();

  return (
    <TopBarProvider>
      <div className="flex h-dvh overflow-hidden bg-background text-foreground">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:text-accent-fg"
        >
          Skip to main content
        </a>
        <Sidebar pathname={pathname} isAdmin={session.role === 'admin'} />
        <ShellContent pathname={pathname} canResetWorkspace={session.role === 'admin'}>
          {children ?? <Outlet />}
        </ShellContent>
      </div>
    </TopBarProvider>
  );
}

export function AuthShell({ children }: Readonly<{ children?: ReactNode }>) {
  return (
    <div className="grid min-h-dvh place-items-center bg-background p-8">
      <div className="w-full max-w-[420px] rounded-xl border border-border bg-panel px-7 pt-6 pb-7 shadow-card">
        <div className="flex items-center justify-between">
          <LogoMark auth />
          <ThemeToggle />
        </div>
        <div className="-mx-7 mt-5 mb-6 border-t border-border-subtle" />
        {children ?? <Outlet />}
      </div>
    </div>
  );
}

function ShellContent({
  children,
  pathname,
  canResetWorkspace,
}: Readonly<{ children: ReactNode; pathname: string; canResetWorkspace: boolean }>) {
  const header = useTopBarHeader();
  const topBar = header?.pathKey === pathname ? header : getFallbackHeader(pathname);
  const {
    executeReset,
    handleSelectedReset,
    resetConfirmRef,
    resetDialogOpen,
    resetDialogRef,
    resetError,
    resetLabel,
    resetPending,
    resetTriggerRef,
    setResetDialogOpen,
  } = useWorkspaceReset(canResetWorkspace);

  return (
    <div className="flex h-dvh min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border bg-panel px-4">
        <div className="min-w-0">
          <h1 className="truncate text-[13px] font-medium text-foreground">{topBar.title}</h1>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {topBar.actions ? (
            <div className="flex items-center gap-1.5">{topBar.actions}</div>
          ) : null}
          {canResetWorkspace ? (
            <Button
              ref={resetTriggerRef}
              type="button"
              onClick={handleSelectedReset}
              disabled={resetPending}
              variant="destructive"
              size="sm"
              className="h-7 gap-1.5 px-2.5 text-xs font-semibold"
            >
              <Trash2 className="size-3.5" />
              {resetLabel}
            </Button>
          ) : null}
          <ThemeToggle />
        </div>
      </header>

      <main id="main-content" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1440px] p-[var(--content-gutter)]">{children}</div>
      </main>

      {canResetWorkspace && resetDialogOpen ? (
        <ConfirmDialog
          dialogRef={resetDialogRef}
          confirmRef={resetConfirmRef}
          titleId="reset-workspace-title"
          descriptionId="reset-workspace-description"
          title={resetDialogCopy.title}
          description={resetDialogCopy.description}
          error={resetError}
          pending={resetPending}
          pendingLabel="Working…"
          confirmLabel={resetDialogCopy.confirmLabel}
          onCancel={() => setResetDialogOpen(false)}
          onConfirm={() => void executeReset()}
        />
      ) : null}
    </div>
  );
}

function getFallbackHeader(pathname: string): TopBarState {
  return routeMetadataForPath(pathname);
}
