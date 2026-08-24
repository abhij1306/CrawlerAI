import { DatabaseZap, FileChartColumn, KeyRound, Trash2, WandSparkles } from 'lucide-react';
import { Outlet, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';

import { routeMetadataForPath } from '../../src/app/route-registry';
import { useSession } from '../../src/app/session';
import { Button } from '../ui/button';
import { ConfirmDialog } from '../ui/dialog';
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
        <Sidebar
          pathname={pathname}
          isAdmin={session.role === 'admin'}
          accountEmail={session.email}
        />
        <ShellContent pathname={pathname} canResetWorkspace={session.role === 'admin'}>
          {children ?? <Outlet />}
        </ShellContent>
      </div>
    </TopBarProvider>
  );
}

/**
 * Capabilities named after what the app actually ships, using the same icons
 * the nav uses for those routes — so the panel cannot drift into marketing
 * that the product does not back up.
 */
const authHighlights = [
  {
    icon: WandSparkles,
    title: 'Crawl Studio',
    body: 'Configure, launch, and watch runs live with per-site logs.',
  },
  {
    icon: DatabaseZap,
    title: 'Domain memory',
    body: 'Learned selectors, cookies, and profiles retained per domain.',
  },
  {
    icon: FileChartColumn,
    title: 'Data enrichment',
    body: 'Fill gaps in an existing catalog straight from source pages.',
  },
  {
    icon: KeyRound,
    title: 'REST + MCP access',
    body: 'Drive the same pipeline from your own tools with an API key.',
  },
] as const;

export function AuthShell({ children }: Readonly<{ children?: ReactNode }>) {
  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,480px)]">
      {/* Below lg this panel is hidden, leaving the original single centred
          card — so phones and tablets are unaffected by the split. */}
      <aside className="relative hidden flex-col justify-between border-r border-border bg-background-alt p-10 lg:flex">
        <LogoMark auth />

        <div className="max-w-[440px]">
          <h2 className="type-auth-title m-0">Structured product data from any storefront.</h2>
          <ul className="mt-8 flex list-none flex-col gap-5 p-0">
            {authHighlights.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex items-start gap-3">
                {/* Panel-white, not accent-subtle: on the tinted aside the two
                    are nearly the same value and the chip disappears. */}
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-panel shadow-xs">
                  <Icon className="size-4 text-accent-text" strokeWidth={1.75} />
                </span>
                <div className="min-w-0">
                  <p className="type-subheading m-0">{title}</p>
                  <p className="type-body-sm m-0 mt-0.5">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="type-caption m-0">Self-hosted. Your crawl data stays in your workspace.</p>
      </aside>

      <div className="grid place-items-center p-8">
        <div className="w-full max-w-[420px] rounded-xl border border-border bg-panel px-7 pt-6 pb-7 shadow-card">
          <div className="flex items-center justify-between lg:justify-end">
            {/* The mark stays in the card below lg, where the brand panel that
                would otherwise carry it is hidden. */}
            <span className="lg:hidden">
              <LogoMark auth />
            </span>
            <ThemeToggle />
          </div>
          <div className="-mx-7 mt-5 mb-6 border-t border-border-subtle" />
          {children ?? <Outlet />}
        </div>
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
          <h1 className="truncate text-base font-medium text-foreground">{topBar.title}</h1>
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
              className="h-7 gap-1.5 px-2.5 text-sm font-semibold"
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
