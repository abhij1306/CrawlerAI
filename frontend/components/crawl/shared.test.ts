import { describe, expect, it } from 'vite-plus/test';

import type { CrawlRecord, RunEvent } from '../../lib/api/types';
import {
  buildRunEventSiteGroups,
  cleanRecordForDisplay,
  decodeUrlsForDisplay,
  estimateDataQuality,
  formatCellDisplay,
  scoreFieldQuality,
  scoreRecordQuality,
  validateAdditionalFieldName,
} from './shared';

function makeRecord(id: number, data: Record<string, unknown>): CrawlRecord {
  return {
    id,
    run_id: 1,
    source_url: `https://example.com/${id}`,
    data,
    raw_data: {},
    discovered_data: {},
    source_trace: {},
    raw_html_path: null,
    created_at: '2026-01-01T00:00:00Z',
  };
}

function makeRunEvent(
  sequence: number,
  overrides: Partial<Omit<RunEvent, 'id' | 'run_id' | 'sequence' | 'created_at'>> = {},
): RunEvent {
  return {
    id: sequence,
    run_id: 1,
    sequence,
    kind: 'run.progress',
    stage: null,
    url: null,
    url_scope_id: null,
    severity: 'info',
    outcome: 'progress',
    reason_code: null,
    facts: {},
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('estimateDataQuality', () => {
  it('returns unknown when there is no record data', () => {
    const quality = estimateDataQuality([], ['title', 'price']);

    expect(quality.level).toBe('unknown');
    expect(quality.score).toBe(0);
  });

  it('returns high for dense, well-shaped rows', () => {
    const records = [
      makeRecord(1, { title: 'Trail Shoe', price: '$10', brand: 'Puma' }),
      makeRecord(2, { title: 'Running Tee', price: '$20', brand: 'Nike' }),
      makeRecord(3, { title: 'Gym Shorts', price: '$30', brand: 'Adidas' }),
    ];

    const quality = estimateDataQuality(records, ['title', 'price', 'brand']);

    expect(quality.level).toBe('high');
    expect(quality.score).toBeGreaterThanOrEqual(0.8);
  });

  it('returns low for sparse rows', () => {
    const records = [
      makeRecord(1, { title: 'Trail Shoe', price: '' }),
      makeRecord(2, { title: '', price: '' }),
      makeRecord(3, { title: '', price: '' }),
    ];

    const quality = estimateDataQuality(records, ['title', 'price']);

    expect(quality.level).toBe('low');
    expect(quality.score).toBeLessThan(0.5);
  });

  it('returns medium for rows that are usable but sparse', () => {
    const records = [
      makeRecord(1, { title: 'Trail Shoe', url: 'https://example.com/a' }),
      makeRecord(2, { title: 'Running Tee', url: 'https://example.com/b' }),
      makeRecord(3, { title: 'Gym Shorts', url: 'https://example.com/c' }),
    ];

    const quality = estimateDataQuality(records, ['title', 'url', 'price', 'brand']);

    expect(quality.level).toBe('medium');
    expect(quality.score).toBeGreaterThanOrEqual(0.5);
    expect(quality.score).toBeLessThan(0.8);
  });
});

describe('scoreRecordQuality', () => {
  it('penalizes rows with only a single weak field', () => {
    const score = scoreRecordQuality(makeRecord(1, { title: 'A' }), ['title', 'price', 'brand']);

    expect(score).toBeLessThan(0.5);
  });

  it('rewards rows with multiple informative fields', () => {
    const score = scoreRecordQuality(
      makeRecord(1, {
        title: 'Trail Shoe',
        price: '$120',
        brand: 'Puma',
        url: 'https://example.com/p/1',
      }),
      ['title', 'price', 'brand', 'url'],
    );

    expect(score).toBeGreaterThanOrEqual(0.8);
  });
});

describe('scoreFieldQuality', () => {
  it('tracks field usefulness without a placeholder state', () => {
    const records = [
      makeRecord(1, { material: 'Mesh' }),
      makeRecord(2, { material: 'Leather' }),
      makeRecord(3, { material: '' }),
    ];

    const score = scoreFieldQuality(records, 'material');

    expect(score).toBeGreaterThanOrEqual(0.5);
    expect(score).toBeLessThan(0.8);
  });
});

describe('validateAdditionalFieldName', () => {
  it('rejects schema type names', () => {
    expect(validateAdditionalFieldName('AggregateRating')).toContain('schema type');
    expect(validateAdditionalFieldName('breadcrumblist')).toContain('schema type');
  });

  it('rejects day-of-week labels', () => {
    expect(validateAdditionalFieldName('Monday')).toContain('day label');
    expect(validateAdditionalFieldName('sunday')).toContain('day label');
  });

  it('accepts concise business field names', () => {
    expect(validateAdditionalFieldName('supplier_color')).toBeNull();
    expect(validateAdditionalFieldName('material')).toBeNull();
  });
});

describe('formatCellDisplay', () => {
  it('decodes internationalized product URLs for UI display only', () => {
    expect(
      formatCellDisplay('https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3'),
    ).toBe('https://www.shop.ving.run/product/สีดำ');
  });

  it('decodes escaped quotes in description text for UI display', () => {
    expect(formatCellDisplay(String.raw`meaning \\"Dragon Well\\" tea`)).toBe(
      'meaning "Dragon Well" tea',
    );
  });
});

describe('decodeUrlsForDisplay', () => {
  it('decodes URL strings nested inside preview JSON objects', () => {
    expect(
      decodeUrlsForDisplay({
        url: 'https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3',
        images: ['https://cdn.example.com/a.jpg'],
      }),
    ).toEqual({
      url: 'https://www.shop.ving.run/product/สีดำ',
      images: ['https://cdn.example.com/a.jpg'],
    });
  });

  it('decodes escaped description strings nested inside preview records', () => {
    expect(
      decodeUrlsForDisplay({
        description: String.raw`meaning \\"Dragon Well\\" tea`,
      }),
    ).toEqual({
      description: 'meaning "Dragon Well" tea',
    });
  });
});

describe('cleanRecordForDisplay', () => {
  it('parses nested JSON strings before raw JSON preview stringifies records', () => {
    const record = makeRecord(1, {
      payload: '{"title":"Trail Shoe","price":"$120"}',
    });

    expect(cleanRecordForDisplay(record)).toEqual({
      payload: { title: 'Trail Shoe', price: '$120' },
    });
  });
});

describe('buildRunEventSiteGroups', () => {
  it('groups Run Events by URL scope and structured stages', () => {
    const records = [
      makeRecord(1, { title: 'Trail Shoe', url: 'https://example.com/p/1' }),
      makeRecord(2, { title: 'Road Shoe', url: 'https://example.com/p/2' }),
    ];
    const events = [
      makeRunEvent(1, { kind: 'url.started', url: 'https://example.com/p/1', url_scope_id: 'p1' }),
      makeRunEvent(2, {
        kind: 'acquisition.succeeded',
        stage: 'acquisition',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
      makeRunEvent(3, {
        kind: 'extraction.succeeded',
        stage: 'extraction',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
      makeRunEvent(4, {
        kind: 'normalization.succeeded',
        stage: 'normalization',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
      makeRunEvent(5, {
        kind: 'persistence.succeeded',
        stage: 'persistence',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
      makeRunEvent(6, { kind: 'url.started', url: 'https://example.com/p/2', url_scope_id: 'p2' }),
      makeRunEvent(7, {
        kind: 'acquisition.succeeded',
        stage: 'acquisition',
        url: 'https://example.com/p/2',
        url_scope_id: 'p2',
        outcome: 'succeeded',
      }),
      makeRunEvent(8, {
        kind: 'extraction.partial',
        stage: 'extraction',
        url: 'https://example.com/p/2',
        url_scope_id: 'p2',
        severity: 'warning',
        outcome: 'partial',
      }),
    ];

    const groups = buildRunEventSiteGroups(events, records);

    expect(groups).toHaveLength(2);
    expect(groups[0].url).toBe('https://example.com/p/1');
    expect(groups[0].stageEvents.acquisition).toHaveLength(1);
    expect(groups[0].stageEvents.extraction).toHaveLength(1);
    expect(groups[0].stageEvents.normalization).toHaveLength(1);
    expect(groups[0].stageEvents.persistence).toHaveLength(1);
    expect(groups[0].recordCount).toBe(1);
    expect(groups[1].hasWarning).toBe(true);
    expect(groups[1].recordCount).toBe(1);
  });

  it('matches canonical product redirects by stable trailing product id', () => {
    const records = [
      makeRecord(1, {
        title: 'Nordstrom Product',
        url: 'https://www.nordstrom.com/s/canonical-product-name/7507996?origin=category-personalizedsort',
      }),
    ];
    const events = [
      makeRunEvent(1, {
        kind: 'url.started',
        url: 'https://www.nordstrom.com/s/old-product-name/7507996',
        url_scope_id: 'p1',
      }),
      makeRunEvent(2, {
        kind: 'persistence.succeeded',
        stage: 'persistence',
        url: 'https://www.nordstrom.com/s/old-product-name/7507996',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
    ];

    const groups = buildRunEventSiteGroups(events, records);

    expect(groups).toHaveLength(1);
    expect(groups[0].recordCount).toBe(1);
  });

  it('does not associate records across query-distinct URL scopes', () => {
    const records = [
      makeRecord(1, { title: 'Small Widget', url: 'https://example.com/p/12345?variant=small' }),
      makeRecord(2, { title: 'Large Widget', url: 'https://example.com/p/12345?variant=large' }),
    ];
    const events = [
      makeRunEvent(1, {
        kind: 'url.started',
        url: 'https://example.com/p/12345?variant=small',
        url_scope_id: 'small',
      }),
      makeRunEvent(2, {
        kind: 'url.started',
        url: 'https://example.com/p/12345?variant=large',
        url_scope_id: 'large',
      }),
    ];

    const groups = buildRunEventSiteGroups(events, records);

    expect(groups[0].records.map((record) => record.id)).toEqual([1]);
    expect(groups[1].records.map((record) => record.id)).toEqual([2]);
  });

  it('keeps run-scoped events separate from URL-scoped events', () => {
    const events = [
      makeRunEvent(1, { kind: 'run.started' }),
      makeRunEvent(2, {
        kind: 'persistence.succeeded',
        stage: 'persistence',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        outcome: 'succeeded',
      }),
      makeRunEvent(3, { kind: 'url.started', url: 'https://example.com/p/2', url_scope_id: 'p2' }),
    ];

    const groups = buildRunEventSiteGroups(events);

    expect(groups).toHaveLength(3);
    expect(groups[0].url).toBe('');
    expect(groups[1].stageEvents.persistence).toHaveLength(1);
    expect(groups[2].url).toBe('https://example.com/p/2');
  });

  it('keeps repeated runs for the same URL in separate groups', () => {
    const events = [
      makeRunEvent(1, {
        kind: 'url.started',
        url: 'https://example.com/p/1',
        url_scope_id: 'attempt-1',
      }),
      makeRunEvent(2, {
        kind: 'extraction.succeeded',
        stage: 'extraction',
        url: 'https://example.com/p/1',
        url_scope_id: 'attempt-1',
        outcome: 'succeeded',
      }),
      makeRunEvent(3, {
        kind: 'url.started',
        url: 'https://example.com/p/1',
        url_scope_id: 'attempt-2',
      }),
      makeRunEvent(4, {
        kind: 'extraction.partial',
        stage: 'extraction',
        url: 'https://example.com/p/1',
        url_scope_id: 'attempt-2',
        severity: 'warning',
        outcome: 'partial',
      }),
    ];

    const groups = buildRunEventSiteGroups(events);

    expect(groups).toHaveLength(2);
    expect(groups[0].url).toBe('https://example.com/p/1');
    expect(groups[1].url).toBe('https://example.com/p/1');
    expect(groups[0].stageEvents.extraction).toHaveLength(1);
    expect(groups[1].stageEvents.extraction).toHaveLength(1);
  });

  it('uses severity and outcome without prose parsing', () => {
    const events = [
      makeRunEvent(1, { kind: 'url.started', url: 'https://example.com/p/1', url_scope_id: 'p1' }),
      makeRunEvent(2, {
        kind: 'extraction.failed',
        stage: 'extraction',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        severity: 'error',
        outcome: 'failed',
      }),
      makeRunEvent(3, {
        kind: 'persistence.skipped',
        stage: 'persistence',
        url: 'https://example.com/p/1',
        url_scope_id: 'p1',
        severity: 'warning',
        outcome: 'skipped',
      }),
    ];

    const groups = buildRunEventSiteGroups(events);

    expect(groups).toHaveLength(1);
    expect(groups[0].hasError).toBe(true);
    expect(groups[0].hasWarning).toBe(false);
    expect(groups[0].stageEvents.extraction).toHaveLength(1);
    expect(groups[0].stageEvents.persistence).toHaveLength(1);
  });
});
