import type { CrawlRecord } from '../api/types';
import {
  decodeUrlsForDisplay,
  formatCellDisplay,
  isEmptyCandidateValue,
  stringifyCell,
} from './format';

export function extractRecordUrl(record: CrawlRecord) {
  const value = record.data?.url ?? record.raw_data?.url ?? record.source_url;
  return stringifyCell(value).trim();
}

export function readRecordValue(record: CrawlRecord, field: string) {
  const data = record.data && typeof record.data === 'object' ? record.data : {};
  const raw = record.raw_data && typeof record.raw_data === 'object' ? record.raw_data : {};
  if (field in data) return data[field];
  if (field in raw) return raw[field];
  if (field === 'source_url') return record.source_url;
  return '';
}

export function copyJson(records: CrawlRecord[]) {
  void navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecordForDisplay), null, 2));
}

export function cleanRecord(record: CrawlRecord) {
  return Object.fromEntries(
    Object.entries(record.data ?? {}).filter(
      ([key, value]) =>
        !key.startsWith('_') &&
        value !== null &&
        value !== '' &&
        !(Array.isArray(value) && value.length === 0),
    ),
  );
}

export function cleanRecordForDisplay(record: CrawlRecord) {
  return decodeUrlsForDisplay(cleanRecord(record));
}

export function cellDisplayForRecord(record: CrawlRecord, field: string) {
  return formatCellDisplay(readRecordValue(record, field));
}

export function recordHasValue(record: CrawlRecord, field: string) {
  return !isEmptyCandidateValue(readRecordValue(record, field));
}
