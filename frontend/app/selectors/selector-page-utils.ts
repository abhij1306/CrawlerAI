import type { SelectorRecord } from '../../lib/api/types';

export type SelectorKind = 'xpath' | 'css_selector' | 'regex';
export type RowState = 'idle' | 'accepted' | 'saved';

export type SelectorRow = {
  key: string;
  selectorId: number | null;
  surface: string | null;
  fieldName: string;
  kind: SelectorKind;
  selectorValue: string;
  extractedValue: string;
  source: string;
  state: RowState;
};

export function normalizeField(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, '_');
}

export function selectRelevantSelectorRecords(records: SelectorRecord[], surface: string) {
  return records
    .filter(
      (record) => record.is_active && (record.surface === surface || record.surface === 'generic'),
    )
    .sort((left, right) => {
      const leftPriority = left.surface === surface ? 0 : 1;
      const rightPriority = right.surface === surface ? 0 : 1;
      if (leftPriority !== rightPriority) {
        return leftPriority - rightPriority;
      }
      return `${left.field_name}:${left.id}`.localeCompare(`${right.field_name}:${right.id}`);
    });
}

export function inferSelectorSurface(fields: string[], url: string) {
  const normalized = new Set(fields.map((field) => normalizeField(field)));
  if (
    ['company', 'location', 'apply_url', 'salary', 'remote'].some((field) => normalized.has(field))
  ) {
    return 'job_detail';
  }
  if (String(url).toLowerCase().includes('jobs')) {
    return 'job_detail';
  }
  return 'ecommerce_detail';
}

export function mergeSelectorRows(
  currentRows: SelectorRow[],
  incomingRows: SelectorRow[],
  options?: { preferIncoming?: boolean },
) {
  const merged = new Map<string, SelectorRow>();
  const preferIncoming = Boolean(options?.preferIncoming);
  for (const row of currentRows) {
    merged.set(normalizeField(row.fieldName || row.key), row);
  }
  for (const row of incomingRows) {
    const key = normalizeField(row.fieldName || row.key);
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, row);
      continue;
    }
    merged.set(key, {
      ...existing,
      selectorId: existing.selectorId ?? row.selectorId,
      surface: existing.surface ?? row.surface,
      fieldName: existing.fieldName || row.fieldName,
      kind: preferIncoming ? row.kind : existing.selectorValue ? existing.kind : row.kind,
      selectorValue: preferIncoming
        ? row.selectorValue
        : existing.selectorValue || row.selectorValue,
      extractedValue: preferIncoming
        ? row.extractedValue
        : existing.extractedValue || row.extractedValue,
      source: preferIncoming ? row.source : existing.source || row.source,
      state: preferIncoming ? row.state : existing.state === 'saved' ? 'saved' : row.state,
    });
  }
  return Array.from(merged.values());
}

export function buildXPathForElement(element: Element): string {
  const segments: string[] = [];
  let current: Element | null = element;
  while (current && current.nodeType === Node.ELEMENT_NODE) {
    const tagName = current.tagName.toLowerCase();
    const testId = current.getAttribute('data-testid');
    if (testId) {
      segments.unshift(`//${tagName}[@data-testid=${xpathLiteral(testId)}]`);
      return segments.join('');
    }
    const id = current.getAttribute('id');
    if (id) {
      segments.unshift(`//${tagName}[@id=${xpathLiteral(id)}]`);
      return segments.join('');
    }
    let index = 1;
    if (current.parentElement) {
      for (const sibling of current.parentElement.children) {
        if (sibling === current) {
          break;
        }
        if (sibling.tagName.toLowerCase() === tagName) {
          index += 1;
        }
      }
    }
    segments.unshift(`/${tagName}[${index}]`);
    current = current.parentElement;
  }
  return segments.join('') || '//*';
}

export function xpathLiteral(value: string): string {
  if (!value.includes("'")) {
    return `'${value}'`;
  }
  if (!value.includes('"')) {
    return `"${value}"`;
  }
  const parts = value.split("'");
  const args: string[] = [];
  for (let index = 0; index < parts.length; index += 1) {
    args.push(`'${parts[index]}'`);
    if (index < parts.length - 1) {
      args.push(`"'"`);
    }
  }
  return `concat(${args.join(',')})`;
}
