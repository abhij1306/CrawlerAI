import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test';

const originalViteApiBaseUrl = import.meta.env.VITE_API_BASE_URL;

describe('apiClient', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    if (originalViteApiBaseUrl) {
      vi.stubEnv('VITE_API_BASE_URL', originalViteApiBaseUrl);
    }
  });

  it('throws ApiError for successful non-json response with body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html>ok</html>', {
          status: 200,
          headers: { 'content-type': 'text/html' },
        }),
      ),
    );

    const { apiClient } = await import('./client');
    await expect(apiClient.get('/api/example')).rejects.toThrow('Expected JSON response from API.');
  });

  it('validates configured API base URL contract early', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'localhost');
    const { getApiBaseUrl } = await import('./client');

    expect(() => getApiBaseUrl()).toThrow('VITE_API_BASE_URL must be a valid absolute URL');
  });

  it('rejects configured API base URL with unsupported protocol', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'ftp://api.example.com');
    const { getApiBaseUrl } = await import('./client');

    expect(() => getApiBaseUrl()).toThrow('VITE_API_BASE_URL must use http:// or https://.');
  });

  it('normalizes a valid configured API base URL', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/');
    const { getApiBaseUrl } = await import('./client');

    expect(getApiBaseUrl()).toBe('https://api.example.com');
  });

  it('uses Vite API base URL for production configuration', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://vite.example.com/');
    const { getApiBaseUrl } = await import('./client');

    expect(getApiBaseUrl()).toBe('https://vite.example.com');
  });

  it('keeps a single-origin policy after 404 responses', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response('Not Found', { status: 404 }));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.get<{ ok: boolean }>('/api/ping')).rejects.toThrow('Not Found');

    expect(fetchMock).toHaveBeenCalledTimes(1);

    const firstUrl = String(fetchMock.mock.calls[0]?.[0] ?? '');
    expect(firstUrl).not.toEqual('');
  });

  it('does not retry mutation network failures', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await expect(apiClient.post('/api/crawls', { url: 'https://example.com' })).rejects.toThrow(
      'offline',
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('forwards AbortSignal and request identifiers', async () => {
    const controller = new AbortController();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.get('/api/ping', { signal: controller.signal, requestId: 'request-test' });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
    expect(new Headers(init.headers).get('X-Request-ID')).toBe('request-test');
  });

  it('keeps ordinary GET requests simple to avoid a CORS preflight', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.get('/api/ping');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('X-Request-ID')).toBeNull();
  });

  it('keeps generated request identifiers on mutations', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { apiClient } = await import('./client');
    await apiClient.post('/api/crawls', { url: 'https://example.com' });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get('X-Request-ID')).toBeTruthy();
  });

  it('httpErrorStatus reads status from ApiError and duck-typed errors', async () => {
    const { ApiError, httpErrorStatus } = await import('./client');
    const apiErr = new ApiError('x', 403, '{}');
    expect(httpErrorStatus(apiErr)).toBe(403);
    expect(httpErrorStatus({ status: 401 })).toBe(401);
    expect(httpErrorStatus(new Error('no'))).toBeUndefined();
  });

  it('preserves review bucket evidence metadata during validation', async () => {
    const { crawlRecordSchema, strictValidate } = await import('../../lib/api/schemas');
    const parsed = strictValidate(
      crawlRecordSchema,
      {
        id: 1,
        run_id: 2,
        source_url: 'https://example.com/p',
        data: {},
        raw_data: {},
        discovered_data: {},
        source_trace: {},
        review_bucket: [
          {
            key: 'price',
            value: '10.00',
            source: 'dom',
            evidence_id: 'ev_000001',
            reason: 'lower_source_priority',
          },
        ],
        raw_html_path: null,
        created_at: '2026-06-16T00:00:00Z',
      },
      'record',
    );

    expect(parsed.review_bucket?.[0]).toMatchObject({
      evidence_id: 'ev_000001',
      reason: 'lower_source_priority',
    });
  });
});
