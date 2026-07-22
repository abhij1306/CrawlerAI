import { describe, expect, it } from 'vite-plus/test';

import { parseOptionalClampedNumber } from './format';

describe('parseOptionalClampedNumber', () => {
  it('returns null for empty or whitespace-only input in both modes', () => {
    expect(parseOptionalClampedNumber('', 1, 10, 'clamp-to-min')).toBeNull();
    expect(parseOptionalClampedNumber('   ', 1, 10, 'clamp-to-min')).toBeNull();
    expect(parseOptionalClampedNumber('', 1, 10, 'null')).toBeNull();
    expect(parseOptionalClampedNumber('   ', 1, 10, 'null')).toBeNull();
  });

  it('falls back to min for non-numeric input in clamp-to-min mode', () => {
    expect(parseOptionalClampedNumber('abc', 5, 10, 'clamp-to-min')).toBe(5);
  });

  it('returns null for non-numeric input in null mode', () => {
    expect(parseOptionalClampedNumber('abc', 5, 10, 'null')).toBeNull();
  });

  it('clamps parsed values into bounds in both modes', () => {
    expect(parseOptionalClampedNumber('0', 1, 10, 'clamp-to-min')).toBe(1);
    expect(parseOptionalClampedNumber('99', 1, 10, 'clamp-to-min')).toBe(10);
    expect(parseOptionalClampedNumber('0', 1, 10, 'null')).toBe(1);
    expect(parseOptionalClampedNumber('99', 1, 10, 'null')).toBe(10);
    expect(parseOptionalClampedNumber('7', 1, 10, 'null')).toBe(7);
  });

  it('parses leading integers like the previous implementations', () => {
    expect(parseOptionalClampedNumber('12px', 1, 60, 'clamp-to-min')).toBe(12);
    expect(parseOptionalClampedNumber('12px', 1, 60, 'null')).toBe(12);
  });
});
