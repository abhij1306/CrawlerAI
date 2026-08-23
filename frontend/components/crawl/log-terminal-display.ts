import type { CrawlLog, CrawlRecord } from '../../lib/api/types';
import {
  formatDurationMs,
  humanizeFieldName,
  normalizeField,
  parseApiDate,
} from '../../lib/crawl/format';
import { uniqueRequestedFields } from '../../lib/crawl/fields';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import { isInformativeValue, qualityLevelFromScore } from '../../lib/crawl/quality';
import {
  getLogStage,
  parseStartingLog,
  sanitizeLogMessage,
  TERMINAL_STRINGS,
} from './log-terminal-utils';
import type { LogSiteGroup, LogStage } from './log-terminal-utils';

export function severityTone(group: LogSiteGroup, index: number) {
  if (group.hasError) return 'bg-transparent border-l-2 border-l-danger';
  if (group.hasWarning) return 'bg-transparent border-l-2 border-l-warning';
  if (group.recordCount > 0 || group.stageLogs.persistence.length > 0) {
    return 'bg-transparent border-l-2 border-l-success';
  }
  return index % 2 === 0
    ? 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]'
    : 'bg-transparent';
}

export function payloadSnapshot(group: LogSiteGroup) {
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

export function groupConfidence(group: LogSiteGroup): { score: number; level: string } | null {
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

export function groupDurationMs(group: LogSiteGroup, activeNowMs?: number): number | null {
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
  if (!startedAt) return null;
  const startedMs = parseApiDate(startedAt).getTime();
  if (!Number.isFinite(startedMs)) return null;
  const lastLog = group.logs.at(-1);
  const endCandidatesMs = [
    activeNowMs,
    lastLog?.created_at ? parseApiDate(lastLog.created_at).getTime() : null,
    ...group.records.map((record) => parseApiDate(record.created_at).getTime()),
    ...recordDurations.map((durationMs) => startedMs + durationMs),
  ].filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!endCandidatesMs.length) return null;
  return Math.max(0, Math.max(...endCandidatesMs) - startedMs);
}

export function groupFieldCoverage(group: LogSiteGroup, requestedFields: string[]) {
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

type ExpandedLogRow = {
  key: string;
  stage: LogStage;
  level: string;
  message: string;
  createdAt?: string | null;
  payloadAction?: boolean;
};

export function buildExpandedRows(
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
      parts.push(
        `${TERMINAL_STRINGS.CONFIDENCE} ${Math.round(normalizeConfidenceScore(confidence.score) * 100)}%`,
      );
    }
    if (durationMs !== null) parts.push(`${TERMINAL_STRINGS.TIME} ${formatDurationMs(durationMs)}`);
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

export function groupSummaryMessage(
  group: LogSiteGroup,
  coverage: ReturnType<typeof groupFieldCoverage>,
  fallbackLog?: CrawlLog,
) {
  if (group.records.length > 0) {
    const noun = group.records.length === 1 ? 'record' : 'records';
    return `Extracted ${group.records.length} ${noun}; fields ${coverage.foundCount}/${coverage.totalCount || 0}`;
  }
  if (group.hasError || group.hasWarning) {
    return sanitizeLogMessage(fallbackLog?.message ?? 'No public record extracted');
  }
  const persistenceLog = group.stageLogs.persistence.at(-1);
  if (persistenceLog) return sanitizeLogMessage(persistenceLog.message);
  return fallbackLog ? sanitizeLogMessage(fallbackLog.message) : TERMINAL_STRINGS.PENDING;
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
