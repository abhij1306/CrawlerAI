'use client';

import type { ReactNode } from 'react';

import { Button } from '../ui/primitives';
import {
  AdditionalFieldInput,
  FieldEditorHeader,
  ManualFieldEditor,
  SettingSection,
  SliderRow,
} from './form-fields';
import type { FieldRow, FieldRowMessageTone, ValidationState } from './form-fields';
import { LogTerminal, buildLogSiteGroups, getLogStage } from './log-terminal';
import { RecordThumbnail } from './record-thumbnail';
import { RecordsTable } from './records-table';
import type { CrawlDomain, CrawlRun, CrawlSurface } from '../../lib/api/types';
import { SURFACE_DISPATCH } from './domain-surface-config';
import { cn } from '../../lib/utils';
import {
  cleanRequestedField,
  uniqueFields,
  uniqueNumbers,
  uniqueRequestedFields,
  uniqueStrings,
  validateAdditionalFieldName,
} from '../../lib/crawl/fields';
import {
  clampNumber,
  decodeUrlForDisplay,
  decodeUrlsForDisplay,
  extractionVerdict,
  extractionVerdictTone,
  formatCellDisplay,
  formatDuration,
  formatDurationMs,
  humanizeFieldName,
  humanizeVerdict,
  isEmptyCandidateValue,
  normalizeField,
  parseLines,
  presentCandidateValue,
  progressPercent,
  stringifyCell,
} from '../../lib/crawl/format';
import { scrollViewportToBottom } from '../../lib/crawl/scroll';
import {
  cleanRecord,
  cleanRecordForDisplay,
  copyJson,
  extractRecordUrl,
  readRecordValue,
} from '../../lib/crawl/record-utils';
import {
  estimateDataQuality,
  humanizeQuality,
  qualityLevelFromScore,
  qualityTone,
  scoreFieldQuality,
  scoreRecordQuality,
} from '../../lib/crawl/quality';
import type { QualityLevel, QualitySnapshot } from '../../lib/crawl/quality';

export {
  clampNumber,
  cleanRequestedField,
  cleanRecord,
  cleanRecordForDisplay,
  copyJson,
  decodeUrlForDisplay,
  decodeUrlsForDisplay,
  estimateDataQuality,
  extractionVerdict,
  extractionVerdictTone,
  extractRecordUrl,
  formatCellDisplay,
  formatDuration,
  formatDurationMs,
  humanizeFieldName,
  humanizeQuality,
  humanizeVerdict,
  isEmptyCandidateValue,
  normalizeField,
  parseLines,
  presentCandidateValue,
  progressPercent,
  qualityLevelFromScore,
  qualityTone,
  readRecordValue,
  scoreFieldQuality,
  scoreRecordQuality,
  stringifyCell,
  uniqueFields,
  uniqueNumbers,
  uniqueRequestedFields,
  uniqueStrings,
  validateAdditionalFieldName,
};
export type { QualityLevel, QualitySnapshot };
export {
  AdditionalFieldInput,
  FieldEditorHeader,
  LogTerminal,
  ManualFieldEditor,
  RecordsTable,
  RecordThumbnail,
  SettingSection,
  SliderRow,
  buildLogSiteGroups,
  getLogStage,
  scrollViewportToBottom,
};
export type { FieldRow, FieldRowMessageTone, ValidationState };

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
export type OutputTabKey = 'table' | 'json' | 'logs' | 'learning' | 'run_config';
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
  if (domain === 'forum_thread') {
    return 'forum_detail';
  }
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
  if (normalizedSurface.startsWith('automobile_')) {
    return 'automobiles';
  }
  if (normalizedSurface.startsWith('article_')) {
    return 'article';
  }
  if (normalizedSurface.startsWith('content_')) {
    return 'content';
  }
  if (normalizedSurface === 'forum_detail') {
    return 'forum_thread';
  }
  return null;
}

export function ActionButton({
  label,
  danger,
  disabled,
  onClick,
}: Readonly<{ label: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>) {
  return (
    <Button
      type="button"
      variant={danger ? 'danger' : 'secondary'}
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className="type-control h-8 min-w-0 px-3"
    >
      {label}
    </Button>
  );
}

export function PreviewRow({
  label,
  value,
  mono,
}: Readonly<{ label: string; value: ReactNode; mono?: boolean }>) {
  return (
    <div className="surface-muted flex items-start justify-between gap-4 rounded-[var(--radius-md)] px-3 py-2">
      <div className="field-label shrink-0">{label}</div>
      <div
        className={cn(
          'type-body-sm text-foreground min-w-0 flex-1 text-right font-normal',
          mono && 'type-caption-mono font-medium !text-foreground',
        )}
      >
        {value || '--'}
      </div>
    </div>
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
