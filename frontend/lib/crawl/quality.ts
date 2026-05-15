import type { CrawlRecord } from '../api/types';
import { isEmptyCandidateValue, normalizeField, stringifyCell } from './format';
import { readRecordValue } from './record-utils';

export type QualityLevel = 'high' | 'medium' | 'low' | 'unknown';

export type QualitySnapshot = {
  level: QualityLevel;
  score: number;
  populatedCells: number;
  totalCells: number;
};

const QUALITY_IDENTITY_FIELD_PATTERNS = [
  /^title$/,
  /^name$/,
  /_title$/,
  /_name$/,
  /^url$/,
  /_url$/,
  /^price$/,
  /_price$/,
  /^brand$/,
  /^company$/,
  /^location$/,
  /^sku$/,
  /^id$/,
];

const LOW_SIGNAL_VALUE_TOKENS = new Set([
  'n/a',
  'na',
  'none',
  'null',
  'undefined',
  'unknown',
  'tbd',
  '--',
  '-',
]);

export function isIdentityField(field: string) {
  const normalized = normalizeField(field);
  return QUALITY_IDENTITY_FIELD_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isInformativeValue(value: unknown): boolean {
  if (isEmptyCandidateValue(value)) {
    return false;
  }

  const rendered = stringifyCell(value).trim();
  if (!rendered) {
    return false;
  }

  if (LOW_SIGNAL_VALUE_TOKENS.has(rendered.toLowerCase())) {
    return false;
  }

  if (Array.isArray(value)) {
    return value.some((entry) => isInformativeValue(entry));
  }

  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some((entry) =>
      isInformativeValue(entry),
    );
  }

  return rendered.length >= 2;
}

export function scoreRecordQuality(record: CrawlRecord, visibleColumns: string[]) {
  if (!visibleColumns.length) {
    return 0;
  }

  let populatedCount = 0;
  let informativeCount = 0;
  let identityCount = 0;

  for (const column of visibleColumns) {
    const value = readRecordValue(record, column);
    if (isEmptyCandidateValue(value)) {
      continue;
    }

    populatedCount += 1;
    if (isInformativeValue(value)) {
      informativeCount += 1;
      if (isIdentityField(column)) {
        identityCount += 1;
      }
    }
  }

  const coverage = populatedCount / visibleColumns.length;
  const richness = Math.min(1, informativeCount / 4);
  const identity = Math.min(1, identityCount / 2);
  let score = coverage * 0.45 + richness * 0.35 + identity * 0.2;

  if (informativeCount <= 1) {
    score = Math.min(score, 0.34);
  } else if (informativeCount === 2) {
    score = Math.min(score, identityCount >= 1 ? 0.68 : 0.54);
  } else if (informativeCount < 4) {
    score = Math.min(score, 0.84);
  }

  return score;
}

export function scoreFieldQuality(records: CrawlRecord[], field: string) {
  if (!records.length) {
    return 0;
  }
  const informativeValues = records
    .map((record) => readRecordValue(record, field))
    .filter((value) => isInformativeValue(value));
  if (!informativeValues.length) {
    return 0;
  }
  const coverage = informativeValues.length / records.length;
  const uniqueValues = new Set(
    informativeValues.map((value) => stringifyCell(value).trim().toLowerCase()).filter(Boolean),
  ).size;
  const diversity = Math.min(1, uniqueValues / Math.min(3, informativeValues.length));
  return coverage * 0.75 + diversity * 0.25;
}

export function estimateDataQuality(
  records: CrawlRecord[],
  visibleColumns: string[],
): QualitySnapshot {
  if (!records.length || !visibleColumns.length) {
    return {
      level: 'unknown',
      score: 0,
      populatedCells: 0,
      totalCells: records.length * visibleColumns.length,
    };
  }

  const totalCells = records.length * visibleColumns.length;
  let populatedCells = 0;
  let aggregateRecordScore = 0;
  let broadlyUsefulRows = 0;

  for (const record of records) {
    let populatedForRecord = 0;
    for (const column of visibleColumns) {
      const value = readRecordValue(record, column);
      if (!isEmptyCandidateValue(value)) {
        populatedCells += 1;
        populatedForRecord += 1;
      }
    }
    const recordScore = scoreRecordQuality(record, visibleColumns);
    aggregateRecordScore += recordScore;
    if (recordScore >= 0.55 || populatedForRecord >= 3) {
      broadlyUsefulRows += 1;
    }
  }

  const completenessRatio = populatedCells / totalCells;
  const averageRecordScore = aggregateRecordScore / records.length;
  const usefulRowRatio = broadlyUsefulRows / records.length;
  const score = completenessRatio * 0.2 + averageRecordScore * 0.6 + usefulRowRatio * 0.2;

  if (score >= 0.8) {
    return { level: 'high', score, populatedCells, totalCells };
  }
  if (score >= 0.5) {
    return { level: 'medium', score, populatedCells, totalCells };
  }
  return { level: 'low', score, populatedCells, totalCells };
}

export function qualityTone(level: QualityLevel) {
  if (level === 'high') return 'success';
  if (level === 'medium') return 'warning';
  if (level === 'low') return 'danger';
  return 'neutral';
}

export function humanizeQuality(level: QualityLevel) {
  if (level === 'unknown') return 'Unknown';
  return level.charAt(0).toUpperCase() + level.slice(1);
}

export function qualityLevelFromScore(score: number): QualityLevel {
  if (!Number.isFinite(score)) return 'unknown';
  if (score >= 0.8) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}
