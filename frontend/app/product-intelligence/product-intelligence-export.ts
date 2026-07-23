import type { ProductIntelligenceDiscoveryResponse } from '../../lib/api/types';
import type { ProductDiscoveryCandidate } from './product-intelligence-utils';
import { isRecord } from './product-intelligence-utils';

export function downloadRows(
  tab: 'urls' | 'intelligence',
  kind: 'csv' | 'json',
  discovery: ProductIntelligenceDiscoveryResponse | null,
) {
  const rows: Array<Record<string, unknown>> =
    tab === 'urls'
      ? (discovery?.candidates ?? []).map((candidate) => ({ ...candidate }))
      : (discovery?.candidates ?? []).map(toIntelligenceExportRow);
  const body = kind === 'csv' ? toCsv(rows) : JSON.stringify(rows, null, 2);
  const type = kind === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8';
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `product-intelligence-${tab}.${kind}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function toIntelligenceExportRow(candidate: ProductDiscoveryCandidate) {
  const row = toIntelligenceRow(candidate);
  return {
    source_title: row.source_title,
    source_brand: row.source_brand,
    result_url: row.url,
    result_domain: row.domain,
    title: row.record.title ?? '',
    brand: row.record.brand ?? '',
    price: row.record.price ?? '',
    currency: row.record.currency ?? '',
    confidence_score: row.confidence_score,
    confidence_label: row.confidence_label,
    cleanup_source: row.cleanup_source,
    score_reasons: row.score_reasons,
  };
}

function toIntelligenceRow(candidate: ProductDiscoveryCandidate) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const record = isRecord(intelligence.canonical_record) ? intelligence.canonical_record : {};
  const parsedConfidence = Number(intelligence.confidence_score ?? 0);
  const confidenceScore = Number.isFinite(parsedConfidence) ? parsedConfidence : 0;
  return {
    source_title: candidate.source_title,
    source_brand: candidate.source_brand,
    url: candidate.url,
    domain: candidate.domain,
    record,
    confidence_score: confidenceScore,
    confidence_label: scalarString(intelligence.confidence_label),
    cleanup_source: scalarString(intelligence.cleanup_source),
    score_reasons: isRecord(intelligence.score_reasons) ? intelligence.score_reasons : {},
  };
}

// Spreadsheet apps execute cells whose text starts with one of these characters as
// formulas; neutralize by prepending a single quote before any other escaping.
const FORMULA_PREFIX = /^[\t\r=+\-@]/;

export function toCsv(rows: Array<Record<string, unknown>>) {
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const lines = [headers.join(',')];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(','));
  }
  return lines.join('\n');
}

function csvCell(value: unknown) {
  const text =
    typeof value === 'object' && value !== null ? JSON.stringify(value) : scalarString(value);
  const safe = FORMULA_PREFIX.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

function scalarString(value: unknown) {
  if (value === null || value === undefined) {
    return '';
  }
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : '';
}
