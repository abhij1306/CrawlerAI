import type { CrawlLog, CrawlRecord } from '../../lib/api/types';

export function logMessageIsError(level: string, message: string): boolean {
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
  textClass: string;
}

const DISPLAY_LOG_STAGES: LogStage[] = ['acquisition', 'extraction', 'normalize', 'persistence'];

/* Refined-minimal logs: stage = colored text, no filled chip (sample
   .log-stage — semantic *-text tokens; .stage-run is mono + subtle). */
export const STAGE_CONFIG: Record<LogStage, LogStageConfig> = {
  acquisition: {
    label: 'Acquire',
    textClass: 'text-info-text',
  },
  extraction: {
    label: 'Extract',
    textClass: 'text-accent-text',
  },
  normalize: {
    label: 'Normalize',
    textClass: 'text-warning-text',
  },
  persistence: {
    label: 'Persist',
    textClass: 'text-success-text',
  },
  system: {
    label: 'Run',
    textClass: 'text-subtle',
  },
};

export const TERMINAL_STRINGS = {
  FIELDS: 'Fields',
  CONFIDENCE: 'Confidence',
  TIME: 'Time',
  RUN_EVENTS: 'Run Events',
  PENDING: 'Pending…',
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
  URL_PREFIX: /^\[url:(https?:\/\/[^\s\]]+)\]\s*/i,
  FIRST_URL: /https?:\/\/[^\s]+/i,
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
  return 'system';
}

export type LogSiteGroup = {
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

export function sanitizeLogMessage(message: string) {
  return String(message || '')
    .replace(LOG_PATTERNS.URL_PREFIX, '')
    .replace(/\s*\[corr=[^\]]+\]/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export function parseStartingLog(message: string) {
  const match = LOG_PATTERNS.STARTING_CRAWL.exec(sanitizeLogMessage(message));
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

export function isPersistenceSummaryLog(message: string) {
  return LOG_PATTERNS.PERSISTENCE_SUMMARY.test(String(message || ''));
}

function isWarningLog(log: CrawlLog) {
  const level = String(log.level || '').toLowerCase();
  if (level === 'warn' || level === 'warning') {
    return true;
  }
  const text = String(log.message || '').toLowerCase();
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
  if (candidates.has(siteUrl)) {
    return true;
  }
  const normalizedSiteUrl = canonicalLogMatchUrl(siteUrl);
  return Array.from(candidates).some((candidate) => {
    if (canonicalLogMatchUrl(candidate) === normalizedSiteUrl) {
      return true;
    }
    return hasSameStablePathIdentity(candidate, siteUrl);
  });
}

function canonicalLogMatchUrl(value: string) {
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
    if (leftHost !== rightHost) {
      return false;
    }

    const lastSegment = (url: URL) =>
      decodeURIComponent(url.pathname).split('/').filter(Boolean).at(-1)?.trim().toLowerCase() ??
      '';
    const leftId = lastSegment(leftUrl);
    const rightId = lastSegment(rightUrl);

    // Retail canonical redirects often rewrite the product slug while keeping
    // the trailing product/SKU identifier stable.
    return leftId.length >= 5 && rightId.length >= 5 && /\d/.test(leftId) && leftId === rightId;
  } catch {
    return false;
  }
}

function siteLabel(url: string, index: number | null, total: number | null) {
  let prefix: string | null = null;
  if (index && total) {
    prefix = `${index}/${total}`;
  } else if (index) {
    prefix = String(index);
  }
  return prefix ? `${prefix} ${url}` : url;
}

export function siteDomId(groupKey: string) {
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

function createRunGroupWithLogs(key: string, logs: CrawlLog[]) {
  const group = createRunGroup(key);
  for (const log of logs) {
    addLogToGroup(group, log, getLogStage(log.message));
  }
  return group;
}

function firstUrlInLog(message: string): string {
  return LOG_PATTERNS.FIRST_URL.exec(sanitizeLogMessage(message))?.[0] ?? '';
}

type LogGroupBuildState = {
  groups: LogSiteGroupDraft[];
  groupMap: Map<string, LogSiteGroupDraft>;
  activeGroupKeyByUrl: Map<string, string>;
  currentGroup: LogSiteGroupDraft | null;
  pendingRunLogs: CrawlLog[];
  untitledCounter: number;
};

function flushPendingRunLogs(state: LogGroupBuildState) {
  if (!state.pendingRunLogs.length) {
    return;
  }
  state.untitledCounter += 1;
  state.groups.push(createRunGroupWithLogs(`run:${state.untitledCounter}`, state.pendingRunLogs));
  state.pendingRunLogs = [];
}

function ensurePrefixedGroup(state: LogGroupBuildState, log: CrawlLog, url: string) {
  const groupKey = state.activeGroupKeyByUrl.get(url);
  let group = groupKey ? state.groupMap.get(groupKey) : undefined;
  if (group) {
    return group;
  }
  const key = `site:prefixed:${log.id}:${url}`;
  group = createSiteGroup({ key, url, index: null, total: null });
  state.groups.push(group);
  state.groupMap.set(key, group);
  state.activeGroupKeyByUrl.set(url, key);
  return group;
}

function handlePrefixedLog(state: LogGroupBuildState, log: CrawlLog) {
  const urlMatch = LOG_PATTERNS.URL_PREFIX.exec(log.message);
  if (!urlMatch) {
    return false;
  }
  const url = urlMatch[1];
  const cleanLog = { ...log, message: log.message.replace(LOG_PATTERNS.URL_PREFIX, '') };
  const group = ensurePrefixedGroup(state, log, url);
  addLogToGroup(group, cleanLog, getLogStage(cleanLog.message));
  state.currentGroup = group;
  return true;
}

function handleStartingLog(state: LogGroupBuildState, log: CrawlLog, logIndex: number) {
  const start = parseStartingLog(log.message);
  if (!start) {
    return false;
  }
  flushPendingRunLogs(state);
  const key = `site:${start.index ?? logIndex}:${log.id}:${start.url}`;
  const group = createSiteGroup({
    key,
    url: start.url,
    index: start.index,
    total: start.total,
  });
  state.groups.push(group);
  state.groupMap.set(key, group);
  state.activeGroupKeyByUrl.set(start.url, key);
  addLogToGroup(group, log, 'system');
  state.currentGroup = group;
  return true;
}

function handleInferredUrlLog(state: LogGroupBuildState, log: CrawlLog, isParallel: boolean) {
  const inferredUrl = firstUrlInLog(log.message);
  if (!inferredUrl) {
    return false;
  }
  const groupKey = state.activeGroupKeyByUrl.get(inferredUrl);
  let group = groupKey ? state.groupMap.get(groupKey) : undefined;
  if (group) {
    addLogToGroup(group, log, getLogStage(log.message));
    state.currentGroup = group;
    return true;
  }
  if (state.currentGroup && !isParallel) {
    return false;
  }
  group = createSiteGroup({
    key: `site:inferred:${log.id}:${inferredUrl}`,
    url: inferredUrl,
    index: null,
    total: null,
  });
  state.groups.push(group);
  state.groupMap.set(group.key, group);
  state.activeGroupKeyByUrl.set(inferredUrl, group.key);
  if (!state.currentGroup) {
    for (const pendingLog of state.pendingRunLogs) {
      addLogToGroup(group, pendingLog, getLogStage(pendingLog.message));
    }
    state.pendingRunLogs = [];
  }
  addLogToGroup(group, log, getLogStage(log.message));
  state.currentGroup = group;
  return true;
}

function handleFallbackLog(state: LogGroupBuildState, log: CrawlLog, isParallel: boolean) {
  if (isParallel && !state.currentGroup) {
    state.pendingRunLogs.push(log);
    return;
  }
  if (!state.currentGroup) {
    state.pendingRunLogs.push(log);
    return;
  }
  addLogToGroup(state.currentGroup, log, getLogStage(log.message));
}

function finalizeLogSiteGroup(group: LogSiteGroupDraft, records: CrawlRecord[]): LogSiteGroup {
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
}

export function buildLogSiteGroups(logs: CrawlLog[], records: CrawlRecord[] = []): LogSiteGroup[] {
  const groups: LogSiteGroupDraft[] = [];
  const state: LogGroupBuildState = {
    groups,
    groupMap: new Map<string, LogSiteGroupDraft>(),
    activeGroupKeyByUrl: new Map<string, string>(),
    currentGroup: null,
    pendingRunLogs: [],
    untitledCounter: 0,
  };

  const isParallel = logs.some((log) => LOG_PATTERNS.URL_PREFIX.test(log.message));

  for (const [logIndex, log] of logs.entries()) {
    if (isHiddenLogMessage(log.message)) {
      continue;
    }
    if (handlePrefixedLog(state, log)) {
      continue;
    }
    if (handleStartingLog(state, log, logIndex)) {
      continue;
    }
    if (handleInferredUrlLog(state, log, isParallel)) {
      continue;
    }
    handleFallbackLog(state, log, isParallel);
  }

  flushPendingRunLogs(state);
  return groups.map((group) => finalizeLogSiteGroup(group, records));
}
