import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { UI_DELAYS } from '../../lib/constants/timing';
import { TopBarProvider } from '../layout/top-bar-context';
import { CrawlConfigScreen } from './crawl-config-screen';

const {
  replaceMock,
  refreshMock,
  createCsvCrawlMock,
  createCrawlMock,
  createPageAuditJobMock,
  getDomainRunProfileMock,
  listSelectorsMock,
} = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  refreshMock: vi.fn(),
  createCsvCrawlMock: vi.fn(),
  createCrawlMock: vi.fn(),
  createPageAuditJobMock: vi.fn(),
  getDomainRunProfileMock: vi.fn(),
  listSelectorsMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/crawl',
  useRouter: () => ({
    replace: replaceMock,
    refresh: refreshMock,
  }),
}));

vi.mock('../../lib/api', () => ({
  api: {
    createCsvCrawl: createCsvCrawlMock,
    createCrawl: createCrawlMock,
    createPageAuditJob: createPageAuditJobMock,
    getDomainRunProfile: getDomainRunProfileMock,
    listSelectors: listSelectorsMock,
  },
}));

function renderConfigScreen() {
  render(
    <TopBarProvider>
      <CrawlConfigScreen requestedTab={null} requestedCategoryMode={null} requestedPdpMode={null} />
    </TopBarProvider>,
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
      expect(getDomainRunProfileMock).toHaveBeenCalledWith({
        url,
        surface,
      });
    },
    { timeout: UI_DELAYS.DEBOUNCE_MS * 6 },
  );
}

describe('CrawlConfigScreen bulk prefill', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    window.history.replaceState(null, '', '/');
    getDomainRunProfileMock.mockResolvedValue({
      domain: 'example.com',
      surface: 'ecommerce_listing',
      saved_run_profile: null,
    });
    listSelectorsMock.mockResolvedValue([]);
    createCrawlMock.mockResolvedValue({ run_id: 321 });
    createPageAuditJobMock.mockResolvedValue({ id: 41 });
  });
  it('restores the jobs domain from batch prefill storage', async () => {
    window.sessionStorage.setItem(
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
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        '/crawl?module=pdp&mode=batch',
      );
    });
    expect(replaceMock).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Domain' })).toHaveTextContent('Jobs');
    });

    expect(screen.getByLabelText('Bulk URLs input')).toHaveValue(
      'https://jobs.example.com/posting/1',
    );
    expect(screen.getByRole('button', { name: 'Batch' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps pdp batch prefill active for non-picker domains', async () => {
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        domain: 'automobiles',
        urls: ['https://cars.example.com/listing/1'],
      }),
    );

    renderConfigScreen();

    await waitFor(() => {
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        '/crawl?module=pdp&mode=batch',
      );
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Domain' })).toHaveTextContent('Automobiles');
    });

    expect(screen.getByLabelText('Bulk URLs input')).toHaveValue(
      'https://cars.example.com/listing/1',
    );
    expect(screen.queryByLabelText('Target URL input')).not.toBeInTheDocument();
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
      expect(listSelectorsMock).toHaveBeenCalledWith({ domain: 'example.com' });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));

    expect(await screen.findByDisplayValue('price')).toBeInTheDocument();
    expect(
      screen.queryByText('Loaded 1 saved selector from domain memory.'),
    ).not.toBeInTheDocument();
  });

  it('launches design crawls from the target URL', async () => {
    renderConfigScreen();

    enterTargetUrl('https://example.com/');
    fireEvent.click(screen.getByRole('button', { name: 'Design Crawl' }));

    await waitFor(() => {
      expect(createCrawlMock).toHaveBeenCalledWith(
        expect.objectContaining({
          run_type: 'crawl',
          url: 'https://example.com/',
          surface: 'design_system',
          additional_fields: [],
          settings: expect.objectContaining({
            llm_enabled: true,
            respect_robots_txt: expect.any(Boolean),
            fetch_profile: expect.objectContaining({
              fetch_mode: 'browser_only',
              extraction_source: 'rendered_dom_visual',
              traversal_mode: null,
            }),
          }),
        }),
      );
    });
    expect(replaceMock).toHaveBeenCalledWith('/crawl?run_id=321');
  });

  it('runs page audit from the Crawl Studio audit mode', async () => {
    renderConfigScreen();

    fireEvent.click(screen.getByRole('button', { name: 'Audit' }));
    enterTargetUrl('https://example.com/about');
    fireEvent.click(screen.getByRole('button', { name: 'Start Audit' }));

    await waitFor(() => {
      expect(createPageAuditJobMock).toHaveBeenCalledWith({
        url: 'https://example.com/about',
        context: 'auto',
      });
    });
    expect(replaceMock).toHaveBeenCalledWith('/crawl?audit_job_id=41');
  });

  it('does not expose sitemap controls while auto surface is selected', async () => {
    render(
      <TopBarProvider>
        <CrawlConfigScreen
          requestedTab="category"
          requestedCategoryMode="sitemap"
          requestedPdpMode={null}
        />
      </TopBarProvider>,
    );

    expect(screen.queryByLabelText('Sitemap domain input')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Sitemap filter keyword input')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Sitemap max URLs input')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Target URL input')).toBeInTheDocument();
  });

  it('does not apply proxy defaults from the saved domain run profile', async () => {
    getDomainRunProfileMock.mockResolvedValue({
      domain: 'example.com',
      surface: 'ecommerce_listing',
      saved_run_profile: {
        version: 1,
        fetch_profile: {
          fetch_mode: 'browser_only',
          extraction_source: 'raw_html',
          js_mode: 'auto',
          include_iframes: false,
          traversal_mode: null,
          request_delay_ms: 500,
          host_memory_ttl_seconds: 1800,
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
          capture_network: 'matched_only',
          capture_response_headers: true,
          capture_browser_diagnostics: true,
        },
        source_run_id: 11,
        saved_at: '2026-04-23T00:00:00Z',
      },
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

  it('refreshes the route after launching a crawl so the new run screen loads immediately', async () => {
    renderConfigScreen();

    enterTargetUrl('https://example.com/collections/chairs');

    fireEvent.click(screen.getByRole('button', { name: 'Start Crawl' }));

    await waitFor(() => {
      expect(createCrawlMock).toHaveBeenCalled();
      expect(replaceMock).toHaveBeenCalledWith('/crawl?run_id=321');
      expect(refreshMock).toHaveBeenCalledTimes(1);
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
