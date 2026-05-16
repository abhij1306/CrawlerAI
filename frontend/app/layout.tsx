import type { Metadata } from 'next';
import './globals.css';

import { Outfit } from 'next/font/google';
import localFont from 'next/font/local';

import { AppShell } from '../components/layout/app-shell';
import { QueryProvider } from '../components/ui/query-provider';

// Primary UI font
const mainFont = Outfit({
  subsets: ['latin'],
  variable: '--font-primary-source',
  display: 'swap',
});

// Mono font. Keep variable name stable so globals.css does not need selector churn.
const monoFont = localFont({
  src: [
    { path: './fonts/adwaita-mono-regular.ttf', weight: '400', style: 'normal' },
    { path: './fonts/adwaita-mono-italic.ttf', weight: '400', style: 'italic' },
    { path: './fonts/adwaita-mono-bold.ttf', weight: '700', style: 'normal' },
    { path: './fonts/adwaita-mono-bold-italic.ttf', weight: '700', style: 'italic' },
  ],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'CrawlerAI',
  description: 'Web crawling and structured data extraction platform.',
};

// Runs before first paint — sets data-theme to prevent FOUC
const themeScript = `(()=>{let d=false;try{const s=localStorage.getItem("crawlerai-theme");d=s==="dark"||(!s&&matchMedia("(prefers-color-scheme:dark)").matches);}catch(e){try{d=matchMedia("(prefers-color-scheme:dark)").matches;}catch(_){d=false;}}document.documentElement.dataset.theme=d?"dark":"light";})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Inline theme script — must be synchronous to block FOUC */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      {/*
        Only apply font variables here, NOT mainFont.className.
        mainFont.className hardcodes a font-family class directly on body,
        bypassing the CSS variable cascade in globals.css entirely.
        The variables are picked up by --font-primary-family and --font-mono-family.
      */}
      <body className={`${mainFont.variable} ${monoFont.variable}`}>
        <div className="noise-overlay" aria-hidden="true" />
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
