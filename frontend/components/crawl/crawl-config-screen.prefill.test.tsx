import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { UI_DELAYS } from '../../lib/constants/timing';
import { TopBarProvider } from '../layout/top-bar-context';
import { CrawlConfigScreen } from './crawl-config-screen';

const {
  replaceMock,
  createCsvCrawlMock,
  createCrawlMock,
  getDomainRunProfileMock,
  listSelectorsMock,
} = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  createCsvCrawlMock: vi.fn(),
  createCrawlMock: vi.fn(),
  getDomainRunProfileMock: vi.fn(),
  listSelectorsMock: vi.fn(),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useLocation: () => ({ pathname: '/crawl', search: '', hash: '', state: null, key: 'test' }),
    useNavigate: () => replaceMock,
  };
});

vi.mock('../../lib/api/crawls', () => ({
  crawlsApi: {
    createCsvCrawl: createCsvCrawlMock,
    createCrawl: createCrawlMock,
  },
}));

vi.mock('../../lib/api/domain-memory', () => ({
  domainMemoryApi: {
    getDomainRunProfile: getDomainRunProfileMock,
  },
}));

vi.mock('../../lib/api/selectors', () => ({
  selectorsApi: {
    listSelectors: listSelectorsMock,
  },
}));

function renderConfigScreen() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TopBarProvider>
        <CrawlConfigScreen
          requestedTab={null}
          requestedCategoryMode={null}
          requestedPdpMode={null}
        />
      </TopBarProvider>
    </QueryClientProvider>,
  );
}

function enterTargetUrl(url: string): void {
  fireEvent.change(screen.getByLabelText('Target URL input'), {
    target: { value: url },
  });
}

async function expectDomainProfileLookup(
  url: string,
  surface = 'ecommerce_listing',
): Promise<void> {
  await waitFor(
    () => {
      expect(getDomainRunProfileMock).toHaveBeenCalledWith(
        { url, surface },
        { signal: expect.any(AbortSignal) },
      );
    },
    { timeout: UI_DELAYS.DEBOUNCE_MS * 6 },
  );
}

function savedProfile(hostMemoryTtlSeconds: number) {
  return {
    version: 1,
    fetch_profile: {
      fetch_mode: 'browser_only' as const,
      extraction_source: 'raw_html' as const,
      js_mode: 'auto' as const,
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 500,
      host_memory_ttl_seconds: hostMemoryTtlSeconds,
      max_pages: 10,
      max_scrolls: 10,
    },
    locality_profile: {
      geo_country: 'auto',
      language_hint: null,
      currency_hint: null,
    },
    diagnostics_profile: {
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'matched_only' as const,
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    },
    source_run_id: 11,
    saved_at: '2026-04-23T00:00:00Z',
  };
}

describe('CrawlConfigScreen bulk prefill', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.sessionStorage.clear();
    globalThis.history.replaceState(null, '', '/');
    getDomainRunProfileMock.mockResolvedValue({
      domain: 'example.com',
      surface: 'ecommerce_listing',
      saved_run_profile: null,
    });
    listSelectorsMock.mockResolvedValue([]);
    createCrawlMock.mockResolvedValue({ run_id: 321 });
  });
  it('restores the jobs domain from batch prefill storage', async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        domain: 'jobs',
        urls: ['https://jobs.example.com/posting/1'],
      }),
    );
    renderConfigScreen();
    expect(screen.getByRole('button', { name: 'Batch' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Bulk URLs input')).toHaveValue(
      'https://jobs.example.com/posting/1',
    );
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith('/crawl?module=pdp&mode=batch', { replace: true });
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Domain' })).toHaveTextContent('Jobs');
    });

    expect(screen.getByLabelText('Bulk URLs input')).toHaveValue(
      'https://jobs.example.com/posting/1',
    );
    expect(screen.getByRole('button', { name: 'Batch' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('loads domain memory as soon as the target URL is entered', async () => {
    listSelectorsMock.mockResolvedValue([
      {
        id: 7,
        domain: 'example.com',
        surface: 'ecommerce_listing',
        field_name: 'price',
        css_selector: '.product-price',
        xpath: null,
        regex: null,
        status: 'validated',
        source: 'domain_memory',
        is_active: true,
        created_at: '2026-04-23T00:00:00Z',
        updated_at: '2026-04-23T00:00:00Z',
      },
    ]);

    renderConfigScreen();

    enterTargetUrl('https://example.com/collections/chairs');

    await expectDomainProfileLookup('https://example.com/collections/chairs');
    await waitFor(() => {
      expect(listSelectorsMock).toHaveBeenCalledWith(
        { domain: 'example.com', surface: 'ecommerce_listing' },
        { signal: expect.any(AbortSignal) },
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));

    expect(await screen.findByDisplayValue('price')).toBeInTheDocument();
    expect(
      screen.queryByText('Loaded 1 saved selector from domain memory.'),
    ).not.toBeInTheDocument();
  });

  it('does not apply proxy defaults from the saved domain run profile', async () => {
    getDomainRunProfileMock.mockResolvedValue({
      domain: 'example.com',
      surface: 'ecommerce_listing',
      saved_run_profile: savedProfile(1800),
    });

    renderConfigScreen();

    enterTargetUrl('https://example.com/collections/chairs');

    await expectDomainProfileLookup('https://example.com/collections/chairs');

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));

    await waitFor(() => {
      expect(screen.queryByLabelText('Proxy pool input')).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText('Host memory TTL seconds')).toHaveValue(1800);
  });

  it('resets a saved profile while a different domain profile is loading', async () => {
    let resolveSecondProfile!: (value: unknown) => void;
    getDomainRunProfileMock.mockImplementation(({ url }: { url: string }) => {
      if (url.includes('first.example')) {
        return Promise.resolve({
          domain: 'first.example',
          surface: 'ecommerce_listing',
          saved_run_profile: savedProfile(1800),
        });
      }
      return new Promise((resolve) => {
        resolveSecondProfile = resolve;
      });
    });

    renderConfigScreen();
    enterTargetUrl('https://first.example/collections/chairs');
    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    await waitFor(() => {
      expect(screen.getByLabelText('Host memory TTL seconds')).toHaveValue(1800);
    });

    enterTargetUrl('https://second.example/collections/desks');
    await waitFor(() => {
      expect(getDomainRunProfileMock).toHaveBeenCalledWith(
        {
          url: 'https://second.example/collections/desks',
          surface: 'ecommerce_listing',
        },
        { signal: expect.any(AbortSignal) },
      );
    });
    expect(screen.getByLabelText('Host memory TTL seconds')).toHaveValue(null);

    resolveSecondProfile({
      domain: 'second.example',
      surface: 'ecommerce_listing',
      saved_run_profile: null,
    });
  });

  it('preserves explicit profile edits when a saved profile resolves later', async () => {
    let resolveProfile!: (value: unknown) => void;
    getDomainRunProfileMock.mockReturnValue(
      new Promise((resolve) => {
        resolveProfile = resolve;
      }),
    );

    renderConfigScreen();
    enterTargetUrl('https://example.com/collections/chairs');
    await waitFor(() => expect(getDomainRunProfileMock).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    fireEvent.change(screen.getByLabelText('Host memory TTL seconds'), {
      target: { value: '600' },
    });

    resolveProfile({
      domain: 'example.com',
      surface: 'ecommerce_listing',
      saved_run_profile: savedProfile(1800),
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Host memory TTL seconds')).toHaveValue(600);
    });
  });

  it('refreshes the route after launching a crawl so the new run screen loads immediately', async () => {
    renderConfigScreen();

    enterTargetUrl('https://example.com/collections/chairs');

    fireEvent.click(screen.getByRole('button', { name: 'Start Crawl' }));

    await waitFor(() => {
      expect(createCrawlMock).toHaveBeenCalled();
      expect(replaceMock).toHaveBeenCalledWith('/crawl?run_id=321', { replace: true });
    });
  });

  it('rejects an invalid target URL before dispatching a crawl', async () => {
    renderConfigScreen();

    enterTargetUrl('not-a-url');
    fireEvent.click(screen.getByRole('button', { name: 'Start Crawl' }));

    expect(await screen.findByText('Must be a valid URL.')).toBeInTheDocument();
    expect(createCrawlMock).not.toHaveBeenCalled();
  });
});
