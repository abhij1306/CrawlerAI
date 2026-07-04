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
import './app-shell.module.css';
import './auth-shell.module.css';

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
      <div className="app-shell-root">
        <a
          href="#main-content"
          className="ui-on-accent-surface sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to main content
        </a>
        <div className="app-shell-grid">
          <Sidebar pathname={pathname} isAdmin={session.role === 'admin'} />
          <ShellContent pathname={pathname} canResetWorkspace={session.role === 'admin'}>
            {children ?? <Outlet />}
          </ShellContent>
        </div>
      </div>
    </TopBarProvider>
  );
}

export function AuthShell({ children }: Readonly<{ children?: ReactNode }>) {
  return (
    <div className="auth-shell">
      <div className="auth-shell-card">
        <div className="auth-shell-header">
          <div className="auth-shell-brand">
            <LogoMark auth />
          </div>
          <ThemeToggle compact />
        </div>
        {children ?? <Outlet />}
      </div>
    </div>
  );
}

function LogoMark({
  collapsed = false,
  auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
  const mark = (
    <img
      src="/crawlerai-logo.svg"
      className="app-logo-image"
      alt=""
      width={96}
      height={96}
      aria-hidden="true"
      draggable={false}
    />
  );

  if (collapsed) {
    return (
      <div className="app-logo app-logo-collapsed">
        <div className="app-logo-mark">{mark}</div>
      </div>
    );
  }

  return (
    <div className="app-logo">
      <div className={cn('app-logo-mark', auth && 'app-logo-mark-large')}>{mark}</div>
      <div className="app-logo-copy">
        <span className="app-logo-title">CrawlerAI</span>
      </div>
    </div>
  );
}

// skipcq: JS-0067
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
    <aside className={cn('app-sidebar', collapsed && 'is-collapsed')}>
      <div className="app-sidebar-header">
        <LogoMark collapsed={collapsed} />
        <button
          id="app-sidebar-toggle"
          data-testid="app-sidebar-toggle"
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="app-icon-button"
          aria-controls="app-sidebar-navigation"
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
        </button>
      </div>

      <nav id="app-sidebar-navigation" className="app-sidebar-nav" aria-label="Main navigation">
        {navGroups
          .filter((group) => isAdmin || group.label !== 'Admin')
          .map((group) => (
            <div key={group.label} className="app-sidebar-group">
              <div className="space-y-1">
                {group.items.map((item) => {
                  const active = isNavItemActive(pathname, item);
                  const Icon = item.nav!.icon;
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      title={collapsed ? item.nav!.label : undefined}
                      className={cn(
                        'app-nav-item relative',
                        active && 'is-active',
                        collapsed && 'is-collapsed',
                      )}
                    >
                      <Icon className="app-nav-icon" />
                      {!collapsed && <span className="truncate">{item.nav!.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
      </nav>

      {!collapsed && (
        <div className="app-sidebar-footer">
          <div className="app-sidebar-footer-row">
            <div>
              <div className="app-sidebar-footer-title">Display</div>
              <div className="app-sidebar-footer-subtitle">Theme preference</div>
            </div>
            <ThemeToggle compact />
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
    <div className="app-main-col">
      <header className="app-topbar">
        <div className="app-topbar-main">
          <h1 className="app-topbar-title">{topBar.title}</h1>
        </div>
        <div className="app-topbar-actions">
          {topBar.actions ? (
            <div className="flex flex-wrap items-center gap-2">{topBar.actions}</div>
          ) : null}
          {canResetWorkspace ? (
            <div className="flex items-center gap-2">
              <Button
                ref={resetTriggerRef}
                type="button"
                onClick={handleSelectedReset}
                disabled={resetPending}
                variant="destructive"
                size="sm"
              >
                <Trash2 className="size-3" />
                {resetLabel}
              </Button>
            </div>
          ) : null}
          <ThemeToggle compact />
        </div>
      </header>

      <main id="main-content" className="app-page-frame">
        <div className="app-page-inner">{children}</div>
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
          overlayClassName="overlay-scrim fixed inset-0 z-[100] grid place-items-center p-4"
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
