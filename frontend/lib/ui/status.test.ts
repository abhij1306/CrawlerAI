import { describe, expect, it } from 'vite-plus/test';

import { runExecutionLabel, runExecutionTone, statusTone } from './status';

describe('runExecutionStatus', () => {
  it('downgrades completed zero-result runs to warning', () => {
    expect(
      runExecutionTone('completed', {
        extraction_verdict: 'listing_detection_failed',
        record_count: 0,
      }),
    ).toBe('warning');
    expect(
      runExecutionLabel('completed', {
        extraction_verdict: 'listing_detection_failed',
        record_count: 0,
      }),
    ).toBe('Listing Failed');
  });

  it('marks completed blocked or error runs as danger', () => {
    expect(
      runExecutionTone('completed', {
        extraction_verdict: 'error',
        record_count: 0,
      }),
    ).toBe('danger');
    expect(
      runExecutionLabel('completed', {
        extraction_verdict: 'blocked',
        record_count: 0,
      }),
    ).toBe('Blocked');
  });
});

describe('statusTone', () => {
  it('maps the canonical run statuses', () => {
    expect(statusTone('completed')).toBe('success');
    expect(statusTone('running')).toBe('accent');
    expect(statusTone('paused')).toBe('warning');
    expect(statusTone('failed')).toBe('danger');
    expect(statusTone('killed')).toBe('warning');
    expect(statusTone('proxy_exhausted')).toBe('danger');
    expect(statusTone('pending')).toBe('neutral');
  });

  it('keeps legacy aliases and is case-insensitive', () => {
    expect(statusTone('complete')).toBe('success');
    expect(statusTone('success')).toBe('success');
    expect(statusTone('error')).toBe('danger');
    expect(statusTone('Completed')).toBe('success');
  });

  it('falls back to neutral for unknown statuses', () => {
    expect(statusTone('')).toBe('neutral');
    expect(statusTone('not-a-real-status')).toBe('neutral');
  });

  it('maps cancelled to warning via the generic aliases', () => {
    expect(statusTone('cancelled')).toBe('warning');
  });
});
