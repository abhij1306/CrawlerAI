'use client';

import { Copy } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import katex from 'katex';
import type { KatexOptions } from 'katex';

import { DataRegionEmpty, DataRegionLoading } from '../ui/patterns';
import { Button } from '../ui/primitives';

type KaTeXApi = {
  render: (math: string, element: HTMLElement, options: KatexOptions) => void;
};

type WindowWithKaTeX = Window & { katex?: KaTeXApi };

function loadKaTeX(): Promise<KaTeXApi> {
  if (typeof window === 'undefined') return Promise.reject(new Error('Window is undefined'));
  const browserWindow = window as WindowWithKaTeX;
  if (browserWindow.katex) return Promise.resolve(browserWindow.katex);
  browserWindow.katex = katex;
  return Promise.resolve(katex);
}

export function MathRenderer({
  math,
  displayMode,
}: Readonly<{ math: string; displayMode?: boolean }>) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const katexRef = useRef<KaTeXApi | null>(null);

  useEffect(() => {
    let active = true;
    function renderMath(kt: KaTeXApi | null) {
      if (!containerRef.current) {
        return;
      }
      if (!kt) {
        containerRef.current.textContent = displayMode ? `$$\n${math}\n$$` : `$${math}$`;
        return;
      }
      try {
        kt.render(math, containerRef.current, {
          displayMode: !!displayMode,
          throwOnError: false,
          strict: 'ignore',
        });
      } catch {
        containerRef.current.textContent = math;
      }
    }

    renderMath(katexRef.current);
    loadKaTeX()
      .then((kt) => {
        if (active) {
          katexRef.current = kt;
          renderMath(kt);
        }
      })
      .catch((err) => console.error(err));
    return () => {
      active = false;
    };
  }, [math, displayMode]);

  return (
    <span
      ref={containerRef}
      className={displayMode ? 'block w-full overflow-x-auto py-1 text-center' : 'inline'}
    />
  );
}

function parseInlineMarkdownNodes(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern =
    /(\$\$[\s\S]+?\$\$|\$[^$\n]+\$|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\((?:https?:\/\/|\/|#)[^)]+\))/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      nodes.push(text.slice(cursor, index));
    }
    const token = match[0];
    const key = `${index}-${token}`;

    if (token.startsWith('$$') && token.endsWith('$$')) {
      const math = token.slice(2, -2);
      nodes.push(<MathRenderer key={key} math={math} displayMode={true} />);
    } else if (token.startsWith('$') && token.endsWith('$')) {
      const math = token.slice(1, -1);
      nodes.push(<MathRenderer key={key} math={math} displayMode={false} />);
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(
        <code
          key={key}
          className="bg-background-alt rounded-sm px-1 py-0.5 font-mono text-[0.92em]"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('*') && token.endsWith('*')) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith('_') && token.endsWith('_')) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a
            key={key}
            href={linkMatch[2]}
            target={linkMatch[2].startsWith('#') ? undefined : '_blank'}
            rel={linkMatch[2].startsWith('#') ? undefined : 'noreferrer'}
            className="link-accent underline-offset-2 hover:underline"
          >
            {linkMatch[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    cursor = index + token.length;
  }
  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes;
}

function InlineMarkdown({ text }: Readonly<{ text: string }>) {
  return <>{parseInlineMarkdownNodes(text)}</>;
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isTableDivider(line: string): boolean {
  const cells = parseTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function MarkdownPreview({ markdown }: Readonly<{ markdown: string }>) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let index = 0;
  let blockSeq = 0;
  const nextKey = (prefix: string) => `${prefix}-${(blockSeq += 1)}`;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (
      index === 0 &&
      trimmed === '---' &&
      lines.findIndex((candidate, candidateIndex) => {
        return candidateIndex > index && candidate.trim() === '---';
      }) !== -1
    ) {
      const frontmatter: string[] = [];
      index += 1;
      while (index < lines.length && lines[index].trim() !== '---') {
        frontmatter.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <section
          key="frontmatter"
          className="border-border bg-background-alt/60 my-3 overflow-hidden rounded-md border"
        >
          <div className="border-border bg-panel flex items-center justify-between border-b px-4 py-2">
            <div className="type-label text-secondary">Design Tokens</div>
            <div className="text-secondary text-2xs font-mono">YAML</div>
          </div>
          <pre className="px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap">
            <code className="font-mono">{frontmatter.join('\n')}</code>
          </pre>
        </section>,
      );
      continue;
    }

    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim();
      const code: string[] = [];
      const maxCodeLines = 500;
      index += 1;
      while (
        index < lines.length &&
        !lines[index].trim().startsWith('```') &&
        code.length < maxCodeLines
      ) {
        code.push(lines[index]);
        index += 1;
      }
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        index += 1;
      }
      if (index < lines.length && lines[index].trim().startsWith('```')) {
        index += 1;
      }
      blocks.push(
        <div key={nextKey('code')} className="my-4 overflow-hidden rounded-md border">
          {lang && (
            <div className="bg-background-alt text-secondary border-b px-4 py-1.5 font-mono text-[0.75em]">
              {lang}
            </div>
          )}
          <pre className="bg-background-alt overflow-x-auto px-4 py-3 text-sm leading-relaxed whitespace-pre">
            <code className="font-mono">{code.join('\n')}</code>
          </pre>
        </div>,
      );
      continue;
    }

    if (trimmed.startsWith('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = parseTableRow(trimmed);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        rows.push(parseTableRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div
          key={nextKey('table')}
          className="border-border my-4 overflow-x-auto rounded-md border"
        >
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead className="bg-background-alt text-secondary">
              <tr>
                {headers.map((header) => (
                  <th
                    key={header}
                    className="border-border text-2xs border-b px-3 py-2 text-left font-mono font-semibold tracking-wide uppercase"
                  >
                    <InlineMarkdown text={header} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.join('|')} className="odd:bg-background even:bg-background-alt/40">
                  {headers.map((header, cellIndex) => (
                    <td
                      key={header}
                      className="border-border/70 text-foreground border-b px-3 py-2 align-top"
                    >
                      <InlineMarkdown text={row[cellIndex] || ''} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (trimmed.startsWith('$$')) {
      const mathLines: string[] = [];
      if (trimmed.endsWith('$$') && trimmed.length > 2) {
        const math = trimmed.slice(2, -2);
        blocks.push(
          <div key={nextKey('math')} className="my-4">
            <MathRenderer math={math} displayMode={true} />
          </div>,
        );
        index += 1;
        continue;
      }

      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('$$')) {
        mathLines.push(lines[index]);
        index += 1;
      }
      index += 1; // skip closing $$
      blocks.push(
        <div key={nextKey('math')} className="my-4">
          <MathRenderer math={mathLines.join('\n')} displayMode={true} />
        </div>,
      );
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const className =
        level === 1
          ? 'type-title text-foreground mt-1 mb-3'
          : level === 2
            ? 'type-section text-foreground mt-6 mb-2'
            : 'type-body text-foreground mt-4 mb-2 font-semibold';
      const HeadingTag = `h${Math.min(level, 6)}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
      blocks.push(
        <HeadingTag key={nextKey('heading')} className={className}>
          <InlineMarkdown text={heading[2]} />
        </HeadingTag>,
      );
      index += 1;
      continue;
    }

    if (/^[-*_]{3,}$/.test(trimmed)) {
      blocks.push(<hr key={nextKey('hr')} className="border-divider my-6" />);
      index += 1;
      continue;
    }

    if (trimmed.startsWith('>')) {
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('>')) {
        quote.push(lines[index].trim().replace(/^>\s?/, ''));
        index += 1;
      }
      blocks.push(
        <blockquote
          key={nextKey('quote')}
          className="border-accent/40 text-secondary border-l-2 pl-4 leading-relaxed"
        >
          {quote.map((item, itemIndex) => (
            <p key={`${item}-${itemIndex}`} className="type-body my-1">
              <InlineMarkdown text={item} />
            </p>
          ))}
        </blockquote>,
      );
      continue;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      const items: string[] = [];
      const orderedList = Boolean(ordered);
      while (index < lines.length) {
        const item = lines[index].trim().match(orderedList ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const ListTag: 'ol' | 'ul' = orderedList ? 'ol' : 'ul';
      blocks.push(
        <ListTag
          key={nextKey('list')}
          className="type-body text-foreground my-3 space-y-1 pl-6 leading-relaxed"
        >
          {items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`} className={orderedList ? 'list-decimal' : 'list-disc'}>
              <InlineMarkdown text={item} />
            </li>
          ))}
        </ListTag>,
      );
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const current = lines[index].trim();
      if (
        !current ||
        current.startsWith('```') ||
        current.startsWith('$$') ||
        current.startsWith('>') ||
        /^(#{1,6})\s+/.test(current) ||
        /^[-*_]{3,}$/.test(current) ||
        (current.startsWith('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) ||
        /^[-*]\s+/.test(current) ||
        /^\d+\.\s+/.test(current)
      ) {
        break;
      }
      paragraph.push(current);
      index += 1;
    }
    blocks.push(
      <p key={nextKey('p')} className="type-body text-foreground my-3 leading-[1.72]">
        <InlineMarkdown text={paragraph.join(' ')} />
      </p>,
    );
  }

  return <div className="px-3 py-5">{blocks}</div>;
}

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

export function MarkdownOutput({ markdown }: Readonly<{ markdown: string }>) {
  const [view, setView] = useState<'preview' | 'source'>('preview');
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<number | undefined>(undefined);
  const lineCount = markdown ? markdown.replace(/\r\n/g, '\n').split('\n').length : 0;

  useEffect(() => {
    const copyTimeout = copyTimeoutRef;
    return () => {
      if (copyTimeout.current) window.clearTimeout(copyTimeout.current);
    };
  }, []);

  function copyMarkdown() {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(markdown).catch(() => {
        fallbackCopy(markdown);
      });
    } else {
      fallbackCopy(markdown);
    }
    setCopied(true);
    if (copyTimeoutRef.current) window.clearTimeout(copyTimeoutRef.current);
    copyTimeoutRef.current = window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="min-h-[55vh]">
      <div className="border-border bg-panel sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-t-[var(--radius-md)] border border-b-0 px-3 py-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-pressed={view === 'preview'}
            onClick={() => setView('preview')}
            className={`rounded-sm px-3 py-1.5 text-sm font-medium transition-colors ${
              view === 'preview'
                ? 'bg-accent text-accent-fg'
                : 'text-secondary hover:bg-background-alt hover:text-foreground'
            }`}
          >
            Preview
          </button>
          <button
            type="button"
            aria-pressed={view === 'source'}
            onClick={() => setView('source')}
            className={`rounded-sm px-3 py-1.5 text-sm font-medium transition-colors ${
              view === 'source'
                ? 'bg-accent text-accent-fg'
                : 'text-secondary hover:bg-background-alt hover:text-foreground'
            }`}
          >
            Source
          </button>
          <span className="text-secondary text-2xs font-mono">{lineCount} lines</span>
        </div>
        <Button variant="quiet" type="button" onClick={copyMarkdown}>
          <Copy className="size-3.5" />
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <article className="surface-muted bg-background max-h-[62vh] min-h-[55vh] overflow-y-auto rounded-b-[var(--radius-md)] border">
        {view === 'preview' ? (
          <MarkdownPreview markdown={markdown} />
        ) : (
          <pre className="min-h-[55vh] overflow-auto p-4 text-xs leading-relaxed whitespace-pre-wrap">
            <code className="font-mono">{markdown}</code>
          </pre>
        )}
      </article>
    </div>
  );
}

export function MarkdownOutputPanel({
  isLoading,
  markdown,
  emptyTitle,
  emptyDescription,
}: Readonly<{
  isLoading: boolean;
  markdown: string;
  emptyTitle: string;
  emptyDescription: string;
}>) {
  if (isLoading) {
    return (
      <div className="min-h-[55vh]">
        <DataRegionLoading count={5} className="px-0" />
      </div>
    );
  }
  if (!markdown) {
    return (
      <div className="min-h-[55vh]">
        <DataRegionEmpty title={emptyTitle} description={emptyDescription} className="px-0" />
      </div>
    );
  }
  return <MarkdownOutput markdown={markdown} />;
}
