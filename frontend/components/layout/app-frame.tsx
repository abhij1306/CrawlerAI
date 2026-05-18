'use client';

import React, { ReactNode } from 'react';
import { cn } from '../../lib/utils';

interface AppFrameProps extends React.HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hasHeader?: boolean;
  hasSidebar?: boolean;
  hasFooter?: boolean;
  hasModals?: boolean;
}

interface AppFrameSubComponentProps extends React.HTMLAttributes<HTMLElement> {
  children: ReactNode;
}

export function AppFrame({
  children,
  hasHeader = true,
  hasSidebar = true,
  hasFooter = true,
  hasModals = true,
  className,
  ...props
}: AppFrameProps) {
  // We can count/filter children or just render them directly.
  // Using custom CSS grid template areas based on options.
  return (
    <div
      className={cn(
        'hds-app-frame',
        !hasHeader && 'hds-app-frame--no-header',
        !hasSidebar && 'hds-app-frame--no-sidebar',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

// ── AppFrame Contextual Header Component ──
function AppFrameHeader({ children, className, ...props }: AppFrameSubComponentProps) {
  return (
    <header className={cn('hds-app-frame__header', className)} {...props}>
      {children}
    </header>
  );
}

// ── AppFrame Contextual Sidebar Component ──
function AppFrameSidebar({ children, className, ...props }: AppFrameSubComponentProps) {
  return (
    <aside className={cn('hds-app-frame__sidebar', className)} {...props}>
      {children}
    </aside>
  );
}

// ── AppFrame Contextual Main Component ──
interface AppFrameMainProps extends React.HTMLAttributes<HTMLElement> {
  children: ReactNode;
  id?: string;
}

function AppFrameMain({ children, className, id = 'hds-main', ...props }: AppFrameMainProps) {
  return (
    <main id={id} className={cn('hds-app-frame__main', className)} {...props}>
      {children}
    </main>
  );
}

// ── AppFrame Contextual Footer Component ──
function AppFrameFooter({ children, className, ...props }: AppFrameSubComponentProps) {
  return (
    <footer className={cn('hds-app-frame__footer', className)} {...props}>
      {children}
    </footer>
  );
}

// ── AppFrame Contextual Modals Component ──
interface AppFrameModalsProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: ReactNode;
}

function AppFrameModals({ children, className, ...props }: AppFrameModalsProps) {
  return (
    <div className={cn('hds-app-frame__modals', className)} {...props}>
      {children}
    </div>
  );
}

// Attach subcomponents to AppFrame
AppFrame.Header = AppFrameHeader;
AppFrame.Sidebar = AppFrameSidebar;
AppFrame.Main = AppFrameMain;
AppFrame.Footer = AppFrameFooter;
AppFrame.Modals = AppFrameModals;
