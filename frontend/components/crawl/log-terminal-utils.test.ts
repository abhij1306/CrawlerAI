import { describe, expect, it } from 'vite-plus/test';

import { LOG_GROUP_WINDOW_SIZE, sanitizeLogMessage, windowLogGroups } from './log-terminal-utils';

describe('sanitizeLogMessage', () => {
  it('removes repeated correlation tags without changing surrounding text', () => {
    expect(sanitizeLogMessage('Fetched [corr=abc]  page [corr=def]')).toBe('Fetched page');
    expect(sanitizeLogMessage('Fetched [CoRr=abc] page')).toBe('Fetched page');
  });

  it('handles a long malformed correlation prefix without backtracking', () => {
    const message = `Fetched ${'[corr='}${'x'.repeat(100_000)}`;
    expect(sanitizeLogMessage(message)).toBe(message);
  });

  it('preserves an incomplete tag after removing earlier complete tags', () => {
    expect(sanitizeLogMessage('Fetched [corr=abc] page [corr=incomplete')).toBe(
      'Fetched page [corr=incomplete',
    );
  });
});

describe('windowLogGroups', () => {
  it('returns the same array when the count is under the limit', () => {
    const groups = ['a', 'b', 'c'];
    const result = windowLogGroups(groups, 3);
    expect(result.visible).toBe(groups);
    expect(result.hiddenCount).toBe(0);
  });

  it('returns identity for an empty list', () => {
    const groups: number[] = [];
    const result = windowLogGroups(groups, LOG_GROUP_WINDOW_SIZE);
    expect(result.visible).toBe(groups);
    expect(result.hiddenCount).toBe(0);
  });

  it('keeps the last N groups and reports the hidden count', () => {
    const groups = [1, 2, 3, 4, 5];
    const result = windowLogGroups(groups, 2);
    expect(result.visible).toEqual([4, 5]);
    expect(result.hiddenCount).toBe(3);
  });

  it('windows a large list down to the window size', () => {
    const groups = Array.from({ length: LOG_GROUP_WINDOW_SIZE + 7 }, (_, index) => index);
    const result = windowLogGroups(groups, LOG_GROUP_WINDOW_SIZE);
    expect(result.visible).toHaveLength(LOG_GROUP_WINDOW_SIZE);
    expect(result.visible[0]).toBe(7);
    expect(result.hiddenCount).toBe(7);
  });
});
