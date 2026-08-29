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
  RefreshCw,
  XCircle,
} from 'lucide-react';
import React, { memo, useEffect, useRef } from 'react';
import type { RefObject } from 'react';

import type { CrawlRecord, RunEvent } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { formatDurationMs, formatTimeHms } from '../../lib/crawl/format';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import { scrollViewportToBottom } from '../../lib/crawl/scroll';
import { syntaxHighlightJsonNodes } from '../../lib/ui/syntax';
import { Button } from '../ui/primitives';
import { siteDomId, STAGE_CONFIG, TERMINAL_STRINGS } from './run-event-terminal-utils';
import type { RunEventGroupStage, RunEventSiteGroup } from './run-event-terminal-utils';
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
} from './run-event-terminal-display';

import { useRunEventTerminalState } from './use-run-event-terminal-state';

function useRunEventViewport(_eventCount: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const targetRef = ref ?? internalRef;

  useEffect(() => {
    if (!ref) {
      scrollViewportToBottom(internalRef);
    }
  }, [_eventCount, ref]);

  return targetRef;
}
type RunEventIconStyle = { iconCls: string; bgCls: string };

function getRunEventIcon(event: RunEvent | null, stage: RunEventGroupStage) {
  if (!event) return Database;
  if (event.severity === 'error') return XCircle;
  if (event.severity === 'warning') return AlertTriangle;
  if (event.kind.startsWith('browser_retry.')) return RefreshCw;
  if (stage === 'acquisition') return Globe;
  if (stage === 'extraction') return Database;
  if (stage === 'normalization') return Layers;
  if (stage === 'persistence') return HardDrive;
  return event.kind.startsWith('run.') ? Activity : Dot;
}

function getRunEventIconStyle(event: RunEvent | null): RunEventIconStyle {
  if (!event) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (event.severity === 'error') return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (event.severity === 'warning') return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (event.outcome === 'succeeded') return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (event.stage === 'acquisition') return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  return {
    iconCls: 'text-secondary',
    bgCls: 'bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)]',
  };
}

function StageChip({ stage, showIcon = true }: { stage: RunEventGroupStage; showIcon?: boolean }) {
  const config = STAGE_CONFIG[stage];
  let Icon = Activity;
  if (stage === 'acquisition') Icon = Globe;
  if (stage === 'extraction') Icon = Database;
  if (stage === 'normalization') Icon = Layers;
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

function renderRunEventContent(summary: string, event: RunEvent | null): React.ReactNode {
  return event?.url ? (
    <>
      {summary} · <ShortenedUrl url={event.url} />
    </>
  ) : (
    summary
  );
}

function GroupIdentity({ group, runEvent }: { group: RunEventSiteGroup; runEvent: boolean }) {
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
  group: RunEventSiteGroup;
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
  group: RunEventSiteGroup;
  expanded: boolean;
  active: boolean;
  onToggle: () => void;
}) {
  const label = active ? 'Active' : expanded ? 'Less' : 'More';
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-label={`${expanded ? 'Collapse' : 'Expand'} events for ${group.url || group.label}`}
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
  group: RunEventSiteGroup;
  coverage: ReturnType<typeof groupFieldCoverage>;
  confidence: ReturnType<typeof groupConfidence>;
  durationMs: number | null;
  onPeek: () => void;
}) {
  const rows = buildExpandedRows(group, coverage, confidence, durationMs);
  if (!rows.length)
    return <div className="px-3 py-2 text-base opacity-40">{TERMINAL_STRINGS.NO_EVENTS}</div>;
  return rows.map((row, index) => {
    const IconComponent = getRunEventIcon(row.event, row.stage);
    const iconStyle = getRunEventIconStyle(row.event);
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
          {renderRunEventContent(row.summary, row.event)}
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
  group: RunEventSiteGroup,
  storedOrdinal: number | undefined,
  stableIndex: number,
) {
  return group.index ?? storedOrdinal ?? stableIndex + 1;
}

function displayedGroupDuration(
  group: RunEventSiteGroup,
  active: boolean,
  terminalNowMs: number,
  inferredEndMs: number | undefined,
) {
  return groupDurationMs(group, active ? terminalNowMs : inferredEndMs);
}

export const RunEventTerminal = memo(function RunEventTerminal({
  events,
  records = [],
  requestedFields = [],
  live = false,
  viewportRef,
  nowMs,
}: Readonly<{
  events: RunEvent[];
  records?: CrawlRecord[];
  requestedFields?: string[];
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
  nowMs?: number;
}>) {
  const ref = useRunEventViewport(events.length, viewportRef);
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
  } = useRunEventTerminalState({ events, records, live, nowMs });

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
            activity_stream.events
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
              const lastEvent = group.events.at(-1);
              const recentEvents = [...group.events].reverse();
              const summaryEvent =
                recentEvents.find((event) => event.severity !== 'info') ??
                recentEvents.find((event) => event.stage !== 'persistence') ??
                lastEvent;
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
                        title={summaryEvent?.kind || ''}
                      >
                        {groupSummaryMessage(group, coverage, summaryEvent)}
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
            {live ? 'Waiting for Run Events...' : 'No Run Events recorded'}
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
