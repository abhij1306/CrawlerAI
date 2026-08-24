import type { ReactNode } from 'react';

import type { FieldRow, FieldRowMessageTone } from './form-fields';
import { buildLogSiteGroups, getLogStage } from './log-terminal-utils';
import type { CrawlDomain, CrawlLog, CrawlRun, CrawlSurface } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { SURFACE_DISPATCH } from './domain-surface-config';
import {
  uniqueFields,
  uniqueRequestedFields,
  uniqueStrings,
  validateAdditionalFieldName,
} from '../../lib/crawl/fields';
import {
  clampNumber,
  decodeUrlsForDisplay,
  extractionVerdict,
  formatCellDisplay,
  formatDuration,
  formatDurationMs,
  humanizeVerdict,
  normalizeField,
  parseLines,
} from '../../lib/crawl/format';
import { scrollViewportToBottom } from '../../lib/crawl/scroll';
import { cleanRecordForDisplay, extractRecordUrl } from '../../lib/crawl/record-utils';
import {
  estimateDataQuality,
  humanizeQuality,
  scoreFieldQuality,
  scoreRecordQuality,
} from '../../lib/crawl/quality';

export {
  clampNumber,
  cleanRecordForDisplay,
  decodeUrlsForDisplay,
  estimateDataQuality,
  extractionVerdict,
  extractRecordUrl,
  formatCellDisplay,
  formatDuration,
  formatDurationMs,
  humanizeQuality,
  humanizeVerdict,
  normalizeField,
  parseLines,
  scoreFieldQuality,
  scoreRecordQuality,
  uniqueFields,
  uniqueRequestedFields,
  uniqueStrings,
  validateAdditionalFieldName,
};
export { buildLogSiteGroups, getLogStage, scrollViewportToBottom };
export type { FieldRow, FieldRowMessageTone };

export type CrawlTab = 'category' | 'pdp';
export type CategoryMode = 'single' | 'sitemap' | 'bulk';
export type PdpMode = 'single' | 'batch' | 'csv';
export type PendingDispatch = {
  runType: 'crawl' | 'batch' | 'csv';
  surface: CrawlSurface;
  url?: string;
  urls?: string[];
  settings: Record<string, unknown>;
  additionalFields: string[];
  csvFile: File | null;
};
export type OutputTabKey = 'table' | 'json' | 'logs' | 'learning';

export function selectorWinnerLabel(selectorKind: string | null | undefined): string {
  const normalized = String(selectorKind || '')
    .trim()
    .toLowerCase();
  if (!normalized) return 'Selector winner';
  if (normalized === 'xpath') return 'XPath winner';
  if (normalized === 'css_selector') return 'CSS selector winner';
  return `${selectorKind} winner`;
}

export function mergeLogs(current: CrawlLog[], incoming: CrawlLog[]) {
  const byId = new Map<number, CrawlLog>();
  for (const row of current) byId.set(row.id, row);
  for (const row of incoming) byId.set(row.id, row);
  return Array.from(byId.values())
    .sort((a, b) => a.id - b.id)
    .slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS);
}

export function appendLiveLog(current: CrawlLog[], incoming: CrawlLog) {
  const existingIndex = current.findIndex((row) => row.id === incoming.id);
  if (existingIndex >= 0) {
    const next = [...current];
    next[existingIndex] = incoming;
    return next;
  }
  if (!current.length || current[current.length - 1].id < incoming.id) {
    return [...current, incoming].slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS);
  }
  const insertionIndex = current.findIndex((row) => row.id > incoming.id);
  const next = [...current];
  next.splice(insertionIndex === -1 ? next.length : insertionIndex, 0, incoming);
  return next.slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS);
}

export function parseRequestedCrawlTab(value: string | null): CrawlTab | null {
  return value === 'category' || value === 'pdp' ? value : null;
}

export function parseRequestedCategoryMode(value: string | null): CategoryMode | null {
  return value === 'single' || value === 'sitemap' || value === 'bulk' ? value : null;
}

export function parseRequestedPdpMode(value: string | null): PdpMode | null {
  return value === 'single' || value === 'batch' || value === 'csv' ? value : null;
}

export function deriveSurface(domain: CrawlDomain, module: CrawlTab): CrawlSurface {
  return SURFACE_DISPATCH[`${domain}:${module}`];
}

export function inferDomainFromSurface(surface: string | null | undefined): CrawlDomain | null {
  const normalizedSurface = String(surface || '').toLowerCase();
  if (normalizedSurface.startsWith('job_')) {
    return 'jobs';
  }
  if (normalizedSurface.startsWith('ecommerce_')) {
    return 'commerce';
  }
  return null;
}

/** The one approved tint chip in the refined-minimal sample (mockup .chip/.cdot). */
export function StudioChip({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span className="inline-flex h-5 items-center gap-1.5 rounded-full border border-accent-border bg-accent-soft px-2 text-sm font-medium text-accent-text">
      <span className="size-[5px] rounded-full bg-accent" aria-hidden="true" />
      {children}
    </span>
  );
}

function inferRunModule(run?: CrawlRun): CrawlTab | null {
  if (!run) {
    return null;
  }
  const settings = run.settings && typeof run.settings === 'object' ? run.settings : {};
  const configuredModule = typeof settings.crawl_module === 'string' ? settings.crawl_module : '';
  if (configuredModule === 'category' || configuredModule === 'pdp') {
    return configuredModule;
  }

  const configuredMode = typeof settings.crawl_mode === 'string' ? settings.crawl_mode : '';
  if (configuredMode === 'bulk' || configuredMode === 'sitemap') {
    return 'category';
  }
  if (configuredMode === 'batch' || configuredMode === 'csv') {
    return 'pdp';
  }

  const surface = String(run.surface || '').toLowerCase();
  if (surface.includes('listing')) {
    return 'category';
  }
  if (surface.includes('detail')) {
    return 'pdp';
  }

  return null;
}

export function isListingRun(run?: CrawlRun) {
  return inferRunModule(run) === 'category';
}
