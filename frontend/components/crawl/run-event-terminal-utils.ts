import type { CrawlRecord, RunEvent, RunEventStage } from '../../lib/api/types';

export type RunEventGroupStage = Exclude<RunEventStage, null> | 'system';

export interface RunEventStageConfig {
  label: string;
  textClass: string;
}

export const STAGE_CONFIG: Record<RunEventGroupStage, RunEventStageConfig> = {
  acquisition: { label: 'Acquire', textClass: 'text-info-text' },
  extraction: { label: 'Extract', textClass: 'text-accent-text' },
  normalization: { label: 'Normalize', textClass: 'text-warning-text' },
  persistence: { label: 'Persist', textClass: 'text-success-text' },
  system: { label: 'Run', textClass: 'text-muted' },
};

export const TERMINAL_STRINGS = {
  FIELDS: 'Fields',
  CONFIDENCE: 'Confidence',
  TIME: 'Time',
  RUN_EVENTS: 'Run Events',
  PENDING: 'Pending…',
  SITE_PAYLOAD: 'Site payload',
  PAYLOAD_PEEK: 'Payload Peek',
  NO_EVENTS: 'No Run Events.',
  NO_PAYLOAD: 'No persisted payload for this site yet.',
} as const;

export type RunEventSiteGroup = {
  key: string;
  label: string;
  url: string;
  index: number | null;
  total: number | null;
  events: RunEvent[];
  stageEvents: Record<RunEventGroupStage, RunEvent[]>;
  records: CrawlRecord[];
  hasError: boolean;
  hasWarning: boolean;
  lastStage: RunEventGroupStage;
  recordCount: number;
};

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
    if (text) candidates.add(text);
  }
  if (candidates.has(siteUrl)) return true;
  const normalizedSiteUrl = canonicalEventMatchUrl(siteUrl);
  return Array.from(candidates).some(
    (candidate) =>
      canonicalEventMatchUrl(candidate) === normalizedSiteUrl ||
      hasSameStablePathIdentity(candidate, siteUrl),
  );
}

function canonicalEventMatchUrl(value: string) {
  try {
    const parsed = new URL(value);
    parsed.hash = '';
    parsed.search = '';
    parsed.pathname = parsed.pathname.replace(/\/+$/, '') || '/';
    return parsed.toString();
  } catch {
    return value.trim();
  }
}

function hasSameStablePathIdentity(left: string, right: string) {
  try {
    const leftUrl = new URL(left);
    const rightUrl = new URL(right);
    const leftHost = leftUrl.hostname.replace(/^www\./, '').toLowerCase();
    const rightHost = rightUrl.hostname.replace(/^www\./, '').toLowerCase();
    if (leftHost !== rightHost) return false;
    const lastSegment = (url: URL) =>
      decodeURIComponent(url.pathname).split('/').filter(Boolean).at(-1)?.trim().toLowerCase() ??
      '';
    const leftId = lastSegment(leftUrl);
    const rightId = lastSegment(rightUrl);
    return leftId.length >= 5 && rightId.length >= 5 && /\d/.test(leftId) && leftId === rightId;
  } catch {
    return false;
  }
}

function scopeNumber(event: RunEvent, key: 'index' | 'total') {
  const value = event.facts[key];
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null;
}

function siteLabel(url: string, index: number | null, total: number | null) {
  if (index && total) return `${index}/${total} ${url}`;
  return index ? `${index} ${url}` : url;
}

export function siteDomId(groupKey: string) {
  return `site-run-event-${groupKey.replace(/[^a-z0-9_-]+/gi, '-')}`;
}

function emptyStageEvents(): Record<RunEventGroupStage, RunEvent[]> {
  return { acquisition: [], extraction: [], normalization: [], persistence: [], system: [] };
}

function groupStage(event: RunEvent): RunEventGroupStage {
  return event.stage ?? 'system';
}

function groupKey(event: RunEvent) {
  if (event.url_scope_id) return `scope:${event.url_scope_id}`;
  return 'run';
}

function createGroup(
  event: RunEvent,
): Omit<RunEventSiteGroup, 'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'> {
  const url = event.url ?? '';
  const index = scopeNumber(event, 'index');
  const total = scopeNumber(event, 'total');
  return {
    key: groupKey(event),
    label: url ? siteLabel(url, index, total) : TERMINAL_STRINGS.RUN_EVENTS,
    url,
    index,
    total,
    events: [],
    stageEvents: emptyStageEvents(),
  };
}

function appendEvent(
  group: Omit<
    RunEventSiteGroup,
    'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'
  >,
  event: RunEvent,
) {
  group.events.push(event);
  group.stageEvents[groupStage(event)].push(event);
}

function finalizeGroup(
  group: Omit<
    RunEventSiteGroup,
    'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'
  >,
  records: CrawlRecord[],
): RunEventSiteGroup {
  const matchedRecords = group.url
    ? records.filter((record) => matchesSiteUrl(record, group.url))
    : [];
  const hasError = group.events.some((event) => event.severity === 'error');
  const hasWarning = !hasError && group.events.some((event) => event.severity === 'warning');
  const lastEvent = group.events.at(-1);
  const lastStage = lastEvent ? groupStage(lastEvent) : 'system';
  return {
    ...group,
    records: matchedRecords,
    hasError,
    hasWarning,
    lastStage,
    recordCount: matchedRecords.length,
  };
}

export function buildRunEventSiteGroups(
  events: RunEvent[],
  records: CrawlRecord[] = [],
): RunEventSiteGroup[] {
  const groups = new Map<
    string,
    Omit<RunEventSiteGroup, 'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'>
  >();
  for (const event of events) {
    const key = groupKey(event);
    let group = groups.get(key);
    if (!group) {
      group = createGroup(event);
      groups.set(key, group);
    }
    appendEvent(group, event);
  }
  return Array.from(groups.values()).map((group) => finalizeGroup(group, records));
}

export const RUN_EVENT_GROUP_WINDOW_SIZE = 50;

export function windowRunEventGroups<T>(
  groups: T[],
  visibleCount: number,
): { visible: T[]; hiddenCount: number } {
  if (groups.length <= visibleCount) return { visible: groups, hiddenCount: 0 };
  return {
    visible: groups.slice(groups.length - visibleCount),
    hiddenCount: groups.length - visibleCount,
  };
}
