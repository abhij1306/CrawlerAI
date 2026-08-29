import { z } from 'zod';
import type { User, CrawlRun, CrawlRecord, DomainRunProfile } from './types';

export const userSchema: z.ZodSchema<User> = z.object({
  id: z.number(),
  email: z.string(),
  role: z.enum(['user', 'admin', 'harness']),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

const runStatusSchema = z.enum([
  'pending',
  'running',
  'paused',
  'completed',
  'killed',
  'failed',
  'proxy_exhausted',
]);

const resultSummarySchema = z
  .object({
    extraction_verdict: z.string().optional(),
    record_count: z.number().optional(),
    quality_summary: z.record(z.string(), z.unknown()).optional(),
    acquisition_summary: z.record(z.string(), z.unknown()).optional(),
    duration_ms: z.number().optional(),
    domain: z.string().optional(),
    error: z.string().optional(),
    current_stage: z.string().optional(),
    current_url: z.string().optional(),
    current_url_index: z.number().optional(),
    total_urls: z.number().optional(),
  })
  .passthrough();

export const crawlRunSchema: z.ZodSchema<CrawlRun> = z.object({
  id: z.number(),
  user_id: z.number(),
  run_type: z.string(),
  url: z.string(),
  status: runStatusSchema,
  surface: z.string(),
  settings: z.record(z.string(), z.unknown()),
  requested_fields: z.array(z.string()),
  result_summary: resultSummarySchema,
  // Output-required but tolerates absent input from older backends.
  run_health: z.record(z.string(), z.unknown()).default({}),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable().default(null),
});

export const crawlRecordSchema: z.ZodSchema<CrawlRecord> = z.object({
  id: z.number(),
  run_id: z.number(),
  source_url: z.string(),
  data: z.record(z.string(), z.unknown()),
  raw_data: z.record(z.string(), z.unknown()),
  discovered_data: z.record(z.string(), z.unknown()),
  source_trace: z.record(z.string(), z.unknown()),
  review_bucket: z
    .array(
      z.object({
        key: z.string(),
        value: z.unknown(),
        source: z.string(),
        evidence_id: z.string().optional(),
        reason: z.string().nullable().optional(),
      }),
    )
    .optional(),
  provenance_available: z.boolean().optional(),
  raw_html_path: z.string().nullable().default(null),
  enrichment_status: z.string().optional(),
  enriched_at: z.string().nullable().optional(),
  created_at: z.string(),
});

export const domainRunProfileSchema: z.ZodSchema<DomainRunProfile> = z.object({
  version: z.number().default(1),
  fetch_profile: z
    .object({
      fetch_mode: z.enum(['auto', 'http_only', 'browser_only', 'http_then_browser']),
      extraction_source: z.enum([
        'raw_html',
        'rendered_dom',
        'rendered_dom_visual',
        'network_payload_first',
      ]),
      js_mode: z.enum(['auto', 'enabled', 'disabled']),
      include_iframes: z.boolean(),
      traversal_mode: z.enum(['scroll', 'load_more', 'paginate', 'view_all']).nullable(),
      request_delay_ms: z.number(),
      host_memory_ttl_seconds: z.number().nullable().optional(),
      max_pages: z.number().optional(),
      max_scrolls: z.number().optional(),
    })
    .default({
      fetch_mode: 'auto',
      extraction_source: 'raw_html',
      js_mode: 'auto',
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 100,
    }),
  locality_profile: z
    .object({
      geo_country: z.string(),
      language_hint: z.string().nullable(),
      currency_hint: z.string().nullable(),
    })
    .default({ geo_country: 'auto', language_hint: null, currency_hint: null }),
  diagnostics_profile: z
    .object({
      capture_html: z.boolean(),
      capture_screenshot: z.boolean(),
      capture_network: z.enum(['off', 'matched_only', 'all_small_json']),
      capture_response_headers: z.boolean(),
      capture_browser_diagnostics: z.boolean(),
    })
    .default({
      capture_html: true,
      capture_screenshot: false,
      capture_network: 'off',
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    }),
  acquisition_contract: z
    .object({
      preferred_browser_engine: z.enum(['auto', 'patchright', 'real_chrome']),
      prefer_browser: z.boolean(),
      handoff_eligible: z.boolean(),
      handoff_cookie_engine: z.enum(['auto', 'patchright', 'real_chrome']),
      required_rendering: z.boolean(),
      required_traversal: z.boolean(),
      required_network_payloads: z.boolean(),
      last_quality_success: z
        .object({
          method: z.string().nullable(),
          browser_engine: z.enum(['auto', 'patchright', 'real_chrome']).nullable(),
          record_count: z.number(),
          field_coverage: z.record(z.string(), z.unknown()),
          source_run_id: z.number().nullable(),
          timestamp: z.string().nullable(),
        })
        .nullable(),
      stale_after_failures: z.object({
        failure_count: z.number(),
        stale: z.boolean(),
      }),
    })
    .default({
      preferred_browser_engine: 'auto',
      prefer_browser: false,
      handoff_eligible: false,
      handoff_cookie_engine: 'auto',
      required_rendering: false,
      required_traversal: false,
      required_network_payloads: false,
      last_quality_success: null,
      stale_after_failures: { failure_count: 0, stale: false },
    }),
  source_run_id: z.number().nullable().optional(),
  saved_at: z.string().nullable().optional(),
});

export function strictValidate<T>(schema: z.ZodSchema<T>, data: unknown, context: string): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new Error(`API validation failure in ${context}: ${result.error.message}`);
  }
  return result.data;
}
