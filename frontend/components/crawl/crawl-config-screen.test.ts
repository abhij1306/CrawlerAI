import { describe, expect, it } from 'vitest';

import { buildDispatch, inferRunTypeHint } from './crawl-config-logic';
import type { FieldRow } from './shared';
import type { CrawlConfig, DomainRunProfile } from '../../lib/api/types';

type DomainRunProfileOverrides = {
  version?: number;
  fetch_profile?: Partial<DomainRunProfile['fetch_profile']>;
  locality_profile?: Partial<DomainRunProfile['locality_profile']>;
  diagnostics_profile?: Partial<DomainRunProfile['diagnostics_profile']>;
  acquisition_contract?: Partial<DomainRunProfile['acquisition_contract']>;
  source_run_id?: DomainRunProfile['source_run_id'];
  saved_at?: DomainRunProfile['saved_at'];
};

function baseConfig(overrides: Partial<CrawlConfig> = {}): CrawlConfig {
  return {
    module: 'category',
    domain: 'commerce',
    mode: 'single',
    target_url: 'https://example.com/collections/chairs',
    bulk_urls: '',
    csv_file: null,
    smart_extraction: false,
    max_records: 100,
    respect_robots_txt: true,
    proxy_enabled: false,
    proxy_lines: [],
    additional_fields: [],
    sitemap_domain: '',
    sitemap_filter_keyword: undefined,
    sitemap_max_urls: undefined,
    ...overrides,
  };
}

function baseProfile(overrides: DomainRunProfileOverrides = {}): DomainRunProfile {
  return {
    version: overrides.version ?? 1,
    fetch_profile: {
      fetch_mode: 'auto',
      extraction_source: 'raw_html',
      js_mode: 'auto',
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 2000,
      host_memory_ttl_seconds: null,
      ...overrides.fetch_profile,
    },
    locality_profile: {
      geo_country: 'auto',
      language_hint: null,
      currency_hint: null,
      ...overrides.locality_profile,
    },
    diagnostics_profile: {
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'matched_only',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
      ...overrides.diagnostics_profile,
    },
    acquisition_contract: {
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      prefer_curl_handoff: false,
      handoff_cookie_engine: 'auto',
      last_quality_success: null,
      stale_after_failures: {
        failure_count: 0,
        stale: false,
      },
      ...overrides.acquisition_contract,
    },
    source_run_id: overrides.source_run_id ?? null,
    saved_at: overrides.saved_at ?? null,
  };
}

describe('buildDispatch', () => {
  it('defaults category single runs to ecommerce listing surface', () => {
    const dispatch = buildDispatch(baseConfig(), [], { runProfile: baseProfile() });

    expect(dispatch.runType).toBe('crawl');
    expect(dispatch.surface).toBe('ecommerce_listing');
    expect(dispatch.url).toBe('https://example.com/collections/chairs');
  });

  it('keeps commerce listing when the URL is job-like', () => {
    const dispatch = buildDispatch(
      baseConfig({
        target_url: 'https://workforcenow.adp.com/careers',
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.surface).toBe('ecommerce_listing');
  });

  it('maps jobs category runs to job listing surface', () => {
    const dispatch = buildDispatch(
      baseConfig({
        domain: 'jobs',
        target_url: 'https://example.com/anything',
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.surface).toBe('job_listing');
  });

  it('uses the nested fetch profile in advanced mode', () => {
    const dispatch = buildDispatch(baseConfig(), [], {
      studioMode: 'advanced',
      runProfile: baseProfile({
        fetch_profile: {
          fetch_mode: 'http_then_browser',
          extraction_source: 'rendered_dom',
          js_mode: 'enabled',
          traversal_mode: 'paginate',
          request_delay_ms: 1500,
          host_memory_ttl_seconds: 300,
          include_iframes: true,
        },
        locality_profile: {
          geo_country: 'IN',
          language_hint: 'en-IN',
          currency_hint: 'INR',
        },
        diagnostics_profile: {
          capture_html: true,
          capture_screenshot: true,
          capture_network: 'all_small_json',
          capture_response_headers: true,
          capture_browser_diagnostics: true,
        },
      }),
    });

    expect(dispatch.settings.advanced_enabled).toBe(true);
    expect(dispatch.settings.advanced_mode).toBe('paginate');
    expect(dispatch.settings.fetch_profile).toMatchObject({
      fetch_mode: 'http_then_browser',
      extraction_source: 'rendered_dom',
      js_mode: 'enabled',
      include_iframes: true,
      traversal_mode: 'paginate',
      request_delay_ms: 1500,
      host_memory_ttl_seconds: 300,
    });
    expect(dispatch.settings.locality_profile).toEqual({
      geo_country: 'IN',
      language_hint: 'en-IN',
      currency_hint: 'INR',
    });
    expect(dispatch.settings.diagnostics_profile).toEqual({
      capture_html: true,
      capture_screenshot: true,
      capture_network: 'all_small_json',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    });
    expect(dispatch.settings.acquisition_contract).toEqual({
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      prefer_curl_handoff: false,
      handoff_cookie_engine: 'auto',
      last_quality_success: null,
      stale_after_failures: {
        failure_count: 0,
        stale: false,
      },
    });
    expect(dispatch.settings.proxy_profile).toEqual({
      enabled: false,
      proxy_list: [],
    });
  });

  it('carries a real Chrome browser engine preference into advanced settings', () => {
    const dispatch = buildDispatch(baseConfig(), [], {
      studioMode: 'advanced',
      runProfile: baseProfile({
        acquisition_contract: {
          preferred_browser_engine: 'real_chrome',
          prefer_browser: true,
          handoff_cookie_engine: 'real_chrome',
        },
      }),
    });

    expect(dispatch.settings.acquisition_contract).toMatchObject({
      preferred_browser_engine: 'real_chrome',
      prefer_browser: true,
      handoff_cookie_engine: 'real_chrome',
    });
  });

  it('keeps quick mode lean and disables advanced legacy flags', () => {
    const dispatch = buildDispatch(baseConfig(), [], {
      studioMode: 'quick',
      runProfile: baseProfile({
        fetch_profile: {
          fetch_mode: 'browser_only',
          traversal_mode: 'paginate',
        },
        diagnostics_profile: {
          capture_html: true,
          capture_screenshot: false,
          capture_network: 'off',
          capture_response_headers: true,
          capture_browser_diagnostics: true,
        },
      }),
    });

    expect(dispatch.settings.advanced_enabled).toBe(false);
    expect(dispatch.settings.advanced_mode).toBeNull();
    expect(dispatch.settings.fetch_profile).toMatchObject({
      fetch_mode: 'browser_only',
      traversal_mode: null,
    });
    expect(dispatch.settings.diagnostics_profile).toEqual({
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'off',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    });
  });

  it('carries proxy config into the nested proxy profile', () => {
    const dispatch = buildDispatch(
      baseConfig({
        proxy_enabled: true,
        proxy_lines: ['http://proxy-a', 'http://proxy-b'],
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.settings.proxy_enabled).toBe(true);
    expect(dispatch.settings.proxy_list).toEqual(['http://proxy-a', 'http://proxy-b']);
    expect(dispatch.settings.proxy_profile).toEqual({
      enabled: true,
      proxy_list: ['http://proxy-a', 'http://proxy-b'],
    });
  });

  it('persists the robots toggle in settings', () => {
    const dispatch = buildDispatch(
      baseConfig({
        respect_robots_txt: false,
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.settings.respect_robots_txt).toBe(false);
  });

  it('persists the llm toggle in settings', () => {
    const enabledDispatch = buildDispatch(
      baseConfig({
        smart_extraction: true,
      }),
      [],
      { runProfile: baseProfile() },
    );
    const disabledDispatch = buildDispatch(baseConfig(), [], { runProfile: baseProfile() });

    expect(enabledDispatch.settings.llm_enabled).toBe(true);
    expect(disabledDispatch.settings.llm_enabled).toBe(false);
  });

  it('submits pdp batch as ecommerce detail with URL list', () => {
    const dispatch = buildDispatch(
      baseConfig({
        module: 'pdp',
        mode: 'batch',
        target_url: '',
        bulk_urls: 'https://example.com/p/1\nhttps://example.com/p/2',
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.runType).toBe('batch');
    expect(dispatch.surface).toBe('ecommerce_detail');
    expect(dispatch.urls).toEqual(['https://example.com/p/1', 'https://example.com/p/2']);
    expect(dispatch.settings.urls).toEqual(['https://example.com/p/1', 'https://example.com/p/2']);
    expect(dispatch.settings.fetch_profile).toMatchObject({
      traversal_mode: null,
    });
  });

  it('submits category sitemap as listing batch without explicit urls', () => {
    const dispatch = buildDispatch(
      baseConfig({
        mode: 'sitemap',
        target_url: '',
        sitemap_domain: 'dashingdiva.com',
        sitemap_filter_keyword: 'collections',
        sitemap_max_urls: 250,
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.runType).toBe('batch');
    expect(dispatch.surface).toBe('ecommerce_listing');
    expect(dispatch.url).toBe('dashingdiva.com');
    expect(dispatch.urls).toBeUndefined();
    expect(dispatch.settings.urls).toBeUndefined();
    expect(dispatch.settings.sitemap_domain).toBe('dashingdiva.com');
    expect(dispatch.settings.sitemap_filter_keyword).toBe('collections');
    expect(dispatch.settings.sitemap_max_urls).toBe(250);
  });

  it('defaults sitemap filter settings when omitted', () => {
    const dispatch = buildDispatch(
      baseConfig({
        mode: 'sitemap',
        target_url: '',
        sitemap_domain: 'https://example.com',
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.settings.sitemap_filter_keyword).toBe('collections');
    expect(dispatch.settings.sitemap_max_urls).toBe(500);
  });

  it('throws when sitemap mode has no domain', () => {
    expect(() =>
      buildDispatch(
        baseConfig({
          mode: 'sitemap',
          target_url: '',
          sitemap_domain: ' ',
        }),
        [],
        { runProfile: baseProfile() },
      ),
    ).toThrow('Enter a site domain for sitemap discovery.');
  });

  it('infers category sitemap runs as batch', () => {
    expect(
      inferRunTypeHint(
        baseConfig({
          mode: 'sitemap',
          target_url: '',
          sitemap_domain: 'example.com',
        }),
      ),
    ).toBe('batch');
  });

  it('maps jobs pdp batch runs to job detail surface', () => {
    const dispatch = buildDispatch(
      baseConfig({
        module: 'pdp',
        domain: 'jobs',
        mode: 'batch',
        target_url: '',
        bulk_urls:
          'https://recruiting.ultipro.com/org/JobBoard/id/OpportunityDetail?opportunityId=1',
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.surface).toBe('job_detail');
  });

  it('throws when batch mode has no URLs', () => {
    expect(() =>
      buildDispatch(
        baseConfig({
          module: 'pdp',
          mode: 'batch',
          target_url: '',
          bulk_urls: '',
        }),
        [],
        { runProfile: baseProfile() },
      ),
    ).toThrow('Batch crawl needs at least one URL.');
  });

  it('includes CSS selectors in the extraction contract', () => {
    const fieldRows: FieldRow[] = [
      {
        id: 'field-1',
        fieldName: 'price',
        cssSelector: '.product-price',
        xpath: '',
        regex: '',
        cssState: 'valid',
        xpathState: 'idle',
        regexState: 'idle',
      },
    ];

    const dispatch = buildDispatch(baseConfig(), fieldRows, { runProfile: baseProfile() });

    expect(dispatch.settings.extraction_contract).toEqual([
      {
        field_name: 'price',
        css_selector: '.product-price',
        xpath: undefined,
        regex: undefined,
      },
    ]);
  });

  it('preserves raw additional field labels in dispatch settings', () => {
    const dispatch = buildDispatch(
      baseConfig({
        module: 'pdp',
        mode: 'batch',
        target_url: '',
        bulk_urls: 'https://example.com/p/1',
        additional_fields: ['Features & Benefits', 'Product Story'],
      }),
      [],
      { runProfile: baseProfile() },
    );

    expect(dispatch.additionalFields).toEqual(['Features & Benefits', 'Product Story']);
    expect(dispatch.settings.additional_fields).toEqual(['Features & Benefits', 'Product Story']);
  });
});
