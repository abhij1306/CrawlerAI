import { describe, expect, it, vi } from 'vite-plus/test';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  apiClient: apiMock,
  getApiBaseUrl: () => 'http://127.0.0.1:8001',
}));

import { crawlsApi } from './crawls';

describe('crawlsApi.getRunEvents', () => {
  it('rejects malformed REST Run Events', async () => {
    apiMock.get.mockResolvedValue([
      {
        id: 1,
        run_id: 101,
        sequence: 1,
        kind: 'run.started',
        stage: null,
        url: null,
        url_scope_id: null,
        severity: 'info',
        outcome: 'progress',
        reason_code: null,
        facts: {},
        created_at: '2026-04-08T10:00:00Z',
      },
      { id: 2, sequence: 2 },
    ]);

    await expect(crawlsApi.getRunEvents(101, { afterSequence: 1, limit: 25 })).rejects.toThrow(
      'getRunEvents(101)',
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      '/api/crawls/101/events?after_sequence=1&limit=25',
      undefined,
    );
  });
});
