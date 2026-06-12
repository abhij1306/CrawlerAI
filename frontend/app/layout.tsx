import type { Metadata } from 'next';
import { headers } from 'next/headers';
import Script from 'next/script';
import './globals.css';

// Next.js App Router root layout; invoked by file-system routing.
import { Geist, Geist_Mono } from 'next/font/google';

import { AppShell } from '../components/layout/app-shell';
import { QueryProvider } from '../components/ui/query-provider';

const primaryFont = Geist({
  subsets: ['latin'],
  variable: '--font-primary-source',
  display: 'swap',
});

const displayFont = Geist({
  subsets: ['latin'],
  variable: '--font-display-source',
  display: 'swap',
});

const monoFont = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-mono-source',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Invoro',
  description: 'AI commerce intelligence and structured extraction platform.',
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const nonce = (await headers()).get('x-nonce') ?? undefined;

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <Script src="/theme-init.js" strategy="beforeInteractive" nonce={nonce} />
      </head>
      {/*
        Only apply font variables here, NOT primaryFont.className.
        primaryFont.className hardcodes a font-family class directly on body,
        bypassing the CSS variable cascade in globals.css entirely.
        The variables are picked up by --font-primary-family, --font-display-family,
        and --font-mono-family.
      */}
      <body className={`${primaryFont.variable} ${displayFont.variable} ${monoFont.variable}`}>
        <div className="noise-overlay" aria-hidden="true" />
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
