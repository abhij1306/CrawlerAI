import { Menu, Trash2 } from 'lucide-react';
import { Outlet, useLocation } from 'react-router-dom';
import { useEffect, useState, type ReactNode } from 'react';

import { useIsMobile } from '../../lib/ui/use-media-query';

import { routeMetadataForPath } from '../../src/app/route-registry';
import { useSession } from '../../src/app/session';
import { Button } from '../ui/button';
import { AppDrawer, ConfirmDialog } from '../ui/dialog';
import type { TopBarState } from './top-bar-context';
import { TopBarProvider, useTopBarHeader } from './top-bar-context';
import { ThemeToggle } from '../ui/theme-toggle';
import { useWorkspaceReset } from './use-workspace-reset';
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
  const isMobile = useIsMobile();
  const [navOpen, setNavOpen] = useState(false);

  // Navigating from inside the drawer should close it.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  const sidebar = (
    <Sidebar
      pathname={pathname}
      isAdmin={session.role === 'admin'}
      accountEmail={session.email}
      // Inside the drawer there is nothing to collapse into.
      collapsible={!isMobile}
    />
  );

  return (
    <TopBarProvider>
      <div className="flex h-dvh overflow-hidden bg-background text-foreground">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-base focus:text-accent-fg"
        >
          Skip to main content
        </a>
        {/* Desktop takes the identical code path it always has; only the
            mobile branch is new. */}
        {isMobile ? (
          <AppDrawer
            open={navOpen}
            onOpenChange={setNavOpen}
            side="left"
            title="Navigation"
            className="w-[264px]"
          >
            {sidebar}
          </AppDrawer>
        ) : (
          sidebar
        )}
        <ShellContent
          pathname={pathname}
          canResetWorkspace={session.role === 'admin'}
          isMobile={isMobile}
          onOpenNav={() => setNavOpen(true)}
        >
          {children ?? <Outlet />}
        </ShellContent>
      </div>
    </TopBarProvider>
  );
}

function ShellContent({
  children,
  pathname,
  canResetWorkspace,
  isMobile,
  onOpenNav,
}: Readonly<{
  children: ReactNode;
  pathname: string;
  canResetWorkspace: boolean;
  isMobile: boolean;
  onOpenNav: () => void;
}>) {
  const header = useTopBarHeader();
  const topBar = header?.pathKey === pathname ? header : getFallbackHeader(pathname);
  const {
    executeReset,
    handleSelectedReset,
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
        <div className="flex min-w-0 shrink items-center gap-2">
          {isMobile ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onOpenNav}
              aria-label="Open navigation"
              data-testid="app-nav-open"
              className="-ml-1 size-8 shrink-0 rounded-md"
            >
              <Menu className="size-4" />
            </Button>
          ) : null}
          {/* Hidden on phones: the 48px bar cannot hold the title and the
              page's own actions, and the open drawer already marks the
              current page. */}
          <h1 className="truncate text-base font-medium text-foreground max-md:hidden">
            {topBar.title}
          </h1>
        </div>
        <div className="flex min-w-0 shrink items-center gap-1.5 max-md:overflow-x-auto">
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
              className="h-7 gap-1.5 px-2.5 text-base font-semibold max-md:px-2"
              aria-label={resetLabel}
            >
              <Trash2 className="size-3.5" />
              {/* Label drops on phones so the 48px bar does not crowd. */}
              <span className="max-md:hidden">{resetLabel}</span>
            </Button>
          ) : null}
          <ThemeToggle />
        </div>
      </header>

      <main
        id="main-content"
        tabIndex={-1}
        className="min-h-0 flex-1 overflow-y-auto max-md:overflow-x-auto"
      >
        <div className="mx-auto w-full max-w-[1440px] p-[var(--content-gutter)] pb-[max(var(--content-gutter),env(safe-area-inset-bottom))]">
          {children}
        </div>
      </main>

      {canResetWorkspace ? (
        <ConfirmDialog
          open={resetDialogOpen}
          onOpenChange={setResetDialogOpen}
          title={resetDialogCopy.title}
          description={resetDialogCopy.description}
          confirmLabel={resetDialogCopy.confirmLabel}
          pending={resetPending}
          danger
          error={resetError}
          contentRef={(node) => {
            resetDialogRef.current = node as HTMLDialogElement | null;
          }}
          onConfirm={() => void executeReset()}
        />
      ) : null}
    </div>
  );
}

function getFallbackHeader(pathname: string): TopBarState {
  return routeMetadataForPath(pathname);
}
