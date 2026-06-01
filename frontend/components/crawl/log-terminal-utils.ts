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
  return candidates.has(siteUrl);
}

function siteLabel(url: string, index: number | null, total: number | null) {
  const prefix = index && total ? `${index}/${total}` : index ? String(index) : null;
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

function firstUrlInLog(message: string): string {
  return sanitizeLogMessage(message).match(/https?:\/\/[^\s]+/i)?.[0] ?? '';
}

export function buildLogSiteGroups(logs: CrawlLog[], records: CrawlRecord[] = []): LogSiteGroup[] {
  const groups: LogSiteGroupDraft[] = [];
  const groupMap = new Map<string, LogSiteGroupDraft>();
  const activeGroupKeyByUrl = new Map<string, string>();
  let currentGroup: LogSiteGroupDraft | null = null;
  let pendingRunLogs: CrawlLog[] = [];
  let untitledCounter = 0;

  const isParallel = logs.some((log) => LOG_PATTERNS.URL_PREFIX.test(log.message));

  for (const [logIndex, log] of logs.entries()) {
    if (isHiddenLogMessage(log.message)) {
      continue;
    }

    // 1. Check if the log message has a [url:...] prefix
    const urlMatch = log.message.match(LOG_PATTERNS.URL_PREFIX);
    if (urlMatch) {
      const url = urlMatch[1];
      const cleanMessage = log.message.replace(LOG_PATTERNS.URL_PREFIX, '');
      const cleanLog = { ...log, message: cleanMessage };
      const groupKey = activeGroupKeyByUrl.get(url);

      // Look up or create group for this URL
      let group = groupKey ? groupMap.get(groupKey) : undefined;
      if (!group) {
        const key = `site:prefixed:${log.id}:${url}`;
        group = createSiteGroup({
          key,
          url,
          index: null,
          total: null,
        });
        groups.push(group);
        groupMap.set(key, group);
        activeGroupKeyByUrl.set(url, key);
      }

      addLogToGroup(group, cleanLog, getLogStage(cleanLog.message));
      currentGroup = group;
      continue;
    }

    // 2. Check if the log is a starting log
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

      const key = `site:${start.index ?? logIndex}:${log.id}:${start.url}`;
      const group = createSiteGroup({
        key,
        url: start.url,
        index: start.index,
        total: start.total,
      });
      groups.push(group);
      groupMap.set(key, group);
      activeGroupKeyByUrl.set(start.url, key);

      addLogToGroup(group, log, 'system');
      currentGroup = group;
      continue;
    }

    // 3. Inferred URL via log content
    const inferredUrl = firstUrlInLog(log.message);
    if (inferredUrl) {
      const groupKey = activeGroupKeyByUrl.get(inferredUrl);
      let group = groupKey ? groupMap.get(groupKey) : undefined;
      if (group) {
        addLogToGroup(group, log, getLogStage(log.message));
        currentGroup = group;
        continue;
      }

      if (!currentGroup || isParallel) {
        group = createSiteGroup({
          key: `site:inferred:${log.id}:${inferredUrl}`,
          url: inferredUrl,
          index: null,
          total: null,
        });
        groups.push(group);
        groupMap.set(group.key, group);
        activeGroupKeyByUrl.set(inferredUrl, group.key);

        // Attach leading run logs if this is the first URL group and currentGroup is null
        if (!currentGroup && pendingRunLogs.length) {
          for (const pendingLog of pendingRunLogs) {
            addLogToGroup(group, pendingLog, getLogStage(pendingLog.message));
          }
          pendingRunLogs = [];
        }
        addLogToGroup(group, log, getLogStage(log.message));
        currentGroup = group;
        continue;
      }
    }

    // 4. Fallback for logs without URL and without prefix
    if (isParallel && !currentGroup) {
      pendingRunLogs.push(log);
    } else {
      if (!currentGroup) {
        pendingRunLogs.push(log);
        continue;
      }
      addLogToGroup(currentGroup, log, getLogStage(log.message));
    }
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
