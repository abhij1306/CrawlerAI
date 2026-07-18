import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { cn } from '../../lib/utils';
import { navGroups, routeMetadataForPath } from '../../src/app/route-registry';
import { useSession } from '../../src/app/session';
import { Button } from '../ui/button';
import { ConfirmDialog } from '../ui/confirm-dialog';
import type { TopBarState } from './top-bar-context';
import { TopBarProvider, useTopBarHeader } from './top-bar-context';
import { ThemeToggle } from '../ui/theme-toggle';
import { useWorkspaceReset } from './use-workspace-reset';
import { Tooltip } from '../ui/tooltip';

function isNavItemActive(pathname: string, item: (typeof navGroups)[number]['items'][number]) {
  if (item.nav?.exact) return pathname === item.path;
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}

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
    <div className="flex min-h-dvh items-center justify-center bg-background p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-panel p-6 shadow-card">
        <div className="flex items-center justify-between border-b border-border-subtle pb-4">
          <LogoMark auth />
          <ThemeToggle />
        </div>
        <div className="mt-6">{children ?? <Outlet />}</div>
      </div>
    </div>
  );
}

function LogoMark({
  collapsed = false,
  auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
  const mark = (
    <div
      className={cn(
        'flex items-center justify-center rounded-md bg-gradient-to-br from-[#3557f6] to-[#7c5cff] text-white shadow-md overflow-hidden shrink-0',
        auth ? 'size-9' : 'size-6',
      )}
    >
      <img
        src="/crawlerai-logo.svg"
        className="size-full object-cover"
        alt=""
        width={96}
        height={96}
        aria-hidden="true"
        draggable={false}
      />
    </div>
  );

  if (collapsed) {
    return <div className="flex w-full justify-center">{mark}</div>;
  }

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {mark}
      <span className="truncate text-base leading-none font-semibold tracking-tight text-foreground">
        CrawlerAI
      </span>
    </div>
  );
}

function Sidebar({ pathname, isAdmin }: Readonly<{ pathname: string; isAdmin: boolean }>) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    const stored = window.localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
    if (stored === 'true' || stored === 'false') return stored === 'true';
    return window.matchMedia('(max-width: 1279px)').matches;
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, String(collapsed));
  }, [collapsed]);

  return (
    <aside
      className={cn(
        'flex shrink-0 flex-col gap-4 border-r border-border bg-sidebar p-4 transition-all duration-150 ease-in-out',
        collapsed ? 'w-[58px] p-2 items-center' : 'w-60',
      )}
    >
      <div
        className={cn(
          'flex h-[38px] shrink-0 items-center justify-between gap-2 w-full',
          collapsed && 'justify-center',
        )}
      >
        <LogoMark collapsed={collapsed} />
        {!collapsed && (
          <Button
            id="app-sidebar-toggle"
            data-testid="app-sidebar-toggle"
            variant="ghost"
            size="icon"
            onClick={() => setCollapsed((value) => !value)}
            aria-controls="app-sidebar-navigation"
            aria-expanded={!collapsed}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="size-7 rounded-md"
          >
            <ChevronLeft className="size-4 shrink-0 text-secondary" />
          </Button>
        )}
      </div>

      {collapsed && (
        <Button
          id="app-sidebar-toggle-collapsed"
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed((value) => !value)}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="size-7 rounded-md"
        >
          <ChevronRight className="size-4 shrink-0 text-secondary" />
        </Button>
      )}

      <nav
        id="app-sidebar-navigation"
        className="flex min-h-0 w-full flex-1 flex-col gap-5 overflow-y-auto"
        aria-label="Main navigation"
      >
        {navGroups
          .filter((group) => isAdmin || group.label !== 'Admin')
          .map((group) => (
            <div key={group.label} className="flex w-full flex-col gap-1">
              {!collapsed && (
                <p className="px-2.5 text-[10px] font-semibold tracking-wider text-muted uppercase opacity-75">
                  {group.label}
                </p>
              )}
              <ul className="flex w-full flex-col gap-0.5">
                {group.items.map((item) => {
                  const active = isNavItemActive(pathname, item);
                  const Icon = item.nav!.icon;
                  const itemLink = (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors w-full',
                        active
                          ? 'bg-accent-subtle text-accent-text'
                          : 'text-secondary hover:bg-background-alt hover:text-foreground',
                        collapsed && 'px-0 justify-center h-9 w-9 rounded-md',
                      )}
                    >
                      <Icon className="size-4 shrink-0" strokeWidth={2} />
                      {!collapsed && <span className="truncate">{item.nav!.label}</span>}
                    </Link>
                  );

                  if (collapsed) {
                    return (
                      <li key={item.path} className="flex w-full justify-center">
                        <Tooltip content={item.nav!.label}>{itemLink}</Tooltip>
                      </li>
                    );
                  }

                  return <li key={item.path}>{itemLink}</li>;
                })}
              </ul>
            </div>
          ))}
      </nav>

      {!collapsed && (
        <div className="mt-auto w-full border-t border-border-subtle pt-2">
          <div className="flex items-center justify-between px-2 py-1">
            <div className="min-w-0">
              <div className="text-2xs font-semibold tracking-wide text-muted uppercase">
                Display
              </div>
              <div className="truncate text-[11px] text-secondary">Theme preference</div>
            </div>
            <ThemeToggle />
          </div>
        </div>
      )}
    </aside>
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
      <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-border bg-panel px-4">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold text-foreground">{topBar.title}</h1>
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
