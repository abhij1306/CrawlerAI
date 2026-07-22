import { describe, expect, it } from 'vite-plus/test';

import { aiVisibilityStatusLabel, aiVisibilityStatusTone } from './ai-visibility-status';

describe('aiVisibilityStatusTone', () => {
  it('delegates canonical statuses to lib/ui/status', () => {
    expect(aiVisibilityStatusTone('completed')).toBe('success');
    expect(aiVisibilityStatusTone('running')).toBe('accent');
    expect(aiVisibilityStatusTone('failed')).toBe('danger');
    expect(aiVisibilityStatusTone('pending')).toBe('neutral');
    expect(aiVisibilityStatusTone('degraded')).toBe('warning');
  });

  it('keeps the cancelled -> warning mapping the canonical module lacks', () => {
    expect(aiVisibilityStatusTone('cancelled')).toBe('warning');
  });

  it('falls back to neutral for unknown statuses', () => {
    expect(aiVisibilityStatusTone('something-unexpected')).toBe('neutral');
  });
});

describe('aiVisibilityStatusLabel', () => {
  it('uses canonical labels from lib/ui/status', () => {
    expect(aiVisibilityStatusLabel('completed')).toBe('Completed');
    expect(aiVisibilityStatusLabel('running')).toBe('Running');
    expect(aiVisibilityStatusLabel('degraded')).toBe('Degraded');
  });

  it('falls back to the raw status when the canonical module has no label', () => {
    expect(aiVisibilityStatusLabel('cancelled')).toBe('cancelled');
  });
});
