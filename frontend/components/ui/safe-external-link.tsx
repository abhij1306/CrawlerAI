import type { ReactNode } from 'react';

import { isSafeHttpUrl } from '../../lib/format/domain';
import { cn } from '../../lib/utils';

type SafeExternalLinkProps = Readonly<{
  href: string;
  className?: string;
  title?: string;
  ariaLabel?: string;
  children: ReactNode;
}>;

/**
 * External link for crawled/search-derived URLs. Renders an anchor only for
 * http(s) URLs — anything else (javascript:, data:, vbscript:, ...) degrades
 * to muted plain text so attacker-controlled schemes never become clickable.
 */
export function SafeExternalLink({
  href,
  className,
  title,
  ariaLabel,
  children,
}: SafeExternalLinkProps) {
  if (!isSafeHttpUrl(href)) {
    return (
      <span className={cn(className, 'text-muted')} title={title} aria-label={ariaLabel}>
        {children}
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
      title={title}
      aria-label={ariaLabel}
    >
      {children}
    </a>
  );
}
