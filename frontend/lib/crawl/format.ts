import { formatTimeHms, parseApiDate } from '../format/date';
export { formatTimeHms, parseApiDate };
import type { CrawlRun } from '../api/types';

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

/**
 * Canonical optional-number input parser. Empty input always yields null;
 * `onInvalid` picks the non-numeric-input policy — crawl limits fall back to
 * `min` ('clamp-to-min'), domain-memory drafts reject to null ('null').
 */
export function parseOptionalClampedNumber(
  value: string,
  min: number,
  max: number,
  onInvalid: 'clamp-to-min' | 'null',
) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number.parseInt(trimmed, 10);
  if (Number.isNaN(parsed)) {
    return onInvalid === 'clamp-to-min' ? min : null;
  }
  return Math.min(max, Math.max(min, parsed));
}

// skipcq: JS-0067
export function normalizeField(value: string) {
  const normalized = value
    .trim()
    .replace(/&/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_');
  let start = 0;
  let end = normalized.length;
  while (start < end && normalized[start] === '_') start += 1;
  while (end > start && normalized[end - 1] === '_') end -= 1;
  return normalized.slice(start, end);
}

export function stringifyCell(value: unknown) {
  if (value == null) return '';
  if (typeof value === 'string') return decodeEscapedTextForDisplay(value);
  return JSON.stringify(value);
}

function decodeUrlForDisplay(value: string) {
  const text = decodeEscapedTextForDisplay(String(value || '')).trim();
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

function decodeEscapedTextForDisplay(value: string) {
  let text = String(value || '');
  if (!text.includes('\\')) return text;
  const backslashMarker = '\0BACKSLASH\0';
  text = text.replace(/\\\\/g, backslashMarker);
  text = text
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, code: string) =>
      String.fromCharCode(Number.parseInt(code, 16)),
    )
    .replace(/\\\//g, '/')
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t');
  text = text.replaceAll(backslashMarker, '\\');
  return text.replace(/\\"/g, '"').replace(/\\'/g, "'");
}

export function humanizeFieldName(value: string) {
  const normalized = String(value || '')
    .replace(/[_-]+/g, '')
    .replace(/\s+/g, '')
    .trim();
  if (!normalized) return '';
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
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

export function extractionVerdict(run: CrawlRun | undefined) {
  const verdict = String(run?.result_summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  return verdict || 'unknown';
}

export function humanizeVerdict(verdict: string) {
  return verdict.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}
