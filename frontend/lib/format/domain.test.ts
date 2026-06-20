import { describe, expect, it } from 'vitest';

import { isSafeHttpUrl, isSpecialUseDomain } from './domain';

describe('isSafeHttpUrl', () => {
  it('accepts only absolute HTTP and HTTPS URLs', () => {
    expect(isSafeHttpUrl('https://example.com/product')).toBe(true);
    expect(isSafeHttpUrl('http://example.com/product')).toBe(true);
    expect(isSafeHttpUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeHttpUrl('data:text/html,hello')).toBe(false);
    expect(isSafeHttpUrl('/relative/path')).toBe(false);
  });
});

describe('isSpecialUseDomain', () => {
  it('keeps bracketed IPv6 literals intact when stripping ports', () => {
    expect(isSpecialUseDomain('http://[::1]:3000')).toBe(false);
  });

  it('still detects localhost hosts with explicit ports', () => {
    expect(isSpecialUseDomain('localhost:3000')).toBe(true);
    expect(isSpecialUseDomain('http://localhost.localdomain:8080')).toBe(true);
  });
});
