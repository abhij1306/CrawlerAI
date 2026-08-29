import { DatabaseZap, FileChartColumn, KeyRound, WandSparkles } from 'lucide-react';
import { Outlet } from 'react-router-dom';
import type { ReactNode } from 'react';

import { ThemeToggle } from '../ui/theme-toggle';
import { LogoMark } from './logo-mark';

/**
 * Capabilities named after what the app actually ships, using the same icons
 * the nav uses for those routes — so the panel cannot drift into marketing
 * that the product does not back up.
 */
const authHighlights = [
  {
    icon: WandSparkles,
    title: 'Crawl Studio',
    body: 'Configure, launch, and watch runs live with per-site Run Events.',
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
