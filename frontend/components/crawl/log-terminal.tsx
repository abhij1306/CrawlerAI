'use client';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Clock,
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
import { syntaxHighlightJsonNodes } from '../../lib/ui/syntax';
import { Button } from '../ui/primitives';
import {
  buildLogSiteGroups,
  getLogStage,
  isPersistenceSummaryLog,
  LOG_PATTERNS,
  logMessageIsError,
  parseStartingLog,
  sanitizeLogMessage,
  siteDomId,
  STAGE_CONFIG,
  TERMINAL_STRINGS,
} from './log-terminal-utils';
import type { LogStage, LogSiteGroup } from './log-terminal-utils';

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

function StageChip({ stage, showIcon = true }: { stage: LogStage; showIcon?: boolean }) {
  const config = STAGE_CONFIG[stage];
  let Icon = Activity;
  if (stage === 'acquisition') Icon = Globe;
  if (stage === 'extraction') Icon = Database;
  if (stage === 'normalize') Icon = Layers;
  if (stage === 'persistence') Icon = HardDrive;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-xs tracking-wide uppercase',
        config.textOnlyClass,
      )}
    >
      {showIcon ? <Icon className="size-3" /> : null}
      <span>{config.label}</span>
    </span>
  );
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
  return Object.entries(record.data ?? {}).flatMap(([key, value]) =>
    !key.startsWith('_') && isInformativeValue(value) ? [key] : [],
  );
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

function groupStillActive(group: LogSiteGroup) {
  if (!group.url) {
    return false;
  }
  const lastMessage = sanitizeLogMessage(group.logs.at(-1)?.message ?? '').toLowerCase();
  return !(
    group.stageLogs.persistence.length > 0 ||
    group.hasError ||
    lastMessage.includes('processing failed') ||
    lastMessage.includes('timed out') ||
    lastMessage.includes('stopped after reaching max_records')
  );
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

function ShortenedUrl({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-info decoration-info/20 hover:text-accent underline underline-offset-4 transition-colors"
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
    return baseContent.map((part) => {
      if (typeof part === 'string') {
        const counterMatch = part.match(LOG_PATTERNS.COUNTER);
        if (counterMatch && counterMatch.index !== undefined) {
          const before = part.slice(0, counterMatch.index);
          const after = part.slice(counterMatch.index + counterMatch[0].length);
          return (
            <React.Fragment key={`${before}-${counterMatch[0]}-${after}`}>
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
  const isParallelCrawl = useMemo(() => groups.filter((g) => g.url).length > 1, [groups]);
  const siteOrdinalByKey = useMemo(() => {
    let ordinal = 0;
    const values = new Map<string, number>();
    for (const group of groups) {
      if (!group.url) {
        continue;
      }
      ordinal += 1;
      values.set(group.key, ordinal);
    }
    return values;
  }, [groups]);
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
      className="crawl-terminal-shell group/terminal relative flex flex-col overflow-hidden rounded-none border"
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
        <div className="flex items-center gap-2">
          <span className="relative flex size-2">
            <span
              className={cn(
                'absolute inline-flex h-full w-full animate-ping rounded-full opacity-75',
                live ? 'bg-emerald-500' : 'bg-slate-400',
              )}
            ></span>
            <span
              className={cn(
                'relative inline-flex size-2 rounded-full',
                live ? 'bg-emerald-500' : 'bg-slate-400',
              )}
            ></span>
          </span>
          <span className="type-label-mono text-xs tracking-[0.25em] uppercase">
            activity_stream.log
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="group/scrubber relative flex h-2 w-32 cursor-crosshair items-center rounded-sm bg-[color-mix(in_srgb,var(--text-primary)_8%,transparent)]">
            {timelineTicks.map((tick) => (
              <button
                key={tick.key}
                type="button"
                aria-label={`Jump to ${tick.key}`}
                onClick={() => jumpToGroup(tick.key)}
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
              type="button"
              onClick={() => navigateTriage('prev')}
              className="type-label-mono hover:text-accent focus-visible:text-accent focus-visible:outline-none"
            >
              Prev
            </button>
            <span className="bg-muted h-3 w-px opacity-20" />
            <button
              type="button"
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
            const activeGroup = live && (group.key === activeKey || groupStillActive(group));
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
                    'group/row grid w-full cursor-pointer items-center gap-3 px-6 py-1 text-left text-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset',
                    isRunEventGroup
                      ? 'grid-cols-[32px_minmax(280px,1fr)_auto_minmax(260px,1.4fr)_60px]'
                      : 'grid-cols-[32px_minmax(280px,2fr)_75px_80px_85px_auto_minmax(200px,1.2fr)_80px_70px]',
                    severityTone(group, index),
                  )}
                >
                  <div className="text-muted text-xs font-medium opacity-60">
                    {(group.index ?? siteOrdinalByKey.get(group.key) ?? index + 1)
                      .toString()
                      .padStart(2, '0')}
                  </div>
                  <div className="flex min-w-0 items-center gap-2">
                    {!isRunEventGroup && <Globe className="text-muted size-3.5 shrink-0" />}
                    {isRunEventGroup ? (
                      <span
                        className="text-secondary block truncate text-xs font-medium"
                        title={group.label}
                      >
                        {group.label}
                      </span>
                    ) : (
                      <a
                        href={group.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-info block truncate text-xs font-normal underline-offset-4 hover:underline"
                        title={group.url}
                      >
                        {formatShortUrlLabel(group.url)}
                      </a>
                    )}
                    {isParallelCrawl && group.url && (
                      <span className="text-muted border-border shrink-0 rounded border px-1 py-px text-[9px] font-semibold tracking-widest uppercase">
                        Parallel
                      </span>
                    )}
                    <span className="text-muted shrink-0 font-mono text-[10px] opacity-50">
                      {group.logs.length} logs
                    </span>
                  </div>
                  {!isRunEventGroup ? (
                    <>
                      <div
                        className="border-border text-secondary flex items-center gap-1 rounded-md border bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)] px-1.5 py-0.5 text-xs font-medium whitespace-nowrap shadow-sm"
                        title="Fields Extracted"
                      >
                        <Database className="text-muted size-3 shrink-0" />
                        <span>
                          {coverage.foundCount}/{coverage.totalCount || 0}
                        </span>
                      </div>
                      <div
                        className="border-border text-secondary flex items-center gap-1 rounded-md border bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)] px-1.5 py-0.5 text-xs font-medium whitespace-nowrap shadow-sm"
                        title="Confidence Score"
                      >
                        <CheckCircle2
                          className={cn(
                            'size-3 shrink-0',
                            confidence ? toneForConfidence(confidence.level) : 'text-muted',
                          )}
                        />
                        <span
                          className={cn(
                            confidence ? toneForConfidence(confidence.level) : 'text-muted',
                          )}
                        >
                          {confidence ? `${Math.round(confidence.score * 100)}%` : '--'}
                        </span>
                      </div>
                      <div
                        className="border-border text-secondary flex items-center gap-1 rounded-md border bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)] px-1.5 py-0.5 text-xs font-medium whitespace-nowrap shadow-sm"
                        title="Duration"
                      >
                        <Clock className="text-muted size-3 shrink-0" />
                        <span>{durationMs !== null ? formatDurationMs(durationMs) : '--'}</span>
                      </div>
                    </>
                  ) : null}
                  <div className="flex items-center justify-center">
                    {isRunEventGroup ? (
                      <div className="type-label-mono text-xs uppercase">Run</div>
                    ) : group.lastStage !== 'system' ? (
                      <StageChip stage={group.lastStage} />
                    ) : null}
                  </div>
                  <div className="min-w-0">
                    <div
                      className="text-secondary truncate text-xs"
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
                        <span className="type-caption text-xs opacity-25">--</span>
                      )}
                    </div>
                  ) : null}
                  <div className="flex items-center justify-end gap-1.5 pr-2">
                    <span className="text-muted font-mono text-xs uppercase">
                      {live && groups.length > 0 && group.key === groups[groups.length - 1].key ? (
                        <span className="text-accent flex items-center gap-1.5 font-semibold">
                          <span className="relative flex size-1.5">
                            <span className="bg-accent absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"></span>
                            <span className="bg-accent relative inline-flex size-1.5 rounded-full"></span>
                          </span>
                          Active
                        </span>
                      ) : expanded ? (
                        'Less'
                      ) : (
                        'More'
                      )}
                    </span>
                    {!(
                      live &&
                      groups.length > 0 &&
                      group.key === groups[groups.length - 1].key
                    ) && (
                      <ChevronDown
                        className={cn(
                          'text-muted size-3.5 transition-transform duration-200',
                          expanded && 'rotate-180',
                        )}
                      />
                    )}
                  </div>
                </div>

                {expanded ? (
                  <div className="bg-[color-mix(in_srgb,var(--bg-alt)_60%,transparent)]">
                    <div className="overflow-hidden">
                      {expandedRows.length ? (
                        expandedRows.map((row, expandedIndex) => {
                          const IconComponent = getLogIcon(row.level, row.message);
                          const iconStyle = getLogIconStyle(row.level, row.message);
                          return (
                            <div
                              key={row.key}
                              className={cn(
                                'grid grid-cols-[64px_24px_105px_minmax(0,1fr)_auto] items-center gap-4 px-6 py-0.5 text-xs',
                                expandedIndex % 2 === 0
                                  ? 'bg-[color-mix(in_srgb,var(--bg-alt)_35%,transparent)]'
                                  : 'bg-transparent',
                              )}
                            >
                              <span className="text-muted font-mono text-xs font-normal tabular-nums">
                                {row.createdAt ? formatTimeHms(row.createdAt) : '--'}
                              </span>
                              <div className="flex justify-center">
                                <IconComponent className={cn('size-3.5', iconStyle.iconCls)} />
                              </div>
                              <div className="flex">
                                <StageChip stage={row.stage} showIcon={false} />
                              </div>
                              <span className="text-secondary min-w-0 text-xs font-medium break-words">
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
          <div className="px-6 py-8 text-center text-xs italic opacity-55">
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
                <div className="text-accent type-label-mono">{TERMINAL_STRINGS.PAYLOAD_PEEK}</div>
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
                    <span aria-hidden="true">{syntaxHighlightJsonNodes(peekedRecordJson)}</span>
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
