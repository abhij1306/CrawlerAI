import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { TopBarProvider, useTopBarHeader } from '../../components/layout/top-bar-context';
import DomainMemoryPage from './page-view';

const apiMock = vi.hoisted(() => ({
  listSelectorSummaries: vi.fn(),
  listSelectors: vi.fn(),
  listDomainRunProfiles: vi.fn(),
  listDomainCookieMemory: vi.fn(),
  listDomainFieldFeedback: vi.fn(),
  listKnowledgeSites: vi.fn(),
  getKnowledgeGraph: vi.fn(),
  listKnowledgeContractsByDomain: vi.fn(),
  listKnowledgeContracts: vi.fn(),
  selectKnowledgeContractSource: vi.fn(),
  getRunReport: vi.fn(),
  getResultDiagnosis: vi.fn(),
  listCrawls: vi.fn(),
  resetDomainMemory: vi.fn(),
  saveDomainRunProfile: vi.fn(),
  updateSelector: vi.fn(),
  deleteSelector: vi.fn(),
  deleteSelectorsByDomain: vi.fn(),
}));

vi.mock('../../lib/api/crawls', () => ({
  crawlsApi: {
    listCrawls: apiMock.listCrawls,
    getRunReport: apiMock.getRunReport,
    getResultDiagnosis: apiMock.getResultDiagnosis,
  },
}));

vi.mock('../../lib/api/dashboard', () => ({
  dashboardApi: {
    resetDomainMemory: apiMock.resetDomainMemory,
  },
}));

vi.mock('../../lib/api/domain-memory', () => ({
  domainMemoryApi: {
    listDomainRunProfiles: apiMock.listDomainRunProfiles,
    listDomainCookieMemory: apiMock.listDomainCookieMemory,
    listDomainFieldFeedback: apiMock.listDomainFieldFeedback,
    saveDomainRunProfile: apiMock.saveDomainRunProfile,
  },
}));

vi.mock('../../lib/api/knowledge', () => ({
  knowledgeApi: {
    listKnowledgeSites: apiMock.listKnowledgeSites,
    getKnowledgeGraph: apiMock.getKnowledgeGraph,
    listKnowledgeContractsByDomain: apiMock.listKnowledgeContractsByDomain,
    listKnowledgeContracts: apiMock.listKnowledgeContracts,
    selectKnowledgeContractSource: apiMock.selectKnowledgeContractSource,
  },
}));

vi.mock('../../lib/api/selectors', () => ({
  selectorsApi: {
    listSelectorSummaries: apiMock.listSelectorSummaries,
    listSelectors: apiMock.listSelectors,
    updateSelector: apiMock.updateSelector,
    deleteSelector: apiMock.deleteSelector,
    deleteSelectorsByDomain: apiMock.deleteSelectorsByDomain,
  },
}));

function HeaderActions() {
  const header = useTopBarHeader();
  return <>{header?.actions ?? null}</>;
}

function renderDomainMemoryPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TopBarProvider>
          <DomainMemoryPage />
          <HeaderActions />
        </TopBarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DomainMemoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listSelectorSummaries.mockResolvedValue([
      {
        domain: 'example.com',
        surface: 'ecommerce_detail',
        selector_count: 1,
        updated_at: new Date('2026-04-08T10:00:00Z').toISOString(),
      },
    ]);
    apiMock.listSelectors.mockResolvedValue([
      {
        id: 11,
        domain: 'example.com',
        surface: 'ecommerce_detail',
        field_name: 'price',
        css_selector: '.price',
        xpath: null,
        regex: null,
        status: 'validated',
        sample_value: '$19.99',
        source: 'domain_recipe',
        source_run_id: 101,
        is_active: true,
        created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
        updated_at: new Date('2026-04-08T10:00:00Z').toISOString(),
      },
    ]);
    apiMock.listDomainRunProfiles.mockResolvedValue([
      {
        id: 7,
        domain: 'example.com',
        surface: 'ecommerce_detail',
        profile: {
          version: 1,
          fetch_profile: {
            fetch_mode: 'http_then_browser',
            extraction_source: 'rendered_dom',
            js_mode: 'enabled',
            include_iframes: false,
            traversal_mode: 'paginate',
            request_delay_ms: 1200,
            host_memory_ttl_seconds: 1800,
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
          source_run_id: 101,
          saved_at: new Date('2026-04-08T10:05:00Z').toISOString(),
        },
        created_at: new Date('2026-04-08T10:05:00Z').toISOString(),
        updated_at: new Date('2026-04-08T10:05:00Z').toISOString(),
      },
    ]);
    apiMock.listDomainCookieMemory.mockResolvedValue([
      {
        id: 4,
        domain: 'example.com',
        cookie_count: 3,
        origin_count: 1,
        updated_at: new Date('2026-04-08T10:05:00Z').toISOString(),
      },
      {
        id: 5,
        domain: 'owned-session-test.example.com',
        cookie_count: 1,
        origin_count: 0,
        updated_at: new Date('2026-04-08T10:05:00Z').toISOString(),
      },
    ]);
    apiMock.listDomainFieldFeedback.mockResolvedValue([
      {
        id: 5,
        domain: 'example.com',
        surface: 'ecommerce_detail',
        field_name: 'price',
        action: 'keep',
        source_kind: 'selector',
        source_value: '.price',
        source_run_id: 101,
        selector_kind: 'css_selector',
        selector_value: '.price',
        source_record_ids: [1],
        created_at: new Date('2026-04-08T10:06:00Z').toISOString(),
      },
    ]);
    apiMock.listKnowledgeSites.mockResolvedValue({
      sites: [
        {
          id: 'site-1',
          domain: 'example.com',
          current_version: 4,
          projection_status: 'projected',
          last_projected_run_id: 101,
          last_projected_at: new Date('2026-04-08T10:11:00Z').toISOString(),
        },
      ],
    });
    apiMock.getKnowledgeGraph.mockResolvedValue({
      bounds: { depth: 2, limit: 200 },
      nodes: [
        {
          id: 'template-1',
          entity_type: 'page_template',
          canonical_key: 'example.com:ecommerce_detail:fp',
          canonical_name: 'Product template',
          properties: { route_pattern: '/products/{id}' },
          status: 'active',
        },
        {
          id: 'product-1',
          entity_type: 'product',
          canonical_key: 'example.com:product:sku-1',
          canonical_name: 'Widget',
          properties: {},
          status: 'active',
        },
      ],
      relationships: [
        {
          id: 'rel-1',
          source_entity_id: 'template-1',
          target_entity_id: 'product-1',
          relationship_type: 'PAGE_MENTIONS_PRODUCT',
          properties: {},
          confidence: 1,
          status: 'active',
        },
      ],
    });
    apiMock.listKnowledgeContractsByDomain.mockResolvedValue({
      domain: 'example.com',
      contracts: [
        {
          id: 'contract-1',
          template_id: 'template-1',
          surface: 'ecommerce_detail',
          canonical_field: 'product.brand',
          candidates: [{ source: 'jsonld:/brand' }, { source: 'css_recipe:.brand' }],
          latest_values: [],
          success_count: 3,
          rejection_count: 1,
          resolver_rule: 'operator_selector',
          selected_source: 'jsonld:/brand',
          selection_origin: 'generic',
          selection_history: [],
          status: 'active',
        },
        {
          id: 'contract-brand-second-template',
          template_id: 'template-2',
          surface: 'ecommerce_detail',
          canonical_field: 'product.brand',
          candidates: [{ source: 'jsonld:/brand' }, { source: 'css_recipe:.brand' }],
          latest_values: [],
          success_count: 2,
          rejection_count: 0,
          resolver_rule: 'brand_resolution',
          selected_source: 'jsonld:/brand',
          selection_origin: 'generic',
          selection_history: [],
          status: 'active',
        },
        {
          id: 'contract-price',
          template_id: 'template-1',
          surface: 'ecommerce_detail',
          canonical_field: 'offer.price',
          candidates: [
            { source: 'dom:[data-price]' },
            { source: 'dom:[data-price]' },
            { source: 'dom:[data-price]' },
          ],
          latest_values: [],
          success_count: 1,
          rejection_count: 2,
          resolver_rule: 'price_resolution',
          selected_source: 'dom:[data-price]',
          selection_origin: 'generic',
          selection_history: [],
          status: 'active',
        },
      ],
    });
    apiMock.selectKnowledgeContractSource.mockImplementation(
      (_contractId: string, payload: Record<string, unknown>) =>
        Promise.resolve({
          contract: {
            id: 'contract-1',
            template_id: 'template-1',
            surface: 'ecommerce_detail',
            canonical_field: 'product.brand',
            candidates: [{ source: 'jsonld:/brand' }, { source: 'css_recipe:.brand' }],
            latest_values: [],
            success_count: 3,
            rejection_count: 1,
            resolver_rule: 'operator_selector',
            selected_source: String(payload.selected_source),
            selection_origin: 'operator',
            selection_history: [{ selected_source: String(payload.selected_source) }],
            status: 'active',
          },
        }),
    );
    apiMock.listCrawls.mockResolvedValue({
      items: [
        {
          id: 101,
          user_id: 1,
          run_type: 'crawl',
          url: 'https://example.com/products/widget',
          status: 'completed',
          surface: 'ecommerce_detail',
          settings: {},
          requested_fields: [],
          result_summary: { domain: 'example.com' },
          run_health: {},
          created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
          updated_at: new Date('2026-04-08T10:10:00Z').toISOString(),
          completed_at: new Date('2026-04-08T10:10:00Z').toISOString(),
        },
      ],
      meta: { page: 1, limit: 200, total: 1 },
    });
    apiMock.updateSelector.mockImplementation((_id: number, payload: Record<string, unknown>) =>
      Promise.resolve({
        id: 11,
        domain: 'example.com',
        surface: 'ecommerce_detail',
        field_name: String(payload.field_name ?? 'price'),
        css_selector: payload.css_selector ?? '.price',
        xpath: payload.xpath ?? null,
        regex: payload.regex ?? null,
        status: 'validated',
        sample_value: '$19.99',
        source: String(payload.source ?? 'domain_recipe'),
        source_run_id: 101,
        is_active: Boolean(payload.is_active ?? true),
        created_at: new Date('2026-04-08T10:00:00Z').toISOString(),
        updated_at: new Date('2026-04-08T10:10:00Z').toISOString(),
      }),
    );
    apiMock.saveDomainRunProfile.mockResolvedValue({
      version: 1,
      fetch_profile: {
        fetch_mode: 'browser_only',
        extraction_source: 'rendered_dom',
        js_mode: 'enabled',
        include_iframes: false,
        traversal_mode: 'paginate',
        request_delay_ms: 1200,
        host_memory_ttl_seconds: 600,
        max_pages: 8,
        max_scrolls: 12,
      },
      locality_profile: {
        geo_country: 'US',
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
        preferred_browser_engine: 'auto',
        prefer_browser: false,
        handoff_eligible: false,
        handoff_cookie_engine: 'auto',
        required_rendering: false,
        required_traversal: false,
        required_network_payloads: false,
        last_quality_success: null,
        stale_after_failures: {
          failure_count: 0,
          stale: false,
        },
      },
      source_run_id: 101,
      saved_at: new Date('2026-04-08T10:05:00Z').toISOString(),
    });
    apiMock.resetDomainMemory.mockResolvedValue({
      domain_memory_deleted: 1,
      domain_run_profiles_deleted: 1,
      domain_cookie_memory_deleted: 1,
      domain_field_feedback_deleted: 1,
      host_protection_memory_deleted: 1,
      cookies_removed: 1,
    });
    apiMock.deleteSelector.mockResolvedValue(undefined);
    apiMock.deleteSelectorsByDomain.mockResolvedValue({ deleted: 1 });
    apiMock.getRunReport.mockResolvedValue({
      schema_version: 'run-report.v1',
      run_id: 101,
      root_cause_count: 0,
      root_causes: [],
    });
    apiMock.getResultDiagnosis.mockResolvedValue({
      schema_version: 'diagnose.v2',
      verdict: 'partial',
      fields: [],
    });
  });

  it('renders the selected domain memory workspace and recent learning', async () => {
    renderDomainMemoryPage();

    expect(await screen.findByRole('button', { name: 'Profiles (1)' })).toBeInTheDocument();
    expect(screen.getAllByText('example.com').length).toBeGreaterThan(0);

    expect(screen.getByRole('button', { name: 'Profiles (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cookies (3)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Learning (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Extraction' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selectors' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Profiles (1)' }));
    expect(screen.getByText('Run Profile Defaults')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cookies (3)' }));
    expect(screen.getByText('Saved Domain Cookies')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Learning (1)' }));
    expect(screen.getByText('Recent Learning')).toBeInTheDocument();

    expect(screen.queryByText('owned-session-test.example.com')).not.toBeInTheDocument();
  }, 10_000);

  it('shows extraction preferences without runtime internals', async () => {
    apiMock.listKnowledgeContractsByDomain.mockResolvedValue({
      domain: 'example.com',
      contracts: [],
    });
    renderDomainMemoryPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Extraction' }));
    expect(await screen.findByText('Extraction preferences')).toBeInTheDocument();
    expect(await screen.findByText('No extraction preferences yet')).toBeInTheDocument();
    expect(screen.queryByText('Extraction runtime')).not.toBeInTheDocument();
    expect(screen.queryByText('Build from past crawls')).not.toBeInTheDocument();
  });

  it('renders Knowledge Graph tab and updates source selection', async () => {
    renderDomainMemoryPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Extraction' }));

    expect(await screen.findByText('Extraction preferences')).toBeInTheDocument();
    expect(await screen.findByText('Field defaults')).toBeInTheDocument();
    expect(screen.getAllByText('example.com').length).toBeGreaterThan(0);
    expect(screen.queryByText('Run diagnostics')).not.toBeInTheDocument();
    expect(screen.getAllByText('Brand').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('combobox', { name: 'Source for product.brand' })).toHaveLength(1);
    expect(screen.getAllByText('Automatic').length).toBeGreaterThan(0);
    expect(screen.getByText('Only observed source')).toBeInTheDocument();
    expect(
      screen.queryByRole('combobox', { name: 'Source for offer.price' }),
    ).not.toBeInTheDocument();

    apiMock.listKnowledgeSites.mockResolvedValue({
      sites: [
        {
          id: 'site-1',
          domain: 'example.com',
          current_version: 5,
          projection_status: 'pending',
          last_projected_run_id: 101,
          last_projected_at: new Date('2026-04-08T10:11:00Z').toISOString(),
        },
      ],
    });
    const extractionPanel = screen
      .getByRole('heading', { name: 'Extraction preferences' })
      .closest('.p-0');
    expect(extractionPanel).not.toBeNull();
    fireEvent.click(
      within(extractionPanel as HTMLElement).getByRole('button', { name: 'Refresh' }),
    );
    await waitFor(() => {
      expect(apiMock.listKnowledgeContractsByDomain).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText('Version 5')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'Source for product.brand' }), {
      target: { value: 'css_recipe:.brand' },
    });

    await waitFor(() => {
      expect(apiMock.selectKnowledgeContractSource).toHaveBeenCalledWith('contract-1', {
        selected_source: 'css_recipe:.brand',
        expected_version: 5,
        template_id: 'template-1',
        surface: 'ecommerce_detail',
        canonical_field: 'product.brand',
      });
    });
    expect(screen.getByText('Saved for this surface')).toBeInTheDocument();
  }, 10_000);

  it('keeps domain memory usable when Knowledge Graph site loading fails', async () => {
    apiMock.listKnowledgeSites.mockRejectedValue(new Error('Knowledge Graph unavailable'));

    renderDomainMemoryPage();

    expect(await screen.findByRole('button', { name: 'Profiles (1)' })).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph unavailable')).toBeInTheDocument();
  });

  it('edits and saves a domain run profile from domain memory', async () => {
    renderDomainMemoryPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Profiles (1)' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Fetch Mode' }), {
      target: { value: 'browser_only' },
    });
    fireEvent.change(screen.getByLabelText('Host Memory TTL (s)'), { target: { value: '600' } });
    fireEvent.change(screen.getByDisplayValue('IN'), { target: { value: 'US' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Profile' }));

    await waitFor(() => {
      expect(apiMock.saveDomainRunProfile).toHaveBeenCalledWith(101, {
        profile: expect.objectContaining({
          fetch_profile: expect.objectContaining({
            fetch_mode: 'browser_only',
            host_memory_ttl_seconds: 600,
          }),
          locality_profile: expect.objectContaining({
            geo_country: 'US',
          }),
        }),
      });
    });
  });

  it('resets domain memory from the top bar action', async () => {
    renderDomainMemoryPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Reset Domain Memory' }));
    expect(screen.getByText('Reset domain memory')).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Reset Domain Memory' }),
    );

    await waitFor(() => {
      expect(apiMock.resetDomainMemory).toHaveBeenCalledTimes(1);
    });
  });
});
