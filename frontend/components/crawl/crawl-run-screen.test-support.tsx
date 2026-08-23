import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { queryKeys } from '@/api/query-keys';
import type { CrawlLog, CrawlRecord, CrawlRun, DomainRecipe } from '../../lib/api/types';
import { POLLING_INTERVALS, WEBSOCKET_RECONNECT } from '../../lib/constants/timing';
import { storeProductIntelligencePrefill } from '../../lib/crawl/prefill';
import { TopBarProvider } from '../layout/top-bar-context';
import { CrawlRunScreen } from './crawl-run-screen';
import { LogTerminal } from './log-terminal';

export {
  QueryClient,
  act,
  describe,
  expect,
  fireEvent,
  it,
  LogTerminal,
  POLLING_INTERVALS,
  queryKeys,
  render,
  screen,
  storeProductIntelligencePrefill,
  vi,
  waitFor,
  WEBSOCKET_RECONNECT,
};
export type { CrawlLog, CrawlRecord, CrawlRun, DomainRecipe };

const sharedMocks = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  pushMock: vi.fn(),
  routeMock: { searchParams: 'run_id=42' },
  apiMock: {
    getCrawl: vi.fn(),
    listCrawls: vi.fn(),
    getRecords: vi.fn(),
    getCrawlLogs: vi.fn(),
    killCrawl: vi.fn(),
    getDomainRecipe: vi.fn(),
    saveGroundedCorrection: vi.fn(),
    exportCsv: vi.fn(() => '/export.csv'),
    exportJson: vi.fn(() => '/export.json'),
  },
}));

export const { apiMock, pushMock, replaceMock, routeMock } = sharedMocks;

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  const React = await import('react');
  return {
    ...actual,
    useLocation: () => ({
      pathname: '/crawl',
      search: `?${sharedMocks.routeMock.searchParams}`,
      hash: '',
      state: null,
      key: 'test',
    }),
    useNavigate: () => (to: string, options?: { replace?: boolean }) =>
      options?.replace ? sharedMocks.replaceMock(to, options) : sharedMocks.pushMock(to),
    useSearchParams: () => {
      const [params, setParamsState] = React.useState(
        () => new URLSearchParams(sharedMocks.routeMock.searchParams),
      );
      const setParams = React.useCallback(
        (nextParams: URLSearchParams | ((current: URLSearchParams) => URLSearchParams)) => {
          setParamsState((current: URLSearchParams) =>
            typeof nextParams === 'function'
              ? new URLSearchParams(nextParams(current))
              : new URLSearchParams(nextParams),
          );
        },
        [],
      );
      return [params, setParams] as const;
    },
  };
});

export class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

vi.mock('../../lib/api/crawls', () => ({
  crawlsApi: {
    getCrawl: sharedMocks.apiMock.getCrawl,
    listCrawls: sharedMocks.apiMock.listCrawls,
    getRecords: sharedMocks.apiMock.getRecords,
    getCrawlLogs: sharedMocks.apiMock.getCrawlLogs,
    killCrawl: sharedMocks.apiMock.killCrawl,
    saveGroundedCorrection: sharedMocks.apiMock.saveGroundedCorrection,
    exportCsv: sharedMocks.apiMock.exportCsv,
    exportJson: sharedMocks.apiMock.exportJson,
  },
}));

vi.mock('../../lib/api/domain-memory', () => ({
  domainMemoryApi: {
    getDomainRecipe: sharedMocks.apiMock.getDomainRecipe,
  },
}));

export function terminalRun(runId: number): CrawlRun {
  return {
    id: runId,
    user_id: 1,
    run_type: 'crawl',
    url: 'https://example.com/products/chair',
    status: 'completed',
    surface: 'ecommerce_detail',
    settings: {},
    requested_fields: [],
    result_summary: {
      extraction_verdict: 'success',
      record_count: 2,
    },
    run_health: {},
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
    updated_at: new Date('2026-04-08T10:05:00Z').toISOString(),
    completed_at: new Date('2026-04-08T10:05:00Z').toISOString(),
  };
}

export function runningRun(runId: number): CrawlRun {
  return {
    id: runId,
    user_id: 1,
    run_type: 'crawl',
    url: 'https://example.com/products/chair',
    status: 'running',
    surface: 'ecommerce_detail',
    settings: {},
    requested_fields: [],
    result_summary: {
      extraction_verdict: 'unknown',
      progress: 0,
      record_count: 0,
      current_url_index: 1,
      total_urls: 5,
    },
    run_health: {},
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
    updated_at: new Date('2026-04-08T10:01:00Z').toISOString(),
    completed_at: null,
  };
}

export function makeRecord(id: number): CrawlRecord {
  return {
    id,
    run_id: 101,
    source_url: `https://example.com/p/${id}`,
    data: { title: `Item ${id}`, url: `https://example.com/p/${id}` },
    raw_data: {},
    discovered_data: {},
    source_trace: {},
    raw_html_path: null,
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
  };
}

export function makeLog(id: number, message: string, level = 'info'): CrawlLog {
  return {
    id,
    level,
    message,
    created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
  };
}

export function makeDomainRecipe(): DomainRecipe {
  return {
    run_id: 101,
    domain: 'example.com',
    surface: 'ecommerce_detail',
    requested_field_coverage: {
      requested: ['title', 'price', 'brand'],
      found: ['title', 'price'],
      missing: ['brand'],
    },
    acquisition_evidence: {
      actual_fetch_method: 'browser',
      browser_used: true,
      browser_reason: 'http-escalation',
      acquisition_summary: {
        browser_used_urls: 1,
        acquisition_ms_total: 4200,
      },
      cookie_memory_available: true,
    },
    field_learning: [
      {
        field_name: 'price',
        value: 'Rs. 999',
        source_labels: ['dom_selector'],
        selector_kind: 'css_selector',
        selector_value: '.price',
        source_record_ids: [1],
        representative_url_result_ids: [11],
        feedback: null,
      },
    ],
    selector_candidates: [
      {
        candidate_key: 'price|css_selector|.price',
        field_name: 'price',
        selector_kind: 'css_selector',
        selector_value: '.price',
        selector_source: 'domain_memory',
        sample_value: 'Rs. 999',
        source_record_ids: [1],
        source_run_id: 101,
        saved_selector_id: null,
        already_saved: false,
        final_field_source: 'dom_selector',
      },
      {
        candidate_key: 'title|css_selector|.title',
        field_name: 'title',
        selector_kind: 'css_selector',
        selector_value: '.title',
        selector_source: 'domain_memory',
        sample_value: 'Chair Prime',
        source_record_ids: [1],
        source_run_id: 101,
        saved_selector_id: 22,
        already_saved: true,
        final_field_source: 'dom_selector',
      },
    ],
    affordance_candidates: {
      accordions: ['.details-accordion'],
      tabs: [],
      carousels: [],
      shadow_hosts: [],
      iframe_promotion: null,
      browser_required: true,
    },
    saved_selectors: [
      {
        id: 22,
        domain: 'example.com',
        surface: 'ecommerce_detail',
        field_name: 'title',
        css_selector: '.title',
        xpath: null,
        regex: null,
        status: 'validated',
        sample_value: 'Chair Prime',
        source: 'domain_recipe',
        source_run_id: 88,
        is_active: true,
        created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
        updated_at: new Date('2026-04-08T10:00:00Z').toISOString(),
      },
    ],
    saved_run_profile: {
      version: 1,
      fetch_profile: {
        fetch_mode: 'http_then_browser',
        extraction_source: 'rendered_dom',
        js_mode: 'enabled',
        include_iframes: false,
        traversal_mode: 'paginate',
        request_delay_ms: 1200,
        max_pages: 8,
        max_scrolls: 12,
      },
      locality_profile: {
        geo_country: 'IN',
        language_hint: 'en-IN',
        currency_hint: 'INR',
      },
      diagnostics_profile: {
        capture_html: true,
        capture_screenshot: false,
        capture_network: 'matched_only',
        capture_response_headers: true,
        capture_browser_diagnostics: true,
      },
      acquisition_contract: {
        preferred_browser_engine: 'real_chrome',
        prefer_browser: true,
        handoff_eligible: true,
        required_rendering: false,
        required_traversal: false,
        required_network_payloads: false,
        handoff_cookie_engine: 'real_chrome',
        last_quality_success: null,
        stale_after_failures: {
          failure_count: 0,
          stale: false,
        },
      },
      source_run_id: 101,
      saved_at: '2026-04-08T10:05:00Z',
    },
  };
}

export function renderRunScreen(runId = 101) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <TopBarProvider>
        <CrawlRunScreen runId={runId} />
      </TopBarProvider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

export function renderRunScreenWithClient(queryClient: QueryClient, runId = 101) {
  render(
    <QueryClientProvider client={queryClient}>
      <TopBarProvider>
        <CrawlRunScreen runId={runId} />
      </TopBarProvider>
    </QueryClientProvider>,
  );
}

export function registerCrawlRunScreenTestLifecycle() {
  let originalUserAgentDescriptor: PropertyDescriptor | undefined;

  afterEach(() => {
    if (originalUserAgentDescriptor) {
      Object.defineProperty(window.navigator, 'userAgent', originalUserAgentDescriptor);
    } else {
      Reflect.deleteProperty(window.navigator as Navigator & Record<string, unknown>, 'userAgent');
    }
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    originalUserAgentDescriptor = Object.getOwnPropertyDescriptor(window.navigator, 'userAgent');
    vi.clearAllMocks();
    routeMock.searchParams = 'run_id=42';
    MockWebSocket.instances = [];
    window.sessionStorage.clear();
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
    Object.defineProperty(window.navigator, 'userAgent', {
      configurable: true,
      value: 'Mozilla/5.0',
    });
    apiMock.getCrawl.mockResolvedValue(terminalRun(101));
    apiMock.listCrawls.mockResolvedValue({
      items: [],
      meta: { page: 1, limit: 20, total: 0 },
    });
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        const limit = params?.limit ?? 100;
        const total = 2;
        return {
          items: Array.from({ length: Math.min(limit, total) }, (_, index) =>
            makeRecord(index + 1),
          ),
          meta: { page: 1, limit, total },
        };
      },
    );
    apiMock.getCrawlLogs.mockResolvedValue([]);
    apiMock.killCrawl.mockResolvedValue({ run_id: 101, status: 'killed' });
    apiMock.getDomainRecipe.mockResolvedValue(makeDomainRecipe());
    apiMock.saveGroundedCorrection.mockResolvedValue({
      correction_id: 1,
      domain: 'example.com',
      surface: 'ecommerce_detail',
      label_count: 1,
      activation_status: 'activated',
      replay: { passed: true },
    });
  });
}
