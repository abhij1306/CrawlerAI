import type { CrawlRecord, CrawlRun } from '../../lib/api/types';
import { getDomain } from '../../lib/format/domain';

const MARKDOWN_OUTPUT_SURFACES = new Set([
  'auto',
  'content_detail',
  'article_detail',
  'forum_detail',
  'design_system',
]);

export function isMarkdownOutputRun(run: CrawlRun | undefined): boolean {
  if (!run) return false;
  const surface = String(run.surface || '').toLowerCase();
  const resolvedSurface =
    typeof run.result_summary?.resolved_surface === 'string'
      ? run.result_summary.resolved_surface.toLowerCase()
      : '';
  const requestedFields = Array.isArray(run.requested_fields) ? run.requested_fields : [];
  return (
    MARKDOWN_OUTPUT_SURFACES.has(surface) ||
    MARKDOWN_OUTPUT_SURFACES.has(resolvedSurface) ||
    requestedFields.some((field) => field.toLowerCase() === 'markdown')
  );
}

export function isDesignSystemRun(run: CrawlRun | undefined): boolean {
  return String(run?.surface || '').toLowerCase() === 'design_system';
}

function readRecordString(record: CrawlRecord, field: string): string {
  const dataValue = record.data?.[field];
  if (typeof dataValue === 'string' && dataValue.trim()) return dataValue.trim();
  const rawValue = record.raw_data?.[field];
  if (typeof rawValue === 'string' && rawValue.trim()) return rawValue.trim();
  return '';
}

function recordMarkdown(record: CrawlRecord): string {
  return readRecordString(record, 'markdown') || readRecordString(record, 'content');
}

export function buildMarkdownDocument(records: CrawlRecord[]): string {
  const documents = records.flatMap((record) => {
    const markdown = recordMarkdown(record);
    if (!markdown) return [];
    const title = readRecordString(record, 'title');
    const trimmed = markdown.trimStart();
    if (!title || trimmed.startsWith('#') || trimmed.startsWith('---')) return [markdown];
    return [`# ${title}\n\n${markdown}`];
  });
  return documents.join('\n\n---\n\n');
}

// skipcq: JS-0067
function markdownDownloadName(run: CrawlRun | undefined): string {
  if (isDesignSystemRun(run)) {
    return 'design.md';
  }
  const host = run?.url
    ? getDomain(run.url)
        .replace(/[^a-z0-9.-]+/gi, '-')
        .replace(/^-+/g, '')
        .replace(/-+$/g, '')
    : '';
  return `${host || `run-${run?.id ?? 'output'}`}.md`;
}

export function downloadMarkdown(markdown: string, run: CrawlRun | undefined) {
  if (!markdown) return;
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = markdownDownloadName(run);
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(href);
  }, 0);
}
