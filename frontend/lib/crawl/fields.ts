import { normalizeField } from './format';

export function uniqueFields(values: string[]) {
  return Array.from(new Set(values.map(normalizeField).filter(Boolean)));
}

export function cleanRequestedField(value: string) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, ' ');
}

export function uniqueRequestedFields(values: string[]) {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const cleaned = cleanRequestedField(value);
    if (!cleaned) {
      continue;
    }
    const dedupeKey = cleaned.toLocaleLowerCase();
    if (seen.has(dedupeKey)) {
      continue;
    }
    seen.add(dedupeKey);
    deduped.push(cleaned);
  }
  return deduped;
}

export function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}

export function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

const SCHEMA_TYPE_FIELD_NAMES = new Set(
  [
    'AggregateRating',
    'BreadcrumbList',
    'IndividualProduct',
    'Organization',
    'PeopleAudience',
    'PostalAddress',
    'QuantitativeValue',
    'WebPage',
    'WebSite',
  ].flatMap((value) => {
    const normalized = normalizeField(value);
    return [normalized, normalized.replace(/_/g, '')];
  }),
);

const DAY_OF_WEEK_FIELD_NAMES = new Set([
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]);

export function validateAdditionalFieldName(value: string) {
  const cleaned = cleanRequestedField(value);
  const normalized = normalizeField(cleaned);
  const collapsed = normalized.replace(/_/g, '');
  if (!cleaned) {
    return 'Field name cannot be empty.';
  }
  if (cleaned.length < 2) {
    return 'Field name must be at least 2 characters.';
  }
  if (cleaned.length > 60) {
    return 'Field name must be 60 characters or fewer.';
  }
  if (!normalized) {
    return 'Field name must include letters or numbers.';
  }
  if ((cleaned.match(/\s+/g) ?? []).length >= 7 || (normalized.match(/_/g) ?? []).length >= 7) {
    return 'Field name is too sentence-like. Keep it concise.';
  }
  if (SCHEMA_TYPE_FIELD_NAMES.has(normalized) || SCHEMA_TYPE_FIELD_NAMES.has(collapsed)) {
    return 'Field name looks like a schema type. Use a business field.';
  }
  if (DAY_OF_WEEK_FIELD_NAMES.has(normalized)) {
    return 'Field name looks like a day label. Use a business field.';
  }
  return null;
}
