import { describe, expect, it } from 'vite-plus/test';

import { isSafeHttpUrl, isSpecialUseDomain, surfaceLabel } from './domain';

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
    expect(isSpecialUseDomain('localhost:3001')).toBe(true);
    expect(isSpecialUseDomain('http://localhost.localdomain:8080')).toBe(true);
  });
});

describe('surfaceLabel', () => {
  it('maps known surfaces to their display labels', () => {
    expect(surfaceLabel('ecommerce_listing')).toBe('Commerce Listing');
    expect(surfaceLabel('ecommerce_detail')).toBe('Commerce Detail');
    expect(surfaceLabel('job_listing')).toBe('Job Listing');
    expect(surfaceLabel('job_detail')).toBe('Job Detail');
  });

  it('humanizes unknown surfaces instead of returning the raw key', () => {
    expect(surfaceLabel('forum_thread_x')).toBe('forum thread x');
    expect(surfaceLabel('generic')).toBe('generic');
  });
});
