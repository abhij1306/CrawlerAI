import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test';

describe('trackEvent endpoint', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('MODE', 'production');
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  });

  afterEach(() => {
    Reflect.deleteProperty(window.navigator, 'sendBeacon');
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('sends the beacon to the API base URL', async () => {
    const sendBeacon = vi.fn().mockReturnValue(true);
    Object.defineProperty(window.navigator, 'sendBeacon', {
      value: sendBeacon,
      configurable: true,
    });

    const { trackEvent } = await import('./events');
    trackEvent('crawl_started', { run_id: 7 });

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    const [url, blob] = sendBeacon.mock.calls[0] as [string, Blob];
    expect(url).toBe('https://api.example.test/api/telemetry/events');
    expect(blob.type).toBe('application/json');
    expect(JSON.parse(await blob.text())).toMatchObject({
      name: 'crawl_started',
      payload: { run_id: 7 },
    });
  });

  it('posts via fetch to the API base URL when sendBeacon is unavailable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);

    const { trackEvent } = await import('./events');
    trackEvent('crawl_started');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://api.example.test/api/telemetry/events');
    expect(init).toMatchObject({ method: 'POST', keepalive: true });
    expect(JSON.parse(String(init.body))).toMatchObject({ name: 'crawl_started' });
  });
});
