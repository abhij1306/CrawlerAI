import { afterEach, describe, expect, it } from 'vite-plus/test';

import { STORAGE_KEYS } from '../constants/storage-keys';
import {
  parsePrefillRecords,
  storeDataEnrichmentPrefill,
  storeProductIntelligencePrefill,
} from './prefill';

afterEach(() => {
  window.sessionStorage.clear();
});

describe('parsePrefillRecords', () => {
  it('keeps plain records with numeric id and run_id', () => {
    const records = [
      { id: 1, run_id: 2, source_url: 'https://shop.example/p/1', data: { title: 'Chair' } },
      { id: 3, run_id: 4, source_url: 'https://shop.example/p/2', data: {} },
    ];
    expect(parsePrefillRecords(records)).toEqual(records);
  });

  it('drops malformed entries instead of failing the whole load', () => {
    const good = { id: 1, run_id: 2, source_url: 'https://shop.example/p/1', data: {} };
    const parsed = parsePrefillRecords([
      good,
      null,
      'nope',
      42,
      [1, 2],
      { id: '1', run_id: 2 },
      { id: 1 },
      { run_id: 2 },
    ]);
    expect(parsed).toEqual([good]);
  });

  it('returns an empty array for non-array input', () => {
    expect(parsePrefillRecords(undefined)).toEqual([]);
    expect(parsePrefillRecords(null)).toEqual([]);
    expect(parsePrefillRecords({ id: 1, run_id: 2 })).toEqual([]);
    expect(parsePrefillRecords('[]')).toEqual([]);
  });
});

describe('prefill store/parse round-trip', () => {
  it('stores a Product Intelligence payload that parses back to the same records', () => {
    const payload = {
      source_run_id: 7,
      source_domain: 'https://shop.example',
      records: [
        { id: 1, run_id: 7, source_url: 'https://shop.example/p/1', data: { title: 'Chair' } },
      ],
    };

    storeProductIntelligencePrefill(payload, window.sessionStorage);

    const raw = window.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
    expect(raw).toBe(JSON.stringify(payload));
    const parsed = JSON.parse(raw ?? 'null') as { records?: unknown };
    expect(parsePrefillRecords(parsed.records)).toEqual(payload.records);
  });

  it('stores a Data Enrichment payload that parses back to the same records', () => {
    const payload = {
      source_run_id: 8,
      records: [{ id: 2, run_id: 8, source_url: 'https://shop.example/p/2', data: { price: 10 } }],
    };

    storeDataEnrichmentPrefill(payload, window.sessionStorage);

    const raw = window.sessionStorage.getItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
    expect(raw).toBe(JSON.stringify(payload));
    const parsed = JSON.parse(raw ?? 'null') as { records?: unknown };
    expect(parsePrefillRecords(parsed.records)).toEqual(payload.records);
  });
});
