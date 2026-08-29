import { describe, expect, it } from 'vite-plus/test';

import { RUN_EVENT_GROUP_WINDOW_SIZE, windowRunEventGroups } from './run-event-terminal-utils';

describe('windowRunEventGroups', () => {
  it('returns the same array when the count is under the limit', () => {
    const groups = ['a', 'b', 'c'];
    const result = windowRunEventGroups(groups, 3);
    expect(result.visible).toBe(groups);
    expect(result.hiddenCount).toBe(0);
  });

  it('returns identity for an empty list', () => {
    const groups: number[] = [];
    const result = windowRunEventGroups(groups, RUN_EVENT_GROUP_WINDOW_SIZE);
    expect(result.visible).toBe(groups);
    expect(result.hiddenCount).toBe(0);
  });

  it('keeps the last N groups and reports the hidden count', () => {
    const groups = [1, 2, 3, 4, 5];
    const result = windowRunEventGroups(groups, 2);
    expect(result.visible).toEqual([4, 5]);
    expect(result.hiddenCount).toBe(3);
  });

  it('windows a large list down to the window size', () => {
    const groups = Array.from({ length: RUN_EVENT_GROUP_WINDOW_SIZE + 7 }, (_, index) => index);
    const result = windowRunEventGroups(groups, RUN_EVENT_GROUP_WINDOW_SIZE);
    expect(result.visible).toHaveLength(RUN_EVENT_GROUP_WINDOW_SIZE);
    expect(result.visible[0]).toBe(7);
    expect(result.hiddenCount).toBe(7);
  });
});
