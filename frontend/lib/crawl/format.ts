import { formatTimeHms, parseApiDate } from '../format/date';
import type { CrawlRun } from '../api/types';

export { formatTimeHms, parseApiDate };

export function parseLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function clampNumber(value: string | number, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function normalizeField(value: string) {
  return value
    .trim()
    .replace(/&/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function stringifyCell(value: unknown) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

export function decodeUrlForDisplay(value: string) {
  const text = String(value || '').trim();
  if (!/^https?:\/\//i.test(text)) return text;
  try {
    return decodeURI(text);
  } catch {
    return text;
  }
}

function parseJsonTextForDisplay(value: string): unknown {
  const text = value.trim();
  if (!text || !/^[\[{]/.test(text)) return value;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' ? parsed : value;
  } catch {
    return value;
  }
}

export function formatCellDisplay(value: unknown) {
  return decodeUrlForDisplay(stringifyCell(value));
}

export function decodeUrlsForDisplay<T>(value: T): T {
  if (typeof value === 'string') {
    const parsed = parseJsonTextForDisplay(value);
    if (parsed !== value) return decodeUrlsForDisplay(parsed) as T;
    return decodeUrlForDisplay(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => decodeUrlsForDisplay(entry)) as T;
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, decodeUrlsForDisplay(entry)]),
    ) as T;
  }
  return value;
}

export function humanizeFieldName(value: string) {
  const normalized = String(value || '')
    .replace(/[_-]+/g, '')
    .replace(/\s+/g, '')
    .trim();
  if (!normalized) return '';
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function presentCandidateValue(value: unknown) {
  const trimmed = stringifyCell(value).trim();
  if (!trimmed) return '';
  const schemaMatch = trimmed.match(/^https?:\/\/schema\.org\/([A-Za-z]+)$/i);
  if (!schemaMatch) return trimmed;
  const token = schemaMatch[1].replace(/([a-z])([A-Z])/g, '$1 $2');
  return token.charAt(0).toUpperCase() + token.slice(1);
}

export function isEmptyCandidateValue(value: unknown) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value).length === 0;
  return false;
}

export function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return '--';
  const started = parseApiDate(start).getTime();
  const finished = end ? parseApiDate(end).getTime() : Date.now();

  if (!Number.isFinite(started) || !Number.isFinite(finished)) return '--';
  const ms = Math.max(0, finished - started);
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function formatDurationMs(durationMs?: number | null) {
  if (typeof durationMs !== 'number' || !Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }
  const totalSeconds = Math.floor(durationMs / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function progressPercent(run: CrawlRun | undefined) {
  const value = typeof run?.result_summary?.progress === 'number' ? run.result_summary.progress : 0;
  return Math.min(100, Math.max(0, value));
}

export function extractionVerdict(run: CrawlRun | undefined) {
  const verdict = String(run?.result_summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  return verdict || 'unknown';
}

export function extractionVerdictTone(verdict: string) {
  if (verdict === 'success') return 'success';
  if (verdict === 'partial') return 'warning';
  if (verdict === 'schema_miss' || verdict === 'listing_detection_failed' || verdict === 'empty')
    return 'warning';
  if (verdict === 'blocked' || verdict === 'proxy_exhausted' || verdict === 'error')
    return 'danger';
  return 'neutral';
}

export function humanizeVerdict(verdict: string) {
  return verdict.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatShortUrlLabel(url: string) {
  try {
    const parsed = new URL(url);
    const domain = parsed.hostname.replace(/^www\./, '');
    const parts = parsed.pathname.split('/').filter(Boolean);
    const lastPart = parts.at(-1) || '';
    if (parts.length > 1) {
      return `${domain}/.../${lastPart}`;
    }
    return domain + (lastPart ? `/${lastPart}` : '');
  } catch {
    return url.length > 40 ? url.slice(0, 40) + '...' : url;
  }
}
