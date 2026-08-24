import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

import { Button } from '../button';
import { InlineAlert } from '../alert';

/**
 * A labelled, copyable command or snippet.
 *
 * `overflow-x-auto` plus `whitespace-pre-wrap` keeps long commands inside their
 * container instead of widening the page, so this is safe on narrow viewports.
 */
export function CodeBlock({
  label,
  value,
  className,
}: Readonly<{ label: string; value: string; className?: string }>) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopyError('');
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopyError('Clipboard unavailable. Select and copy the value manually.');
    }
  }

  return (
    <div className={className ? `space-y-2 ${className}` : 'space-y-2'}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold tracking-wide text-muted uppercase">{label}</span>
        <Button type="button" variant="quiet" size="sm" onClick={() => void copy()}>
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-md border border-border bg-background px-3 py-2 font-mono text-base leading-relaxed whitespace-pre-wrap text-secondary">
        {value}
      </pre>
      {copyError ? <InlineAlert tone="warning" message={copyError} /> : null}
    </div>
  );
}
