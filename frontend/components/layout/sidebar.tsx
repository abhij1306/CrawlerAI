import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { cn } from '../../lib/utils';
import { navGroups } from '../../src/app/route-registry';
import { Button } from '../ui/button';
import { ThemeToggle } from '../ui/theme-toggle';
import { Tooltip } from '../ui/tooltip';
import { LogoMark } from './logo-mark';

function isNavItemActive(pathname: string, item: (typeof navGroups)[number]['items'][number]) {
  if (item.nav?.exact) return pathname === item.path;
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}

export function Sidebar({ pathname, isAdmin }: Readonly<{ pathname: string; isAdmin: boolean }>) {
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
        collapsed ? 'w-[58px] p-2 items-center' : 'w-[232px]',
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
          aria-controls="app-sidebar-navigation"
          aria-expanded={!collapsed}
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
                <p className="px-2.5 text-[10px] font-semibold tracking-[0.08em] text-muted uppercase">
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
                        'flex h-7 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors w-full',
                        active
                          ? 'bg-panel-strong text-foreground font-medium'
                          : 'text-secondary hover:bg-background-alt hover:text-foreground',
                        collapsed && 'px-0 justify-center h-9 w-9',
                      )}
                    >
                      <Icon className="size-4 shrink-0" strokeWidth={1.75} />
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
