'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Image from 'next/image';
import Link from 'next/link';
import type { Route } from 'next';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import type { ComponentType, ReactNode } from 'react';
import {
  BrainCircuit,
  BriefcaseBusiness,
  Bell,
  Check,
  ClipboardCheck,
  ChevronLeft,
  ChevronRight,
  Clock3,
  DatabaseZap,
  FileChartColumn,
  FolderKanban,
  Grid2x2,
  Network,
  Radar,
  SearchCheck,
  Settings2,
  Sparkles,
  ShieldCheck,
  Trash2,
  WandSparkles,
  Zap,
} from 'lucide-react';

import { api, monitorsApi } from '../../lib/api';
import { httpErrorStatus } from '../../lib/api/client';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { trapFocus } from '../../lib/focus-trap';
import { formatRelativeTime } from '../../lib/format/date';
import { cn } from '../../lib/utils';
import { getAuthSessionQueryOptions, isAuthRoute } from './auth-session-query';
import { Button } from '../ui/button';
import type { TopBarState } from './top-bar-context';
import { TopBarProvider, useTopBarHeader } from './top-bar-context';
import { ThemeToggle } from '../ui/theme-toggle';
import './app-shell.module.css';
import './auth-shell.module.css';

const navGroups = [
  {
    label: 'Workspace',
    items: [
      { href: '/dashboard', label: 'Dashboard', icon: Grid2x2 },
      { href: '/playground', label: 'Playground', icon: FolderKanban },
      { href: '/crawl', label: 'Crawl Studio', icon: WandSparkles },
      { href: '/runs', label: 'History', icon: Clock3 },
      { href: '/monitors', label: 'Monitors', icon: Radar },
      { href: '/alerts', label: 'Product Alerts', icon: Bell },
      { href: '/data-enrichment', label: 'Data Enrichment', icon: FileChartColumn },
      { href: '/product-intelligence', label: 'Product Intelligence', icon: BrainCircuit },
      { href: '/ucp-audit', label: 'AI Discoverability', icon: ClipboardCheck },
      { href: '/run-trace', label: 'Run Trace', icon: Network },
      { href: '/selectors', label: 'Selector Tool', icon: SearchCheck, exactMatch: true },
      { href: '/selectors/manage', label: 'Domain Memory', icon: DatabaseZap },
      { href: '/jobs', label: 'Jobs', icon: BriefcaseBusiness },
    ],
  },
  {
    label: 'Admin',
    items: [
      { href: '/admin/users', label: 'Users', icon: ShieldCheck },
      { href: '/admin/llm', label: 'LLM Config', icon: Settings2 },
    ],
  },
] as const satisfies ReadonlyArray<{
  label: string;
  items: ReadonlyArray<{
    href: string;
    label: string;
    icon: ComponentType<{ className?: string }>;
    exactMatch?: boolean;
  }>;
}>;

function isNavItemActive(
  pathname: string,
  item: (typeof navGroups)[number]['items'][number],
): boolean {
  if ('exactMatch' in item && item.exactMatch) {
    return pathname === item.href;
  }
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

const navItemCount = navGroups.reduce((total, group) => total + group.items.length, 0);

const resetDialogCopy = {
  title: 'Reset workspace data',
  description:
    'Delete crawl runs, records, logs, artifacts, runtime cookie files, learned domain memory, saved cookie memory, field feedback, host protection memory, Product Intelligence data, Data Enrichment data, and AI Discoverability reports.',
  confirmLabel: 'Reset Workspace Data',
} as const;

const resetForbiddenMessage =
  'The API refused reset (admin-only on an older backend build, or a stale session). Stop and restart the FastAPI server so it loads the latest code, then try again, or sign out and sign back in.';

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const authRoute = isAuthRoute(pathname);

  const authQuery = useQuery(getAuthSessionQueryOptions(pathname));

  useEffect(() => {
    if (!authRoute && authQuery.error && httpErrorStatus(authQuery.error) === 401) {
      router.replace('/login');
    }
  }, [authQuery.error, authRoute, router]);

  if (authRoute) {
    return <AuthShell>{children}</AuthShell>;
  }

  if (authQuery.isPending) {
    return (
      <div className="app-shell-root">
        <div className="app-shell-grid">
          <aside className="app-sidebar">
            <div className="app-sidebar-header">
              <LogoMark />
            </div>
            <div className="app-sidebar-nav">
              {Array.from({ length: navItemCount }, (_, index) => (
                <div key={index} className="skeleton h-8 w-full rounded-[var(--radius-md)]" />
              ))}
            </div>
          </aside>
          <div className="app-main-col">
            <div className="app-topbar">
              <div className="skeleton h-4 w-36" />
            </div>
            <main className="app-page-frame">
              <div className="app-page-inner page-stack-lg">
                <div className="grid grid-cols-4 gap-3">
                  {Array.from({ length: 4 }, (_, index) => (
                    <div
                      key={index}
                      className="border-border card-gradient space-y-3 rounded-[var(--radius-lg)] border p-4"
                    >
                      <div className="skeleton h-3 w-20" />
                      <div className="skeleton h-8 w-28" />
                    </div>
                  ))}
                </div>
                <div className="skeleton h-72 w-full rounded-[var(--radius-lg)]" />
              </div>
            </main>
          </div>
        </div>
      </div>
    );
  }

  if (authQuery.error && httpErrorStatus(authQuery.error) === 401) {
    return (
      <div className="app-shell-feedback">
        <div className="border-border card-gradient max-w-sm rounded-[var(--radius-lg)] border p-6 text-center">
          <p className="text-foreground type-heading text-base leading-snug font-semibold">
            Session expired
          </p>
          <p className="text-secondary mt-1.5 text-sm leading-[var(--leading-relaxed)]">
            Redirecting to login…
          </p>
        </div>
      </div>
    );
  }

  if (authQuery.error) {
    return (
      <div className="app-shell-feedback">
        <div className="border-border card-gradient max-w-sm rounded-[var(--radius-lg)] border p-6 text-center">
          <p className="text-foreground type-heading text-base leading-snug font-semibold">
            Unable to load session
          </p>
          <p className="text-secondary mt-1.5 text-sm leading-[var(--leading-relaxed)]">
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
    <TopBarProvider>
      <div className="app-shell-root">
        <a
          href="#main-content"
          className="ui-on-accent-surface focus:bg-accent sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-md focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to main content
        </a>
        <div className="app-shell-grid">
          <Sidebar pathname={pathname} />
          <ShellContent pathname={pathname} canResetWorkspace={authQuery.data?.role === 'admin'}>
            {children}
          </ShellContent>
        </div>
      </div>
    </TopBarProvider>
  );
}

function AuthShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="auth-shell">
      <div className="auth-shell-card">
        <div className="auth-shell-header">
          <div className="auth-shell-brand">
            <LogoMark auth />
          </div>
          <ThemeToggle compact />
        </div>
        {children}
      </div>
    </div>
  );
}

function LogoMark({
  collapsed = false,
  auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
  const mark = (
    <Image
      src="/invoro-logo.svg"
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
        <span className="app-logo-title">Invoro</span>
      </div>
    </div>
  );
}

function Sidebar({ pathname }: Readonly<{ pathname: string }>) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    const stored = window.localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
    if (stored === 'true' || stored === 'false') return stored === 'true';
    return window.matchMedia('(max-width: 1279px)').matches;
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, String(collapsed));
  }, [collapsed]);

  const monitorLastVisit =
    typeof window === 'undefined'
      ? ''
      : (window.localStorage.getItem(STORAGE_KEYS.MONITORS_LAST_VISIT) ?? '');
  const monitorsQuery = useQuery({
    queryKey: ['sidebar-monitors'],
    queryFn: () => monitorsApi.list({ status: 'active' }),
    staleTime: 60_000,
  });
  const monitorPulse = Boolean(
    monitorsQuery.data?.some((monitor) => {
      if (!monitor.change_count) return false;
      if (!monitorLastVisit) return true;
      return new Date(monitor.updated_at).getTime() > new Date(monitorLastVisit).getTime();
    }),
  );

  return (
    <aside className={cn('app-sidebar', collapsed && 'is-collapsed')}>
      <div className="app-sidebar-header">
        <LogoMark collapsed={collapsed} />
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="app-icon-button"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
        </button>
      </div>

      <nav className="app-sidebar-nav" aria-label="Main navigation">
        {navGroups.map((group) => (
          <div key={group.label} className="app-sidebar-group">
            {!collapsed && <p className="app-sidebar-group-label">{group.label}</p>}
            <div className="space-y-1">
              {group.items.map((item) => {
                const active = isNavItemActive(pathname, item);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href as Route}
                    title={collapsed ? item.label : undefined}
                    className={cn(
                      'app-nav-item relative',
                      active && 'is-active',
                      collapsed && 'is-collapsed',
                    )}
                  >
                    <Icon className="app-nav-icon" />
                    {item.href === '/monitors' && monitorPulse ? (
                      <span
                        className="bg-accent absolute right-2 size-1.5 rounded-full"
                        aria-hidden
                      />
                    ) : null}
                    {!collapsed && <span className="truncate">{item.label}</span>}
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
  const router = useRouter();
  const queryClient = useQueryClient();
  const [resetPending, setResetPending] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetError, setResetError] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const resetTriggerRef = useRef<HTMLButtonElement | null>(null);
  const resetDialogRef = useRef<HTMLDivElement | null>(null);
  const resetConfirmRef = useRef<HTMLButtonElement | null>(null);
  const resetPreviousFocusRef = useRef<HTMLElement | null>(null);
  const resetPendingRef = useRef(resetPending);
  const notificationCountQuery = useQuery({
    queryKey: ['notifications-unread-count'],
    queryFn: api.notificationUnreadCount,
    staleTime: 30_000,
  });
  const notificationsQuery = useQuery({
    queryKey: ['notifications-unread'],
    queryFn: () => api.listNotifications({ limit: 10 }),
    enabled: notificationsOpen,
  });
  const markReadMutation = useMutation({
    mutationFn: api.markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread'] });
    },
  });

  useEffect(() => {
    resetPendingRef.current = resetPending;
  }, [resetPending]);

  useEffect(() => {
    if (!resetDialogOpen) {
      return;
    }
    const resetTrigger = resetTriggerRef.current;
    const previousOverflow = document.body.style.overflow;
    const previousTouchAction = document.body.style.touchAction;
    document.body.style.overflow = 'hidden';
    document.body.style.touchAction = 'none';
    const frame = window.requestAnimationFrame(() => resetConfirmRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (resetPendingRef.current) {
          return;
        }
        event.preventDefault();
        setResetDialogOpen(false);
        return;
      }
      trapFocus(event, resetDialogRef.current);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      document.body.style.touchAction = previousTouchAction;
      const restoreTarget = resetPreviousFocusRef.current?.isConnected
        ? resetPreviousFocusRef.current
        : resetTrigger;
      restoreTarget?.focus();
      resetPreviousFocusRef.current = null;
    };
  }, [resetDialogOpen]);

  async function executeReset() {
    if (!canResetWorkspace) return;
    setResetPending(true);
    setResetError('');
    try {
      await api.resetApplicationData();
      globalThis.location.reload();
    } catch (error) {
      const status = httpErrorStatus(error);
      if (status === 401) {
        router.replace('/login');
        return;
      }
      if (status === 403) {
        setResetError(resetForbiddenMessage);
        return;
      }
      setResetError(error instanceof Error ? error.message : 'Failed to reset workspace data.');
    } finally {
      setResetPending(false);
    }
  }

  function handleSelectedReset() {
    if (!canResetWorkspace) return;
    setResetError('');
    resetPreviousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : resetTriggerRef.current;
    setResetDialogOpen(true);
  }

  const resetLabel = resetPending ? 'Resetting Workspace...' : 'Reset Workspace';

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
          <div className="relative">
            <button
              type="button"
              className="app-icon-button relative"
              aria-label="Notifications"
              onClick={() => setNotificationsOpen((value) => !value)}
            >
              <Bell className="size-3.5" />
              {(notificationCountQuery.data?.count ?? 0) > 0 ? (
                <span className="bg-danger absolute -top-1 -right-1 min-w-4 rounded-full px-1 text-center text-xs leading-4 font-semibold text-white">
                  {notificationCountQuery.data?.count}
                </span>
              ) : null}
            </button>
            {notificationsOpen ? (
              <div className="border-border bg-background-elevated absolute top-9 right-0 z-[250] w-[min(340px,calc(100vw-32px))] rounded-[var(--radius-lg)] border p-2 shadow-lg">
                <div className="border-divider flex items-center justify-between border-b px-2 py-1.5">
                  <p className="type-label m-0">Notifications</p>
                  <span className="type-caption">
                    {notificationCountQuery.data?.count ?? 0} unread
                  </span>
                </div>
                <div className="max-h-80 overflow-y-auto py-1">
                  {notificationsQuery.isPending ? (
                    <div className="space-y-2 p-2">
                      <div className="skeleton h-12 w-full" />
                      <div className="skeleton h-12 w-full" />
                    </div>
                  ) : notificationsQuery.data?.length ? (
                    notificationsQuery.data.map((item) => (
                      <div
                        key={item.id}
                        className="hover:bg-background-alt flex items-start gap-2 rounded-[var(--radius-md)] p-2"
                      >
                        <Link
                          href={`/monitors/${item.monitor_id}` as Route}
                          className="min-w-0 flex-1"
                          onClick={() => setNotificationsOpen(false)}
                        >
                          <p className="text-foreground m-0 truncate text-sm font-medium">
                            {item.message}
                          </p>
                          <p className="type-caption m-0">{formatRelativeTime(item.created_at)}</p>
                        </Link>
                        <button
                          type="button"
                          className="app-icon-button"
                          aria-label="Mark notification read"
                          onClick={() => markReadMutation.mutate(item.id)}
                        >
                          <Check className="size-3.5" />
                        </button>
                      </div>
                    ))
                  ) : (
                    <p className="text-muted m-0 px-2 py-4 text-center text-sm">
                      No unread notifications.
                    </p>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main id="main-content" className="app-page-frame">
        <div className="app-page-inner">{children}</div>
      </main>
      {canResetWorkspace && resetDialogOpen ? (
        <div className="overlay-scrim fixed inset-0 z-[100] grid place-items-center p-4">
          <div
            ref={resetDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-workspace-title"
            aria-describedby="reset-workspace-description"
            tabIndex={-1}
            className="border-border card-gradient w-[min(420px,100%)] rounded-[var(--radius-lg)] border p-5"
          >
            <h2
              id="reset-workspace-title"
              className="text-foreground m-0 text-base leading-snug font-semibold"
            >
              {resetDialogCopy.title}
            </h2>
            <p
              id="reset-workspace-description"
              className="text-secondary mt-2 text-sm leading-[var(--leading-relaxed)]"
            >
              {resetDialogCopy.description}
            </p>
            {resetError ? (
              <div
                role="alert"
                className="border-danger/20 bg-danger/10 text-danger mt-4 rounded-[var(--radius-md)] border px-3 py-2 text-sm leading-[var(--leading-normal)]"
              >
                {resetError}
              </div>
            ) : null}
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="quiet"
                disabled={resetPending}
                onClick={() => setResetDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button
                ref={resetConfirmRef}
                type="button"
                variant="destructive"
                disabled={resetPending}
                onClick={() => void executeReset()}
              >
                {resetPending ? 'Working...' : resetDialogCopy.confirmLabel}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function getFallbackHeader(pathname: string): TopBarState {
  if (pathname.startsWith('/dashboard'))
    return {
      title: 'Dashboard',
      description: 'Overview of crawler activity across your workspace.',
    };
  if (pathname.startsWith('/crawl'))
    return {
      title: 'Crawl Studio',
      description: 'Configure sources, run jobs, and monitor execution.',
    };
  if (pathname.startsWith('/playground'))
    return {
      title: 'Playground',
      description:
        'Explore any domain — discover, extract, enrich, compare, and monitor from one place.',
    };
  if (pathname.startsWith('/data-enrichment'))
    return {
      title: 'Data Enrichment',
      description: 'Normalize ecommerce detail records into discovery fields.',
    };
  if (pathname.startsWith('/monitors'))
    return {
      title: 'Monitors',
      description: 'Schedule recurring crawls and inspect changes.',
    };
  if (pathname.startsWith('/alerts'))
    return {
      title: 'Product Alerts',
      description: 'Track single-product price and availability deltas.',
    };
  if (pathname.startsWith('/product-intelligence'))
    return {
      title: 'Product Intelligence',
      description: 'Find matching product pages and compare prices.',
    };
  if (pathname.startsWith('/ucp-audit'))
    return {
      title: 'AI Discoverability Score',
      description: 'Audit catalog signals for AI-readable commerce discovery.',
    };
  if (pathname.startsWith('/run-trace'))
    return {
      title: 'Run Trace',
      description: 'Inspect acquire timeline, extraction tiers, and auto-flagged bugs for a run.',
    };
  if (pathname.startsWith('/runs/'))
    return {
      title: 'Run Details',
      description: 'Inspect a crawl run, logs, and extracted output.',
    };
  if (pathname.startsWith('/runs'))
    return { title: 'Run History', description: 'Review and manage previously submitted crawls.' };
  if (pathname.startsWith('/selectors/manage'))
    return {
      title: 'Domain Memory',
      description: 'Inspect learned selectors and saved run profiles by domain and surface.',
    };
  if (pathname.startsWith('/selectors'))
    return { title: 'Selector Tool', description: 'Suggest, test, and validate field selectors.' };
  if (pathname.startsWith('/admin/users'))
    return { title: 'Users', description: 'Manage workspace access and roles.' };
  if (pathname.startsWith('/admin/llm'))
    return { title: 'LLM Config', description: 'Control provider settings and prompts.' };
  if (pathname.startsWith('/jobs'))
    return { title: 'Jobs', description: 'Review worker activity and queued work.' };
  return { title: 'Invoro' };
}
