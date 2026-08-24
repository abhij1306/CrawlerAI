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
import React, { memo, useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type { LucideIcon } from 'lucide-react';

import type { CrawlLog, CrawlRecord } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { formatDurationMs, formatTimeHms } from '../../lib/crawl/format';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import { scrollViewportToBottom } from '../../lib/crawl/scroll';
import { syntaxHighlightJsonNodes } from '../../lib/ui/syntax';
import { Button } from '../ui/primitives';
import {
  isPersistenceSummaryLog,
  LOG_PATTERNS,
  logMessageIsError,
  sanitizeLogMessage,
  siteDomId,
  STAGE_CONFIG,
  TERMINAL_STRINGS,
} from './log-terminal-utils';
import type { LogSiteGroup, LogStage } from './log-terminal-utils';
import {
  buildExpandedRows,
  formatShortUrlLabel,
  groupConfidence,
  groupDurationMs,
  groupFieldCoverage,
  groupSummaryMessage,
  normalizeConfidenceScore,
  payloadSnapshot,
  severityTone,
  toneForConfidence,
} from './log-terminal-display';

import { useLogTerminalState } from './use-log-terminal-state';

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
type LogIconStyle = { iconCls: string; bgCls: string };

type LogIconRule = { terms: readonly string[]; icon: LucideIcon; style: LogIconStyle };

function includesAny(message: string, terms: readonly string[]) {
  return terms.some((term) => message.includes(term));
}

const LOG_ICON_RULES: readonly LogIconRule[] = [
  {
    terms: ['starting crawl'],
    icon: Activity,
    style: { iconCls: 'text-info', bgCls: 'bg-info-bg' },
  },
  {
    terms: ['ignoring robots.txt'],
    icon: ShieldAlert,
    style: { iconCls: 'text-warning', bgCls: 'bg-warning-bg' },
  },
  {
    terms: ['resolved'],
    icon: CheckCircle2,
    style: { iconCls: 'text-muted ', bgCls: 'bg-zinc-500/10' },
  },
  { terms: ['acquired'], icon: Globe, style: { iconCls: 'text-info', bgCls: 'bg-info-bg' } },
  {
    terms: ['extracted'],
    icon: Database,
    style: { iconCls: 'text-success', bgCls: 'bg-success-bg' },
  },
  {
    terms: ['normalized', 'normalised'],
    icon: Layers,
    style: { iconCls: 'text-warning', bgCls: 'bg-warning-bg' },
  },
  {
    terms: ['persisted'],
    icon: HardDrive,
    style: { iconCls: 'text-success', bgCls: 'bg-success-bg' },
  },
  {
    terms: ['page loaded', 'page load'],
    icon: Zap,
    style: { iconCls: 'text-warning', bgCls: 'bg-warning-bg' },
  },
  {
    terms: ['challenge', 'blocked', 'captcha', 'bot check'],
    icon: ShieldAlert,
    style: { iconCls: 'text-danger', bgCls: 'bg-danger-bg' },
  },
  {
    terms: ['acquiring', 'fetching'],
    icon: Globe,
    style: { iconCls: 'text-info', bgCls: 'bg-info-bg' },
  },
  {
    terms: ['browser', 'patchright', 'playwright', 'headless'],
    icon: Monitor,
    style: { iconCls: 'text-info', bgCls: 'bg-info-bg' },
  },
  { terms: ['record'], icon: Database, style: { iconCls: 'text-success', bgCls: 'bg-success-bg' } },
];

const LOG_ICON_STYLE_RULES: ReadonlyArray<{ terms: readonly string[]; style: LogIconStyle }> =
  LOG_ICON_RULES.map(({ terms, style }) => ({ terms, style }));

const LOG_ICON_FINAL_RULES: readonly LogIconRule[] = [
  {
    terms: ['retry', 'retrying', 'refresh'],
    icon: RefreshCw,
    style: { iconCls: 'text-info', bgCls: 'bg-info-bg' },
  },
  {
    terms: ['complete', 'success', 'done', 'finished'],
    icon: CheckCircle2,
    style: { iconCls: 'text-success', bgCls: 'bg-success-bg' },
  },
];

const LOG_ICON_STYLE_FINAL_RULES: ReadonlyArray<{ terms: readonly string[]; style: LogIconStyle }> =
  LOG_ICON_FINAL_RULES.map(({ terms, style }) => ({ terms, style }));

function getLogIcon(level: string, message: string) {
  const msg = message.toLowerCase();
  if (logMessageIsError(level, message)) return XCircle;
  if (level === 'warning' || level === 'warn') return AlertTriangle;
  const matched = LOG_ICON_RULES.find((rule) => includesAny(msg, rule.terms));
  if (matched) return matched.icon;
  if (/https?:\/\//i.test(message)) return Globe;
  return LOG_ICON_FINAL_RULES.find((rule) => includesAny(msg, rule.terms))?.icon ?? Dot;
}

function getLogIconStyle(level: string, message: string): LogIconStyle {
  const msg = message.toLowerCase();
  if (logMessageIsError(level, message)) return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (level === 'warning' || level === 'warn')
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  const matched = LOG_ICON_STYLE_RULES.find((rule) => includesAny(msg, rule.terms));
  if (matched) return matched.style;
  if (/https?:\/\//i.test(message)) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  const finalMatch = LOG_ICON_STYLE_FINAL_RULES.find((rule) => includesAny(msg, rule.terms));
  if (finalMatch) return finalMatch.style;
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
        'inline-flex items-center gap-1 font-medium uppercase',
        // Exactly one font-size class per stage: twMerge doesn't know text-base,
        // so a base size + override would both survive the merge.
        stage === 'system' ? 'font-mono text-base tracking-[0.1em]' : 'text-base tracking-wide',
        config.textClass,
      )}
    >
      {showIcon ? <Icon className="size-3" /> : null}
      <span>{config.label}</span>
    </span>
  );
}

function ShortenedUrl({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-info underline decoration-info/20 underline-offset-4 transition-colors hover:text-accent"
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

function GroupIdentity({ group, runEvent }: { group: LogSiteGroup; runEvent: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      {!runEvent ? <Globe className="size-3.5 shrink-0 text-muted" /> : null}
      {runEvent ? (
        <span className="block truncate text-base font-medium text-secondary" title={group.label}>
          {group.label}
        </span>
      ) : (
        <a
          href={group.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
          className="block truncate text-base font-normal text-info-text underline-offset-4 hover:underline"
          title={group.url}
        >
          {formatShortUrlLabel(group.url)}
        </a>
      )}
    </div>
  );
}

function GroupMetrics({
  group,
  coverage,
  confidence,
  durationMs,
}: {
  group: LogSiteGroup;
  coverage: ReturnType<typeof groupFieldCoverage>;
  confidence: ReturnType<typeof groupConfidence>;
  durationMs: number | null;
}) {
  const confidenceTone = confidence ? toneForConfidence(confidence.level) : 'text-muted';
  return (
    <>
      <div
        className="flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-base font-medium whitespace-nowrap text-secondary tabular-nums"
        title="Fields Extracted"
      >
        <Database className="size-3 shrink-0 text-muted" />
        <span>
          {group.records.length ? `${coverage.foundCount}/${coverage.totalCount || 0}` : '--'}
        </span>
      </div>
      <div
        className="flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-base font-medium whitespace-nowrap text-secondary tabular-nums"
        title="Confidence Score"
      >
        <CheckCircle2 className={cn('size-3 shrink-0', confidenceTone)} />
        <span className={confidenceTone}>
          {confidence ? `${Math.round(normalizeConfidenceScore(confidence.score) * 100)}%` : '--'}
        </span>
      </div>
      <div
        className="flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-base font-medium whitespace-nowrap text-secondary tabular-nums"
        title="Duration"
      >
        <Clock className="size-3 shrink-0 text-muted" />
        <span>{durationMs !== null ? formatDurationMs(durationMs) : '--'}</span>
      </div>
    </>
  );
}

function GroupToggle({
  group,
  expanded,
  active,
  onToggle,
}: {
  group: LogSiteGroup;
  expanded: boolean;
  active: boolean;
  onToggle: () => void;
}) {
  const label = active ? 'Active' : expanded ? 'Less' : 'More';
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-label={`${expanded ? 'Collapse' : 'Expand'} logs for ${group.url || group.label}`}
      disabled={active}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      className="flex items-center justify-end gap-1.5 pr-2 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:cursor-default"
    >
      <span
        className={cn(
          'font-mono text-sm text-muted uppercase',
          active && 'flex items-center gap-1.5 font-semibold text-accent',
        )}
      >
        {active ? (
          <span className="relative flex size-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex size-1.5 rounded-full bg-accent" />
          </span>
        ) : null}
        {label}
      </span>
      {!active ? (
        <ChevronDown
          className={cn(
            'text-muted size-3.5 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        />
      ) : null}
    </button>
  );
}

function ExpandedGroupRows({
  group,
  coverage,
  confidence,
  durationMs,
  onPeek,
}: {
  group: LogSiteGroup;
  coverage: ReturnType<typeof groupFieldCoverage>;
  confidence: ReturnType<typeof groupConfidence>;
  durationMs: number | null;
  onPeek: () => void;
}) {
  const rows = buildExpandedRows(group, coverage, confidence, durationMs);
  if (!rows.length)
    return <div className="px-3 py-2 text-base opacity-40">{TERMINAL_STRINGS.NO_LOGS}</div>;
  return rows.map((row, index) => {
    const IconComponent = getLogIcon(row.level, row.message);
    const iconStyle = getLogIconStyle(row.level, row.message);
    return (
      <div
        key={row.key}
        className={cn(
          'grid grid-cols-[64px_24px_105px_minmax(0,1fr)_auto] items-center gap-4 px-6 py-0.5 text-base',
          index % 2 === 0
            ? 'bg-[color-mix(in_srgb,var(--bg-alt)_35%,transparent)]'
            : 'bg-transparent',
        )}
      >
        <span className="font-mono text-base font-normal text-muted tabular-nums">
          {row.createdAt ? formatTimeHms(row.createdAt) : '--'}
        </span>
        <div className="flex justify-center">
          <IconComponent className={cn('size-3.5', iconStyle.iconCls)} />
        </div>
        <div className="flex">
          <StageChip stage={row.stage} showIcon={false} />
        </div>
        <span className="min-w-0 text-base font-medium break-words text-secondary">
          {row.createdAt ? renderLogContent(row.message, row.stage === 'system') : row.message}
        </span>
        <span className="flex items-center gap-2">
          {row.payloadAction ? (
            <Button type="button" variant="quiet" size="sm" onClick={onPeek}>
              Peek payload
            </Button>
          ) : null}
        </span>
      </div>
    );
  });
}

function terminalAriaLive(live: boolean) {
  return live ? ('polite' as const) : ('off' as const);
}

function displayedGroupOrdinal(
  group: LogSiteGroup,
  storedOrdinal: number | undefined,
  stableIndex: number,
) {
  return group.index ?? storedOrdinal ?? stableIndex + 1;
}

function displayedGroupDuration(
  group: LogSiteGroup,
  active: boolean,
  terminalNowMs: number,
  inferredEndMs: number | undefined,
) {
  return groupDurationMs(group, active ? terminalNowMs : inferredEndMs);
}

export const LogTerminal = memo(function LogTerminal({
  logs,
  records = [],
  requestedFields = [],
  live = false,
  viewportRef,
  nowMs,
}: Readonly<{
  logs: CrawlLog[];
  records?: CrawlRecord[];
  requestedFields?: string[];
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
  nowMs?: number;
}>) {
  const ref = useLogViewport(logs.length, viewportRef);
  const {
    activeGroupKey,
    activeGroupKeys,
    activePeekedGroupKey,
    expandedGroupKey,
    groupIndexByKey,
    groups,
    hiddenGroupCount,
    inferredSerialEndMsByKey,
    jumpToGroup,
    navigateTriage,
    nowMs: terminalNowMs,
    peekedGroup,
    peekedRecordJson,
    peekPanelRef,
    safePeekedRecordIndex,
    setPeekedGroupKey,
    setPeekedRecordIndex,
    showEarlierGroups,
    siteOrdinalByKey,
    timelineTicks,
    toggleGroup,
    visibleGroups,
  } = useLogTerminalState({ logs, records, live, nowMs });

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
          <span className="type-label-mono text-sm tracking-[0.25em] uppercase">
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
            <span className="h-3 w-px bg-muted opacity-20" />
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
        aria-live={terminalAriaLive(live)}
        aria-atomic="false"
      >
        {groups.length ? (
          <>
            {hiddenGroupCount > 0 ? (
              <div className="surface-muted type-body m-2 flex items-center justify-between rounded-md px-6 py-2 text-muted">
                <span>
                  Showing the latest {visibleGroups.length} of {groups.length} groups
                </span>
                <Button variant="neutral" type="button" onClick={showEarlierGroups}>
                  Show earlier groups
                </Button>
              </div>
            ) : null}
            {visibleGroups.map((group, index) => {
              // Stable across window slides; `index` is window-relative and shifts.
              const stableGroupIndex = groupIndexByKey.get(group.key) ?? index;
              const expanded = expandedGroupKey === group.key || group.key === activeGroupKey;
              const isRunEventGroup = !group.url;
              const payload = payloadSnapshot(group);
              const coverage = groupFieldCoverage(group, requestedFields);
              const confidence = groupConfidence(group);
              const activeGroup = activeGroupKeys.has(group.key);
              const durationMs = displayedGroupDuration(
                group,
                activeGroup,
                terminalNowMs,
                inferredSerialEndMsByKey.get(group.key),
              );
              const lastLog = group.logs.at(-1);
              const summaryLog =
                [...group.logs].reverse().find((log) => !isPersistenceSummaryLog(log.message)) ??
                lastLog;
              return (
                <section key={group.key} id={siteDomId(group.key)} className="overflow-hidden">
                  <div
                    className={cn(
                      'group/row font-inherit grid w-full items-center gap-3 border-none bg-transparent px-6 py-2 text-left text-base text-inherit transition-colors',
                      isRunEventGroup
                        ? 'grid-cols-[32px_minmax(280px,1fr)_auto_minmax(260px,1.4fr)_60px]'
                        : 'grid-cols-[32px_minmax(280px,2fr)_75px_80px_85px_auto_minmax(200px,1.2fr)_80px_70px]',
                      severityTone(group, stableGroupIndex),
                    )}
                  >
                    <div className="font-mono text-base text-muted">
                      {displayedGroupOrdinal(
                        group,
                        siteOrdinalByKey.get(group.key),
                        stableGroupIndex,
                      )
                        .toString()
                        .padStart(2, '0')}
                    </div>
                    <GroupIdentity group={group} runEvent={isRunEventGroup} />
                    {!isRunEventGroup ? (
                      <GroupMetrics
                        group={group}
                        coverage={coverage}
                        confidence={confidence}
                        durationMs={durationMs}
                      />
                    ) : null}
                    <div className="flex items-center justify-center">
                      {isRunEventGroup ? (
                        <div className="type-label-mono text-sm uppercase">Run</div>
                      ) : group.lastStage !== 'system' ? (
                        <StageChip stage={group.lastStage} />
                      ) : null}
                    </div>
                    <div className="min-w-0">
                      <div
                        className="truncate text-base text-secondary"
                        title={summaryLog?.message || ''}
                      >
                        {groupSummaryMessage(group, coverage, summaryLog)}
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
                          <span className="type-caption text-base opacity-25">--</span>
                        )}
                      </div>
                    ) : null}
                    <GroupToggle
                      group={group}
                      expanded={expanded}
                      active={group.key === activeGroupKey}
                      onToggle={() => toggleGroup(group.key)}
                    />
                  </div>

                  {expanded ? (
                    <div className="bg-[color-mix(in_srgb,var(--bg-alt)_60%,transparent)]">
                      <div className="overflow-hidden">
                        <ExpandedGroupRows
                          group={group}
                          coverage={coverage}
                          confidence={confidence}
                          durationMs={durationMs}
                          onPeek={() => {
                            setPeekedGroupKey(group.key);
                            setPeekedRecordIndex(0);
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                </section>
              );
            })}
          </>
        ) : (
          <div className="px-6 py-8 text-center text-base italic opacity-55">
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
                <div className="type-label-mono text-accent">{TERMINAL_STRINGS.PAYLOAD_PEEK}</div>
                <div
                  className="mt-0.5 truncate pr-4 text-base font-medium tabular-nums"
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
