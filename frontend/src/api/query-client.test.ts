import { describe, expect, it } from 'vite-plus/test';

import { ApiError } from './errors';
import { createAppQueryClient } from './query-client';

describe('createAppQueryClient', () => {
  it('keeps query retry policy in React Query', () => {
    const client = createAppQueryClient();
    const retry = client.getDefaultOptions().queries?.retry;

    expect(typeof retry).toBe('function');
    expect(
      (retry as (failureCount: number, error: unknown) => boolean)(0, new Error('offline')),
    ).toBe(true);
    expect(
      (retry as (failureCount: number, error: unknown) => boolean)(2, new Error('offline')),
    ).toBe(false);
    expect(
      (retry as (failureCount: number, error: unknown) => boolean)(0, new ApiError('bad', 400, '')),
    ).toBe(false);
    expect(
      (retry as (failureCount: number, error: unknown) => boolean)(
        0,
        new ApiError('down', 503, ''),
      ),
    ).toBe(true);
  });
});
