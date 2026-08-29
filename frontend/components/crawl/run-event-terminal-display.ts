import type { CrawlRecord, RunEvent } from '../../lib/api/types';
import {
  formatDurationMs,
  humanizeFieldName,
  normalizeField,
  parseApiDate,
} from '../../lib/crawl/format';
import { uniqueRequestedFields } from '../../lib/crawl/fields';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import { isInformativeValue, qualityLevelFromScore } from '../../lib/crawl/quality';
import { TERMINAL_STRINGS } from './run-event-terminal-utils';
import type { RunEventGroupStage, RunEventSiteGroup } from './run-event-terminal-utils';

export function severityTone(group: RunEventSiteGroup, index: number) {
  if (group.hasError) return 'bg-transparent border-l-2 border-l-danger';
  if (group.hasWarning) return 'bg-transparent border-l-2 border-l-warning';
  if (group.recordCount > 0 || group.stageEvents.persistence.length > 0) {
    return 'bg-transparent border-l-2 border-l-success';
  }
  return index % 2 === 0
    ? 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]'
    : 'bg-transparent';
}

export function payloadSnapshot(group: RunEventSiteGroup) {
  if (!group.records.length) return '';
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

export function normalizeConfidenceScore(score: number) {
  if (!Number.isFinite(score)) return 0;
  if (score > 1 && score <= 100) return score / 100;
  return Math.max(0, Math.min(score, 1));
}

function recordConfidence(record: CrawlRecord): { score: number; level: string } | null {
  const rawConfidence =
    (record.raw_data && typeof record.raw_data === 'object'
      ? (record.raw_data as Record<string, unknown>)._confidence
      : null) ||
    (record.discovered_data && typeof record.discovered_data === 'object'
      ? (record.discovered_data as Record<string, unknown>).confidence
      : null);
  if (!rawConfidence || typeof rawConfidence !== 'object') return null;
  const payload = rawConfidence as Record<string, unknown>;
  const score = Number(payload.score);
  if (!Number.isFinite(score)) return null;
  const normalizedScore = normalizeConfidenceScore(score);
  return {
    score: normalizedScore,
    level:
      String(payload.level || qualityLevelFromScore(normalizedScore))
        .trim()
        .toLowerCase() || 'unknown',
  };
}

export function groupConfidence(group: RunEventSiteGroup): { score: number; level: string } | null {
  const scores = group.records
    .map(recordConfidence)
    .filter((value): value is { score: number; level: string } => value !== null);
  if (!scores.length) return null;
  const average = scores.reduce((total, item) => total + item.score, 0) / scores.length;
  return { score: average, level: String(qualityLevelFromScore(average)) };
}

function numberOrNull(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function groupDurationMs(group: RunEventSiteGroup, activeNowMs?: number): number | null {
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
  const startedAt = group.events[0]?.created_at;
  if (!startedAt) return null;
  const startedMs = parseApiDate(startedAt).getTime();
  if (!Number.isFinite(startedMs)) return null;
  const lastEvent = group.events.at(-1);
  const endCandidatesMs = [
    activeNowMs,
    lastEvent?.created_at ? parseApiDate(lastEvent.created_at).getTime() : null,
    ...group.records.map((record) => parseApiDate(record.created_at).getTime()),
    ...recordDurations.map((durationMs) => startedMs + durationMs),
  ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!endCandidatesMs.length) return null;
  return Math.max(0, Math.max(...endCandidatesMs) - startedMs);
}

export function groupFieldCoverage(group: RunEventSiteGroup, requestedFields: string[]) {
  const requested = uniqueRequestedFields(requestedFields);
  const normalizedRequested = requested.map(normalizeField);
  const foundNormalized = new Set<string>();
  const foundOriginal = new Map<string, string>();

  for (const record of group.records) {
    for (const field of publicFieldNames(record)) {
      const normalized = normalizeField(field);
      foundNormalized.add(normalized);
      if (!foundOriginal.has(normalized)) foundOriginal.set(normalized, field);
    }
  }

  if (requested.length) {
    const labels = requested.filter(
      (field, index) =>
        foundNormalized.has(normalizedRequested[index]) || foundNormalized.has(field),
    );
    return { foundCount: labels.length, totalCount: requested.length, labels };
  }

  const labels = Array.from(foundOriginal.values());
  return { foundCount: labels.length, totalCount: labels.length, labels };
}

export function toneForConfidence(level: string) {
  if (level === 'high') return 'text-success';
  if (level === 'medium') return 'text-warning';
  if (level === 'low') return 'text-danger';
  return 'text-muted';
}

type ExpandedRunEventRow = {
  key: string;
  stage: RunEventGroupStage;
  event: RunEvent | null;
  summary: string;
  createdAt?: string | null;
  payloadAction?: boolean;
};

export function isVisibleRunEvent(event: RunEvent) {
  return event.kind !== 'acquisition.started';
}

export function buildExpandedRows(
  group: RunEventSiteGroup,
  coverage: ReturnType<typeof groupFieldCoverage>,
  confidence: ReturnType<typeof groupConfidence>,
  durationMs: number | null,
): ExpandedRunEventRow[] {
  const rows: ExpandedRunEventRow[] = group.events.filter(isVisibleRunEvent).map((event) => ({
    key: `event-${event.sequence}`,
    stage: event.stage ?? 'system',
    event,
    summary: runEventSummary(event),
    createdAt: event.created_at,
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
      parts.push(
        `${TERMINAL_STRINGS.CONFIDENCE} ${Math.round(normalizeConfidenceScore(confidence.score) * 100)}%`,
      );
    }
    if (durationMs !== null) parts.push(`${TERMINAL_STRINGS.TIME} ${formatDurationMs(durationMs)}`);
    rows.push({
      key: `${group.key}-fields`,
      stage: 'persistence',
      event: null,
      summary: parts.join(' | '),
      payloadAction: group.records.length > 0,
    });
  }

  return rows;
}

export function groupSummaryMessage(
  group: RunEventSiteGroup,
  coverage: ReturnType<typeof groupFieldCoverage>,
  fallbackEvent?: RunEvent,
) {
  if (group.records.length > 0) {
    const noun = group.records.length === 1 ? 'record' : 'records';
    return `Extracted ${group.records.length} ${noun}; fields ${coverage.foundCount}/${coverage.totalCount || 0}`;
  }
  if (group.hasError || group.hasWarning)
    return fallbackEvent ? runEventSummary(fallbackEvent) : 'No public record extracted';
  const persistenceEvent = group.stageEvents.persistence.at(-1);
  if (persistenceEvent) return runEventSummary(persistenceEvent);
  if (fallbackEvent?.kind === 'url.started' || fallbackEvent?.kind === 'acquisition.started') {
    return 'In progress…';
  }
  return fallbackEvent ? runEventSummary(fallbackEvent) : TERMINAL_STRINGS.PENDING;
}

function readableWords(value: unknown) {
  const text = String(value ?? '')
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

function countLabel(value: unknown, singular: string) {
  const count = Number(value);
  if (!Number.isFinite(count)) return null;
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

function conciseStrategy(event: RunEvent) {
  const facts = event.facts;
  const details = [
    readableWords(facts.fetch_mode),
    facts.browser_first === true ? 'Browser first' : null,
    facts.prefer_browser === true && facts.browser_first !== true ? 'Browser preferred' : null,
    typeof facts.primary_http_fetcher === 'string' ? facts.primary_http_fetcher : null,
    typeof facts.http_timeout_seconds === 'number'
      ? `${facts.http_timeout_seconds}s timeout`
      : null,
    facts.host_preference_enabled === true ? 'Host preference enabled' : null,
  ].filter((value): value is string => Boolean(value));
  return `Strategy selected${details.length ? `: ${details.join(' · ')}` : ''}`;
}

function conciseHttpAttempt(event: RunEvent) {
  const facts = event.facts;
  const details = [
    facts.fetcher,
    facts.proxy_mode ? `${readableWords(facts.proxy_mode)} proxy` : null,
    typeof facts.timeout_seconds === 'number' ? `${facts.timeout_seconds}s timeout` : null,
  ].filter(Boolean);
  return `HTTP request${details.length ? `: ${details.join(' · ')}` : ''}`;
}

function conciseBrowserLaunch(event: RunEvent) {
  const facts = event.facts;
  const details = [facts.engine, facts.launch_mode, facts.profile, facts.proxy_mode]
    .filter((value): value is string => typeof value === 'string' && Boolean(value))
    .map(readableWords);
  return `Browser launched${details.length ? `: ${details.join(' · ')}` : ''}`;
}

function concisePageLoad(event: RunEvent) {
  const facts = event.facts;
  const elapsed = Number(facts.elapsed_ms);
  const details = [
    Number.isFinite(elapsed) ? `in ${formatDurationMs(elapsed)}` : null,
    facts.page_title ? String(facts.page_title) : null,
  ].filter(Boolean);
  return `Page loaded${details.length ? ` ${details.join(' · ')}` : ''}`;
}

function conciseRecordsPersisted(event: RunEvent) {
  const count = countLabel(event.facts.record_count, 'record');
  return count ? `Saved ${count}` : 'Records saved';
}

function conciseAcquisitionCompleted(event: RunEvent) {
  const facts = event.facts;
  const details = [
    facts.method ? readableWords(facts.method) : null,
    typeof facts.status_code === 'number' ? `status ${facts.status_code}` : null,
  ].filter(Boolean);
  return `HTTP completed${details.length ? `: ${details.join(' · ')}` : ''}`;
}

function conciseUrlCompleted(event: RunEvent) {
  const facts = event.facts;
  const details = [
    readableWords(facts.verdict ?? event.outcome),
    countLabel(facts.record_count, 'record'),
  ].filter(Boolean);
  return details.length ? `Result: ${details.join(' · ')}` : 'Result ready';
}

const CONCISE_EVENT_FORMATTERS: Record<string, (event: RunEvent) => string> = {
  'url.started': () => 'Processing started',
  'acquisition.strategy_selected': conciseStrategy,
  'acquisition.http_attempted': conciseHttpAttempt,
  'acquisition.browser_launched': conciseBrowserLaunch,
  'acquisition.browser_page_loaded': concisePageLoad,
  'acquisition.completed': conciseAcquisitionCompleted,
  'persistence.records_persisted': conciseRecordsPersisted,
  'url.completed': conciseUrlCompleted,
};

export function runEventSummary(event: RunEvent) {
  const formatter = CONCISE_EVENT_FORMATTERS[event.kind];
  if (formatter) return formatter(event);

  const kindParts = event.stage ? [event.kind.split('.').at(-1)] : event.kind.split('.');
  const label = kindParts.map(readableWords).join(' ');
  const details = Object.entries(event.facts).flatMap(([key, value]) => {
    if (value === null || value === '' || key === 'index' || key === 'total' || key === 'url')
      return [];
    return [
      `${readableWords(key)}: ${typeof value === 'boolean' ? (value ? 'yes' : 'no') : readableWords(value)}`,
    ];
  });
  if (event.reason_code) details.unshift(readableWords(event.reason_code));
  return details.length ? `${label}: ${details.join(' · ')}` : label;
}

export function formatShortUrlLabel(url: string) {
  try {
    const parsed = new URL(url);
    const domain = parsed.hostname.replace(/^www\./, '');
    const parts = parsed.pathname.split('/').filter(Boolean);
    const lastPart = parts.at(-1) || '';
    if (parts.length > 1) return `${domain}/.../${lastPart}`;
    return domain + (lastPart ? `/${lastPart}` : '');
  } catch {
    return url.length > 40 ? url.slice(0, 40) + '…' : url;
  }
}
