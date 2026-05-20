'use client';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Database,
  Dot,
  Globe,
  HardDrive,
  Layers,
  Monitor,
  RefreshCw,
  ShieldAlert,
  XCircle,
  Zap,
} from 'lucide-react';
import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';

import type { CrawlLog, CrawlRecord } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import {
  formatDurationMs,
  formatTimeHms,
  humanizeFieldName,
  normalizeField,
  parseApiDate,
} from '../../lib/crawl/format';
import { uniqueRequestedFields } from '../../lib/crawl/fields';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import { isInformativeValue, qualityLevelFromScore } from '../../lib/crawl/quality';
import { scrollViewportToBottom } from '../../lib/crawl/scroll';
import { syntaxHighlightJson } from '../../lib/ui/syntax';
import { Button } from '../ui/primitives';
function useLogViewport(_logCount: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const targetRef = ref ?? internalRef;

  useEffect(() => {
    if (!ref) {
      scrollViewportToBottom(internalRef);
    }
  }, [_logCount, ref]);

  return targetRef;
}
function getLogIcon(level: string, message: string) {
  const msg = message.toLowerCase();
  const isWarn = level === 'warning' || level === 'warn';
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return XCircle;
  if (isWarn) return AlertTriangle;

  if (msg.includes('starting crawl')) return Activity;
  if (msg.includes('ignoring robots.txt')) return ShieldAlert;
  if (msg.includes('extracted')) return Database;
  if (msg.includes('normalized') || msg.includes('normalised')) return Layers;
  if (msg.includes('persisted')) return HardDrive;
  if (msg.includes('acquiring') || msg.includes('fetching')) return Globe;
  if (
    msg.includes('browser') ||
    msg.includes('playwright') ||
    msg.includes('patchright') ||
    msg.includes('headless')
  )
    return Monitor;
  if (msg.includes('record')) return Database;
  if (msg.includes('page loaded') || msg.includes('page load')) return Zap;
  if (
    msg.includes('challenge') ||
    msg.includes('blocked') ||
    msg.includes('captcha') ||
    msg.includes('bot check')
  )
    return ShieldAlert;
  if (hasUrl) return Globe;
  if (msg.includes('retry') || msg.includes('retrying') || msg.includes('refresh'))
    return RefreshCw;
  if (
    msg.includes('complete') ||
    msg.includes('success') ||
    msg.includes('done') ||
    msg.includes('finished')
  )
    return CheckCircle2;
  return Dot;
}

function getLogIconStyle(level: string, message: string): { iconCls: string; bgCls: string } {
  const msg = message.toLowerCase();
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (level === 'warning' || level === 'warn')
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };

  if (msg.includes('starting crawl')) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (msg.includes('ignoring robots.txt'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (msg.includes('resolved')) return { iconCls: 'text-muted ', bgCls: 'bg-zinc-500/10' };
  if (msg.includes('acquired')) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (msg.includes('extracted')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('normalized') || msg.includes('normalised'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (msg.includes('persisted')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('page loaded') || msg.includes('page load'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (
    msg.includes('challenge') ||
    msg.includes('blocked') ||
    msg.includes('captcha') ||
    msg.includes('bot check')
  )
    return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (msg.includes('acquiring') || msg.includes('fetching'))
    return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (
    msg.includes('browser') ||
    msg.includes('patchright') ||
    msg.includes('playwright') ||
    msg.includes('headless')
  )
    return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (msg.includes('record')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (hasUrl) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (
    msg.includes('complete') ||
    msg.includes('success') ||
    msg.includes('done') ||
    msg.includes('finished')
  )
    return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('retry') || msg.includes('retrying'))
    return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (level === 'debug') return { iconCls: 'text-muted', bgCls: 'bg-transparent' };
  return {
    iconCls: 'text-secondary',
    bgCls: 'bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)]',
  };
}

function logMessageIsError(level: string, message: string): boolean {
  const normalizedLevel = String(level || '').toLowerCase();
  if (normalizedLevel === 'error') return true;
  if (normalizedLevel) return false;
  const text = String(message || '');
  const lowered = text.toLowerCase();
  if (
    /\b(no|not|none|no longer)\s+(error|errors|failed)\b/i.test(text) ||
    lowered.includes('no errors found') ||
    lowered.includes('validation failed check passed')
  ) {
    return false;
  }
  return /^\s*(error|failed)\b/i.test(text);
}

export type LogStage = 'acquisition' | 'extraction' | 'normalize' | 'persistence' | 'system';

export interface LogStageConfig {
  label: string;
  borderClass: string;
  chipClass: string;
  textOnlyClass: string;
  panelClass: string;
}

const DISPLAY_LOG_STAGES: LogStage[] = ['acquisition', 'extraction', 'normalize', 'persistence'];

export const STAGE_CONFIG: Record<LogStage, LogStageConfig> = {
  acquisition: {
    label: 'Acquire',
    borderClass: 'border-info/30',
    chipClass: 'bg-info text-white font-medium',
    textOnlyClass: 'text-info font-medium',
    panelClass: 'border-info/20 bg-info-bg',
  },
  extraction: {
    label: 'Extract',
    borderClass: 'border-accent/30',
    chipClass: 'bg-accent text-accent-fg font-medium',
    textOnlyClass: 'text-accent font-medium',
    panelClass: 'border-accent/20 bg-accent-subtle',
  },
  normalize: {
    label: 'Normalize',
    borderClass: 'border-warning/30',
    chipClass: 'bg-warning text-white font-bold',
    textOnlyClass: 'text-warning font-bold',
    panelClass: 'border-warning/20 bg-warning-bg',
  },
  persistence: {
    label: 'Persist',
    borderClass: 'border-info/30',
    chipClass: 'bg-info text-white font-bold',
    textOnlyClass: 'text-info font-bold',
    panelClass: 'border-info/20 bg-info-bg',
  },
  system: {
    label: 'Run',
    borderClass: 'border-border-strong',
    chipClass: 'bg-zinc-700 text-white font-medium',
    textOnlyClass: 'text-muted font-medium',
    panelClass: 'border-border bg-subtle-panel-bg',
  },
};

export const TERMINAL_STRINGS = {
  FIELDS: 'Fields',
  CONFIDENCE: 'Confidence',
  TIME: 'Time',
  RUN_EVENTS: 'Run Events',
  PENDING: 'Pending...',
  SITE_PAYLOAD: 'Site payload',
  PAYLOAD_PEEK: 'Payload Peek',
  NO_LOGS: 'No logs.',
  NO_PAYLOAD: 'No persisted payload for this site yet.',
} as const;

export const LOG_PATTERNS = {
  STARTING_CRAWL: /^Starting crawl run for (https?:\/\/\S+?)(?: \((\d+)\/(\d+)\))?$/i,
  ROBOTS_IGNORE: /ignoring robots\.txt/i,
  PERSISTENCE_SUMMARY: /\bpersisted\s+\d+\s+record/i,
  ROBOTS_PREFIX: /^\[ROBOTS\]\s*/i,
  HEADLESS_BROWSER: /launched headless browser \(([^,]+),[^)]+\)/i,
  URL: /https?:\/\/[^\s]+/g,
  COUNTER: /\(\d+\/\d+\)/,
} as const;

export function getLogStage(message: string): LogStage {
  const text = message.toLowerCase();
  if (text.includes('persisted') || text.includes('persisting') || text.includes('committed')) {
    return 'persistence';
  }
  if (
    text.includes('normalized') ||
    text.includes('normalised') ||
    text.includes('schema validation cleaned')
  ) {
    return 'normalize';
  }
  if (
    text.includes('extracted') ||
    text.includes('extraction yielded') ||
    text.includes('rejected detail extraction') ||
    text.includes('traversal yielded') ||
    text.includes('selector self-heal')
  ) {
    return 'extraction';
  }
  if (
    text.includes('acquiring') ||
    text.includes('robots') ||
    text.includes('proxy') ||
    text.includes('browser') ||
    text.includes('navigation') ||
    text.includes('page loaded') ||
    text.includes('acquired payload')
  ) {
    return 'acquisition';
  }
  if (
    text.includes('starting crawl') ||
    text.includes('resolved') ||
    text.includes('pipeline finished') ||
    text.includes('stopped after reaching') ||
    text.includes('run paused') ||
    text.includes('run killed')
  ) {
    return 'system';
  }
  return 'system';
}

type LogSiteGroup = {
  key: string;
  label: string;
  url: string;
  index: number | null;
  total: number | null;
  logs: CrawlLog[];
  stageLogs: Record<LogStage, CrawlLog[]>;
  records: CrawlRecord[];
  hasError: boolean;
  hasWarning: boolean;
  lastStage: LogStage;
  recordCount: number;
};

function parseStartingLog(message: string) {
  const match = sanitizeLogMessage(message).match(LOG_PATTERNS.STARTING_CRAWL);
  if (!match) {
    return null;
  }
  const [, url, indexValue, totalValue] = match;
  return {
    url,
    index: indexValue ? Number.parseInt(indexValue, 10) : null,
    total: totalValue ? Number.parseInt(totalValue, 10) : null,
  };
}

function isWarningLog(log: CrawlLog) {
  const level = String(log.level || '').toLowerCase();
  if (level === 'warn' || level === 'warning') {
    return true;
  }
  const text = log.message.toLowerCase();
  return (
    text.includes('partial') ||
    text.includes('yielded 0 records') ||
    text.includes('retrying') ||
    text.includes('rejected detail extraction')
  );
}

function isHiddenLogMessage(message: string) {
  return LOG_PATTERNS.ROBOTS_IGNORE.test(String(message || ''));
}

function isPersistenceSummaryLog(message: string) {
  return LOG_PATTERNS.PERSISTENCE_SUMMARY.test(String(message || ''));
}

function matchesSiteUrl(record: CrawlRecord, siteUrl: string) {
  const candidates = new Set<string>();
  for (const value of [
    record.source_url,
    record.data?.url,
    record.raw_data?.url,
    record.source_trace?.acquisition && typeof record.source_trace.acquisition === 'object'
      ? (record.source_trace.acquisition as Record<string, unknown>).final_url
      : null,
  ]) {
    const text = typeof value === 'string' ? value.trim() : '';
    if (text) {
      candidates.add(text);
    }
  }
  return candidates.has(siteUrl);
}

function siteLabel(url: string, index: number | null, total: number | null) {
  const prefix = index && total ? `${index}/${total}` : index ? String(index) : null;
  return prefix ? `${prefix} ${url}` : url;
}

function siteDomId(groupKey: string) {
  return `site-log-${groupKey.replace(/[^a-z0-9_-]+/gi, '-')}`;
}

type LogSiteGroupDraft = Omit<
  LogSiteGroup,
  'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'
>;

function emptyStageLogs(): Record<LogStage, CrawlLog[]> {
  return {
    acquisition: [],
    extraction: [],
    normalize: [],
    persistence: [],
    system: [],
  };
}

function createSiteGroup({
  key,
  url,
  index,
  total,
}: {
  key: string;
  url: string;
  index: number | null;
  total: number | null;
}): LogSiteGroupDraft {
  return {
    key,
    label: siteLabel(url, index, total),
    url,
    index,
    total,
    logs: [],
    stageLogs: emptyStageLogs(),
  };
}

function createRunGroup(key: string): LogSiteGroupDraft {
  return {
    key,
    label: TERMINAL_STRINGS.RUN_EVENTS,
    url: '',
    index: null,
    total: null,
    logs: [],
    stageLogs: emptyStageLogs(),
  };
}

function addLogToGroup(group: LogSiteGroupDraft, log: CrawlLog, stage: LogStage) {
  group.logs.push(log);
  group.stageLogs[stage].push(log);
}

function firstUrlInLog(message: string): string {
  return sanitizeLogMessage(message).match(/https?:\/\/[^\s]+/i)?.[0] ?? '';
}

export function buildLogSiteGroups(logs: CrawlLog[], records: CrawlRecord[] = []): LogSiteGroup[] {
  const groups: LogSiteGroupDraft[] = [];
  let currentGroup: LogSiteGroupDraft | null = null;
  let pendingRunLogs: CrawlLog[] = [];
  let untitledCounter = 0;

  for (const log of logs) {
    if (isHiddenLogMessage(log.message)) {
      continue;
    }
    const start = parseStartingLog(log.message);
    if (start) {
      if (pendingRunLogs.length) {
        untitledCounter += 1;
        const runGroup = createRunGroup(`run:${untitledCounter}`);
        for (const pendingLog of pendingRunLogs) {
          addLogToGroup(runGroup, pendingLog, getLogStage(pendingLog.message));
        }
        groups.push(runGroup);
        pendingRunLogs = [];
      }
      currentGroup = createSiteGroup({
        key: `site:${start.index ?? logs.indexOf(log)}:${start.url}`,
        url: start.url,
        index: start.index,
        total: start.total,
      });
      groups.push(currentGroup);
      addLogToGroup(currentGroup, log, 'system');
      continue;
    }

    if (!currentGroup) {
      const inferredUrl = firstUrlInLog(log.message);
      if (!inferredUrl) {
        pendingRunLogs.push(log);
        continue;
      }
      currentGroup = createSiteGroup({
        key: `site:inferred:${log.id}:${inferredUrl}`,
        url: inferredUrl,
        index: null,
        total: null,
      });
      groups.push(currentGroup);
      for (const pendingLog of pendingRunLogs) {
        addLogToGroup(currentGroup, pendingLog, getLogStage(pendingLog.message));
      }
      pendingRunLogs = [];
    }

    addLogToGroup(currentGroup, log, getLogStage(log.message));
  }

  if (pendingRunLogs.length) {
    untitledCounter += 1;
    const runGroup = createRunGroup(`run:${untitledCounter}`);
    for (const pendingLog of pendingRunLogs) {
      addLogToGroup(runGroup, pendingLog, getLogStage(pendingLog.message));
    }
    groups.push(runGroup);
  }

  return groups.map((group) => {
    const matchedRecords = group.url
      ? records.filter((record) => matchesSiteUrl(record, group.url))
      : [];
    let lastStage: LogStage = 'system';
    for (const stage of [...DISPLAY_LOG_STAGES, 'system'] as LogStage[]) {
      if (group.stageLogs[stage].length > 0) {
        lastStage = stage;
      }
    }
    const hasError = group.logs.some((log) => logMessageIsError(log.level, log.message));
    const hasWarning = !hasError && group.logs.some(isWarningLog);
    return {
      ...group,
      records: matchedRecords,
      hasError,
      hasWarning,
      lastStage,
      recordCount: matchedRecords.length,
    };
  });
}

function severityTone(group: LogSiteGroup, index: number) {
  // REMOVED ALL BACKGROUND COLORS AS PER USER REQUEST - TERMINAL IS NOW MONOCHROMATIC
  if (group.hasError) {
    return 'bg-transparent border-l-2 border-l-danger';
  }
  if (group.hasWarning) {
    return 'bg-transparent border-l-2 border-l-warning';
  }
  if (group.recordCount > 0 || group.stageLogs.persistence.length > 0) {
    return 'bg-transparent border-l-2 border-l-success';
  }
  return index % 2 === 0
    ? 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]'
    : 'bg-transparent';
}

function severityLabel(group: LogSiteGroup) {
  if (group.hasError) {
    return 'Error';
  }
  if (group.hasWarning) {
    return 'Warning';
  }
  if (group.recordCount > 0 || group.stageLogs.persistence.length > 0) {
    return 'Persisted';
  }
  return 'Running';
}

function payloadSnapshot(group: LogSiteGroup) {
  if (!group.records.length) {
    return '';
  }
  const payload =
    group.records.length === 1
      ? cleanRecordForDisplay(group.records[0])
      : group.records.map(cleanRecordForDisplay);
  return JSON.stringify(payload, null, 2);
}

function publicFieldNames(record: CrawlRecord) {
  return Object.entries(record.data ?? {})
    .filter(([key, value]) => !key.startsWith('_') && isInformativeValue(value))
    .map(([key]) => key);
}

function recordConfidence(record: CrawlRecord): { score: number; level: string } | null {
  const rawConfidence =
    (record.raw_data && typeof record.raw_data === 'object'
      ? (record.raw_data as Record<string, unknown>)._confidence
      : null) ||
    (record.discovered_data && typeof record.discovered_data === 'object'
      ? (record.discovered_data as Record<string, unknown>).confidence
      : null);
  if (!rawConfidence || typeof rawConfidence !== 'object') {
    return null;
  }
  const payload = rawConfidence as Record<string, unknown>;
  const score = Number(payload.score);
  if (!Number.isFinite(score)) {
    return null;
  }
  return {
    score,
    level:
      String(payload.level || qualityLevelFromScore(score))
        .trim()
        .toLowerCase() || 'unknown',
  };
}

function groupConfidence(group: LogSiteGroup): { score: number; level: string } | null {
  const scores = group.records
    .map(recordConfidence)
    .filter((value): value is { score: number; level: string } => value !== null);
  if (!scores.length) {
    return null;
  }
  const average = scores.reduce((total, item) => total + item.score, 0) / scores.length;
  return {
    score: average,
    level: String(qualityLevelFromScore(average)),
  };
}

function numberOrNull(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function groupDurationMs(group: LogSiteGroup, activeNowMs?: number): number | null {
  const recordDurations = group.records
    .map((record) => {
      const acquisition =
        record.source_trace?.acquisition && typeof record.source_trace.acquisition === 'object'
          ? (record.source_trace.acquisition as Record<string, unknown>)
          : null;
      const browserDiagnostics =
        acquisition?.browser_diagnostics && typeof acquisition.browser_diagnostics === 'object'
          ? (acquisition.browser_diagnostics as Record<string, unknown>)
          : null;
      const phaseTimings =
        browserDiagnostics?.phase_timings_ms &&
        typeof browserDiagnostics.phase_timings_ms === 'object'
          ? (browserDiagnostics.phase_timings_ms as Record<string, unknown>)
          : null;
      return numberOrNull(phaseTimings?.total);
    })
    .filter((value): value is number => value !== null);
  const startedAt = group.logs[0]?.created_at;
  if (!startedAt) {
    return null;
  }
  const startedMs = parseApiDate(startedAt).getTime();
  if (!Number.isFinite(startedMs)) {
    return null;
  }
  const lastLog = group.logs.at(-1);
  const endCandidatesMs = [
    activeNowMs,
    lastLog?.created_at ? parseApiDate(lastLog.created_at).getTime() : null,
    ...group.records.map((record) => parseApiDate(record.created_at).getTime()),
    ...recordDurations.map((durationMs) => startedMs + durationMs),
  ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!endCandidatesMs.length) {
    return null;
  }
  return Math.max(0, Math.max(...endCandidatesMs) - startedMs);
}

function groupFieldCoverage(group: LogSiteGroup, requestedFields: string[]) {
  const requested = uniqueRequestedFields(requestedFields);
  const normalizedRequested = requested.map(normalizeField);
  const foundNormalized = new Set<string>();
  const foundOriginal = new Map<string, string>();

  for (const record of group.records) {
    for (const field of publicFieldNames(record)) {
      const normalized = normalizeField(field);
      foundNormalized.add(normalized);
      if (!foundOriginal.has(normalized)) {
        foundOriginal.set(normalized, field);
      }
    }
  }

  if (requested.length) {
    const covered = requested.filter(
      (field, index) =>
        foundNormalized.has(normalizedRequested[index]) || foundNormalized.has(field),
    );
    return {
      foundCount: covered.length,
      totalCount: requested.length,
      labels: covered,
    };
  }

  const labels = Array.from(foundOriginal.values());
  return {
    foundCount: labels.length,
    totalCount: labels.length,
    labels,
  };
}

function toneForConfidence(level: string) {
  if (level === 'high') return 'text-success';
  if (level === 'medium') return 'text-warning';
  if (level === 'low') return 'text-danger';
  return 'text-muted';
}

type ExpandedLogRow = {
  key: string;
  stage: LogStage;
  level: string;
  message: string;
  createdAt?: string | null;
  payloadAction?: boolean;
};

function buildExpandedRows(
  group: LogSiteGroup,
  coverage: ReturnType<typeof groupFieldCoverage>,
  confidence: ReturnType<typeof groupConfidence>,
  durationMs: number | null,
): ExpandedLogRow[] {
  const rows: ExpandedLogRow[] = group.logs.map((log) => ({
    key: `log-${log.id}`,
    stage: parseStartingLog(log.message) ? 'system' : getLogStage(log.message),
    level: log.level,
    message: log.message,
    createdAt: log.created_at,
  }));

  if (coverage.totalCount > 0 || coverage.labels.length > 0 || confidence) {
    const parts: string[] = [];
    if (coverage.totalCount > 0) {
      const labels = coverage.labels.length
        ? coverage.labels.map(humanizeFieldName).join(', ')
        : 'none';
      parts.push(
        `${TERMINAL_STRINGS.FIELDS} ${coverage.foundCount}/${coverage.totalCount}: ${labels}`,
      );
    }
    if (confidence) {
      parts.push(`${TERMINAL_STRINGS.CONFIDENCE} ${Math.round(confidence.score * 100)}%`);
    }
    if (durationMs !== null) {
      parts.push(`${TERMINAL_STRINGS.TIME} ${formatDurationMs(durationMs)}`);
    }
    rows.push({
      key: `${group.key}-fields`,
      stage: 'persistence',
      level: 'info',
      message: parts.join(' | '),
      payloadAction: group.records.length > 0,
    });
  }

  return rows;
}

function formatShortUrlLabel(url: string) {
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
    return url.length > 40 ? url.slice(0, 40) + '…' : url;
  }
}

function sanitizeLogMessage(message: string) {
  return String(message || '')
    .replace(/\s*\[corr=[^\]]+\]/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function ShortenedUrl({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-info decoration-info/20 hover:text-accent type-body underline underline-offset-4 transition-colors"
      title={url}
      onClick={(e) => e.stopPropagation()}
    >
      {formatShortUrlLabel(url)}
    </a>
  );
}

function renderLogContent(message: string, isStartingCrawl: boolean): React.ReactNode {
  let text = sanitizeLogMessage(message).replace(LOG_PATTERNS.ROBOTS_PREFIX, '');
  text = text.replace(
    LOG_PATTERNS.HEADLESS_BROWSER,
    (_, engine) => `Launched ${engine.trim()} browser`,
  );

  const urlRegex = LOG_PATTERNS.URL;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = urlRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<ShortenedUrl key={match.index} url={match[0]} />);
    lastIndex = urlRegex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  const baseContent = parts.length > 0 ? parts : [text];

  if (isStartingCrawl) {
    return baseContent.map((part, i) => {
      if (typeof part === 'string') {
        const counterMatch = part.match(LOG_PATTERNS.COUNTER);
        if (counterMatch && counterMatch.index !== undefined) {
          const before = part.slice(0, counterMatch.index);
          const after = part.slice(counterMatch.index + counterMatch[0].length);
          return (
            <React.Fragment key={i}>
              {before}
              <span className="text-blue-400/70">{counterMatch[0]}</span>
              {after}
            </React.Fragment>
          );
        }
      }
      return part;
    });
  }

  return baseContent;
}

export const LogTerminal = memo(function LogTerminal({
  logs,
  records = [],
  requestedFields = [],
  live = false,
  viewportRef,
}: Readonly<{
  logs: CrawlLog[];
  records?: CrawlRecord[];
  requestedFields?: string[];
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
}>) {
  const ref = useLogViewport(logs.length, viewportRef);
  const peekPanelRef = useRef<HTMLDivElement | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [peekedGroupKey, setPeekedGroupKey] = useState<string | null>(null);
  const [peekedRecordIndex, setPeekedRecordIndex] = useState(0);
  const [expandedGroupPreference, setExpandedGroupPreference] = useState<
    string | null | '__auto__'
  >('__auto__');
  const [triageCursor, setTriageCursor] = useState(0);
  const groups = useMemo(() => buildLogSiteGroups(logs, records), [logs, records]);
  const issueGroups = useMemo(
    () => groups.filter((group) => group.hasError || group.hasWarning),
    [groups],
  );
  const activePeekedGroupKey = useMemo(
    () =>
      peekedGroupKey && groups.some((group) => group.key === peekedGroupKey)
        ? peekedGroupKey
        : null,
    [groups, peekedGroupKey],
  );
  const peekedGroup = useMemo(
    () => groups.find((group) => group.key === activePeekedGroupKey) ?? null,
    [activePeekedGroupKey, groups],
  );
  const expandedGroupKey = useMemo(() => {
    if (
      expandedGroupPreference &&
      expandedGroupPreference !== '__auto__' &&
      groups.some((group) => group.key === expandedGroupPreference)
    ) {
      return expandedGroupPreference;
    }
    if (expandedGroupPreference === null) {
      return null;
    }
    if (live && groups.length > 0) {
      return groups[groups.length - 1].key;
    }
    return issueGroups[0]?.key ?? null;
  }, [expandedGroupPreference, groups, issueGroups, live]);
  const safePeekedRecordIndex = peekedGroup
    ? Math.min(peekedRecordIndex, Math.max(peekedGroup.records.length - 1, 0))
    : 0;
  const peekedRecordJson =
    peekedGroup && peekedGroup.records[safePeekedRecordIndex]
      ? JSON.stringify(cleanRecordForDisplay(peekedGroup.records[safePeekedRecordIndex]), null, 2)
      : '';
  const safeTriageCursor = issueGroups.length ? Math.min(triageCursor, issueGroups.length - 1) : 0;

  useEffect(() => {
    if (!live) {
      return;
    }
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  useEffect(() => {
    if (!activePeekedGroupKey) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const panel = peekPanelRef.current;
      if (!panel) {
        return;
      }
      if (!panel.contains(event.target as Node)) {
        setPeekedGroupKey(null);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [activePeekedGroupKey]);

  const timelineTicks = useMemo(() => {
    if (!groups.length) {
      return [];
    }
    const start = parseApiDate(groups[0].logs[0]?.created_at ?? new Date().toISOString()).getTime();
    const end = parseApiDate(
      groups[groups.length - 1].logs.at(-1)?.created_at ??
        groups[0].logs[0]?.created_at ??
        new Date().toISOString(),
    ).getTime();
    const range = Math.max(1, end - start);
    return groups.map((group) => {
      const createdAt = group.logs[0]?.created_at ?? new Date().toISOString();
      const percent = ((parseApiDate(createdAt).getTime() - start) / range) * 100;
      return {
        key: group.key,
        percent,
        tone: group.hasError
          ? 'bg-danger'
          : group.hasWarning
            ? 'bg-warning'
            : group.recordCount > 0
              ? 'bg-emerald-400'
              : 'bg-white/15',
      };
    });
  }, [groups]);

  const jumpToGroup = (groupKey: string) => {
    const el = document.getElementById(siteDomId(groupKey));
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('log-entry-highlight');
      setTimeout(() => el.classList.remove('log-entry-highlight'), 2000);
    }
    setExpandedGroupPreference(groupKey);
  };

  const toggleGroup = (groupKey: string) => {
    if (live && groups.length > 0 && groupKey === groups[groups.length - 1].key) {
      return;
    }
    setExpandedGroupPreference((current) => (current === groupKey ? null : groupKey));
  };

  const navigateTriage = (dir: 'next' | 'prev') => {
    if (!issueGroups.length) {
      return;
    }
    const delta = dir === 'next' ? 1 : -1;
    const nextIndex = (safeTriageCursor + delta + issueGroups.length) % issueGroups.length;
    setTriageCursor(nextIndex);
    jumpToGroup(issueGroups[nextIndex].key);
  };

  return (
    <div
      className="group/terminal relative flex flex-col overflow-hidden rounded-none border"
      style={{
        borderColor: 'var(--terminal-border)',
        backgroundColor: 'var(--terminal-bg)',
        color: 'var(--terminal-fg)',
        boxShadow: 'var(--terminal-shadow)',
      }}
    >
      <div
        className="flex h-9 items-center justify-between border-b bg-[color-mix(in_srgb,var(--text-primary)_5%,transparent)] px-6"
        style={{ borderColor: 'var(--terminal-border)' }}
      >
        <span className="text-muted type-label-mono tracking-[0.25em] uppercase">
          activity_stream.log
        </span>
        <div className="flex items-center gap-3">
          <div className="group/scrubber relative flex h-2 w-32 cursor-crosshair items-center rounded-sm bg-[color-mix(in_srgb,var(--text-primary)_8%,transparent)]">
            {timelineTicks.map((tick) => (
              <div
                key={tick.key}
                role="button"
                tabIndex={0}
                aria-label={`Jump to ${tick.key}`}
                onClick={() => jumpToGroup(tick.key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ' || e.code === 'Space') {
                    e.preventDefault();
                    jumpToGroup(tick.key);
                  }
                }}
                className={cn(
                  'focus-visible:ring-accent absolute h-full w-0.5 cursor-pointer transition-transform hover:scale-y-125 focus-visible:scale-y-125 focus-visible:ring-1 focus-visible:outline-none',
                  tick.tone,
                )}
                style={{ left: `${tick.percent}%` }}
              />
            ))}
          </div>
          <div className="flex items-center gap-3 opacity-60 transition-opacity group-focus-within/terminal:opacity-100 group-hover/terminal:opacity-100">
            <button
              onClick={() => navigateTriage('prev')}
              className="type-label-mono hover:text-accent focus-visible:text-accent focus-visible:outline-none"
            >
              Prev
            </button>
            <span className="bg-muted h-3 w-px opacity-20" />
            <button
              onClick={() => navigateTriage('next')}
              className="type-label-mono hover:text-accent focus-visible:text-accent focus-visible:outline-none"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      <div
        ref={ref}
        className="crawl-activity-log max-h-[78vh] min-h-[62vh] overflow-y-auto"
        role="log"
        aria-live={live ? 'polite' : 'off'}
        aria-atomic="false"
      >
        {groups.length ? (
          groups.map((group, index) => {
            const activeKey = live && groups.length > 0 ? groups[groups.length - 1].key : null;
            const expanded = expandedGroupKey === group.key || group.key === activeKey;
            const isRunEventGroup = !group.url;
            const payload = payloadSnapshot(group);
            const confidence = groupConfidence(group);
            const coverage = groupFieldCoverage(group, requestedFields);
            const activeGroup =
              live && groups.length > 0 && group.key === groups[groups.length - 1].key;
            const durationMs = groupDurationMs(group, activeGroup ? nowMs : undefined);
            const lastLog = group.logs.at(-1);
            const summaryLog =
              [...group.logs].reverse().find((log) => !isPersistenceSummaryLog(log.message)) ??
              lastLog;
            const expandedRows = buildExpandedRows(group, coverage, confidence, durationMs);
            return (
              <section key={group.key} id={siteDomId(group.key)} className="overflow-hidden">
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={expanded}
                  aria-label={`${expanded ? 'Collapse' : 'Expand'} logs for ${group.url || group.label}`}
                  onClick={() => toggleGroup(group.key)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      toggleGroup(group.key);
                    }
                  }}
                  className={cn(
                    'group/row grid w-full cursor-pointer items-center gap-3 px-6 py-2.5 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset',
                    isRunEventGroup
                      ? 'grid-cols-[32px_minmax(280px,1fr)_auto_minmax(260px,1.4fr)_60px]'
                      : 'grid-cols-[32px_minmax(280px,2fr)_80px_100px_100px_auto_minmax(200px,1.2fr)_80px_60px]',
                    severityTone(group, index),
                  )}
                >
                  <div className="type-body text-muted font-medium opacity-60">
                    {(group.index ?? index + 1).toString().padStart(2, '0')}
                  </div>
                  <div className="min-w-0">
                    {isRunEventGroup ? (
                      <span
                        className="text-secondary block truncate text-sm font-medium"
                        title={group.label}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {group.label}
                      </span>
                    ) : (
                      <a
                        href={group.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-info block truncate text-sm font-normal underline-offset-4 hover:underline"
                        title={group.url}
                      >
                        {formatShortUrlLabel(group.url)}
                      </a>
                    )}
                  </div>
                  {!isRunEventGroup ? (
                    <>
                      <div className="type-body text-secondary font-medium whitespace-nowrap">
                        <span className="text-muted mr-1.5 font-sans text-sm font-bold tracking-wider uppercase">
                          F:
                        </span>
                        {coverage.foundCount}/{coverage.totalCount || 0}
                      </div>
                      <div className="type-body font-medium whitespace-nowrap">
                        <span className="text-muted mr-1.5 font-sans text-sm font-bold tracking-wider uppercase">
                          C:
                        </span>
                        <span
                          className={cn(
                            confidence ? toneForConfidence(confidence.level) : 'text-muted',
                          )}
                        >
                          {confidence ? `${Math.round(confidence.score * 100)}%` : '--'}
                        </span>
                      </div>
                      <div className="type-body text-secondary font-medium whitespace-nowrap">
                        <span className="text-muted mr-1.5 font-sans text-sm font-bold tracking-wider uppercase">
                          T:
                        </span>
                        {durationMs !== null ? formatDurationMs(durationMs) : '--'}
                      </div>
                    </>
                  ) : null}
                  <div className="flex items-center justify-center">
                    {isRunEventGroup ? (
                      <div className="text-muted type-label-mono uppercase">Run</div>
                    ) : group.lastStage !== 'system' ? (
                      <div
                        className={cn(
                          'rounded px-1.5 py-0.5 text-sm font-bold tracking-wider uppercase',
                          STAGE_CONFIG[group.lastStage].chipClass,
                        )}
                      >
                        {STAGE_CONFIG[group.lastStage].label}
                      </div>
                    ) : null}
                  </div>
                  <div className="min-w-0">
                    <div
                      className="type-control text-secondary truncate"
                      title={summaryLog?.message || ''}
                    >
                      {summaryLog
                        ? sanitizeLogMessage(summaryLog.message)
                        : TERMINAL_STRINGS.PENDING}
                    </div>
                  </div>
                  {!isRunEventGroup ? (
                    <div className="flex items-center justify-end">
                      {payload ? (
                        <Button
                          type="button"
                          variant="quiet"
                          size="sm"
                          onClick={(event) => {
                            event.stopPropagation();
                            setPeekedGroupKey(group.key);
                            setPeekedRecordIndex(0);
                          }}
                        >
                          Peek
                        </Button>
                      ) : (
                        <span className="type-caption opacity-25">--</span>
                      )}
                    </div>
                  ) : null}
                  <div className="pr-2 text-right">
                    <div className="text-muted group-hover/row:text-secondary type-label-mono uppercase transition-colors">
                      {live && groups.length > 0 && group.key === groups[groups.length - 1].key
                        ? 'Active'
                        : expanded
                          ? 'Less'
                          : 'More'}
                    </div>
                  </div>
                </div>

                {expanded ? (
                  <div className="bg-[color-mix(in_srgb,var(--bg-alt)_60%,transparent)]">
                    <div className="overflow-hidden">
                      {expandedRows.length ? (
                        expandedRows.map((row, expandedIndex) => {
                          return (
                            <div
                              key={row.key}
                              className={cn(
                                'grid grid-cols-[64px_84px_minmax(0,1fr)_auto] items-center gap-4 px-6 py-2 text-xs',
                                expandedIndex % 2 === 0
                                  ? 'bg-[color-mix(in_srgb,var(--bg-alt)_35%,transparent)]'
                                  : 'bg-transparent',
                              )}
                            >
                              <span className="text-muted font-mono text-xs font-medium tabular-nums">
                                {row.createdAt ? formatTimeHms(row.createdAt) : '--'}
                              </span>
                              <span
                                className={cn(
                                  'inline-flex text-xs font-semibold tracking-wider uppercase',
                                  STAGE_CONFIG[row.stage].textOnlyClass,
                                )}
                              >
                                {STAGE_CONFIG[row.stage].label}
                              </span>
                              <span className="type-body text-secondary min-w-0 font-medium break-words">
                                {!row.createdAt
                                  ? row.message
                                  : renderLogContent(row.message, row.stage === 'system')}
                              </span>
                              <span className="flex items-center gap-2">
                                {row.payloadAction ? (
                                  <Button
                                    type="button"
                                    variant="quiet"
                                    size="sm"
                                    onClick={() => {
                                      setPeekedGroupKey(group.key);
                                      setPeekedRecordIndex(0);
                                    }}
                                  >
                                    Peek payload
                                  </Button>
                                ) : null}
                              </span>
                            </div>
                          );
                        })
                      ) : (
                        <div className="px-3 py-2 text-xs opacity-40">
                          {TERMINAL_STRINGS.NO_LOGS}
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </section>
            );
          })
        ) : (
          <div className="px-6 py-8 text-center text-sm italic opacity-55">
            {live ? 'Waiting for log stream...' : 'No log activity recorded'}
          </div>
        )}
      </div>

      {activePeekedGroupKey ? (
        <div className="absolute inset-0 z-40 bg-[color-mix(in_srgb,var(--bg-base)_60%,transparent)] backdrop-blur-sm">
          <div
            ref={peekPanelRef}
            className="animate-in slide-in-from-right absolute inset-y-0 right-0 z-50 w-[36rem] max-w-full border-l duration-300"
            style={{
              borderColor: 'var(--terminal-border)',
              backgroundColor: 'var(--terminal-code-bg)',
              color: 'var(--terminal-fg)',
              boxShadow: 'var(--terminal-shadow)',
            }}
          >
            <div
              className="flex items-center justify-between border-b px-6 py-3"
              style={{
                borderColor: 'var(--terminal-border)',
                backgroundColor: 'var(--terminal-bg)',
              }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-accent type-label-mono font-bold uppercase">
                  {TERMINAL_STRINGS.PAYLOAD_PEEK}
                </div>
                <div
                  className="mt-0.5 truncate pr-4 text-xs font-medium tabular-nums"
                  style={{ color: 'var(--text-muted)' }}
                  title={peekedGroup?.label ?? ''}
                >
                  {peekedGroup?.label ?? TERMINAL_STRINGS.SITE_PAYLOAD}
                </div>
              </div>
              <Button
                type="button"
                variant="quiet"
                size="sm"
                onClick={() => setPeekedGroupKey(null)}
              >
                Close
              </Button>
            </div>
            <div className="relative h-[calc(100%-56px)] overflow-hidden p-6">
              <div className="group relative h-full">
                <div className="absolute top-3 right-3 z-10 opacity-0 transition-all group-hover:opacity-100">
                  <Button
                    type="button"
                    variant="quiet"
                    size="sm"
                    onClick={() => {
                      if (!peekedGroup) return;
                      const currentRecord =
                        peekedGroup.records[safePeekedRecordIndex] ?? peekedGroup.records[0];
                      if (!currentRecord) return;
                      void navigator.clipboard.writeText(
                        JSON.stringify(cleanRecordForDisplay(currentRecord), null, 2),
                      );
                    }}
                  >
                    <Copy className="mr-1.5 size-3" />
                    Copy
                  </Button>
                </div>
                {peekedRecordJson ? (
                  <pre className="crawl-terminal crawl-terminal-json h-full max-h-full overflow-auto">
                    <span className="sr-only">{peekedRecordJson}</span>
                    <span
                      aria-hidden="true"
                      dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(peekedRecordJson) }}
                    />
                  </pre>
                ) : (
                  <pre className="crawl-terminal crawl-terminal-json h-full max-h-full overflow-auto">
                    {TERMINAL_STRINGS.NO_PAYLOAD}
                  </pre>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
});
