export type User = {
  id: number;
  email: string;
  role: 'user' | 'admin' | 'harness';
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type RunStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'killed'
  | 'failed'
  | 'proxy_exhausted';

type CrawlModule = 'category' | 'pdp';
export type CrawlDomain = 'commerce' | 'jobs';
export type CrawlSurface = 'ecommerce_listing' | 'ecommerce_detail' | 'job_listing' | 'job_detail';

type CrawlMode = 'single' | 'sitemap' | 'bulk' | 'batch' | 'csv';
export type AdvancedCrawlMode = 'scroll' | 'load_more' | 'paginate' | 'view_all';

export type ResultSummaryQualityLevel = 'high' | 'medium' | 'low' | 'unknown';

type ResultSummaryQuality = {
  level?: ResultSummaryQualityLevel;
  score?: number;
  scored_urls?: number;
  level_counts?: Partial<Record<ResultSummaryQualityLevel, number>>;
  listing_incomplete_urls?: number;
  variant_incomplete_urls?: number;
  requested_fields_total?: number;
  requested_fields_found_best?: number;
  [key: string]: unknown;
};

type ResultSummary = {
  extraction_verdict?: string;
  record_count?: number;
  quality_summary?: ResultSummaryQuality;
  acquisition_summary?: Record<string, unknown>;
  duration_ms?: number;
  domain?: string;
  error?: string;
  current_stage?: string;
  current_url?: string;
  current_url_index?: number;
  total_urls?: number;
  [key: string]: unknown;
};

export type CrawlRun = {
  id: number;
  user_id: number;
  run_type: string;
  url: string;
  status: RunStatus;
  surface: string;
  settings: Record<string, unknown>;
  requested_fields: string[];
  result_summary: ResultSummary;
  run_health: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ActiveJob = {
  run_id: number;
  status: RunStatus;
  progress: number;
  started_at: string;
  url: string;
  type: string;
  user_id?: number;
  elapsed_seconds?: number;
  records_collected?: number;
  max_records?: number;
};

export type CrawlRecord = {
  id: number;
  run_id: number;
  source_url: string;
  data: Record<string, unknown>;
  raw_data: Record<string, unknown>;
  discovered_data: Record<string, unknown>;
  source_trace: Record<string, unknown>;
  review_bucket?: Array<{
    key: string;
    value: unknown;
    source: string;
    evidence_id?: string;
    reason?: string | null;
  }>;
  provenance_available?: boolean;
  raw_html_path: string | null;
  enrichment_status?: string;
  enriched_at?: string | null;
  created_at: string;
};

export type CrawlRecordProvenance = {
  id: number;
  run_id: number;
  source_url: string;
  raw_data: Record<string, unknown>;
  discovered_data: Record<string, unknown>;
  source_trace: Record<string, unknown>;
  manifest_trace: Record<string, unknown>;
  raw_html_path: string | null;
  created_at: string;
};

export type CrawlLog = {
  id: number;
  level: string;
  message: string;
  created_at: string;
};

export type Paginated<T> = {
  items: T[];
  meta: { page: number; limit: number; total: number };
};

export type Dashboard = {
  total_runs: number;
  active_runs: number;
  total_records: number;
  recent_runs: CrawlRun[];
  top_domains: { domain: string; count: number }[];
};

export type SelectorRecord = {
  id: number;
  domain: string;
  surface: string;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status: string;
  sample_value?: string | null;
  source: string;
  source_run_id?: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type DomainRunProfile = {
  version: number;
  fetch_profile: {
    fetch_mode: 'auto' | 'http_only' | 'browser_only' | 'http_then_browser';
    extraction_source:
      | 'raw_html'
      | 'rendered_dom'
      | 'rendered_dom_visual'
      | 'network_payload_first';
    js_mode: 'auto' | 'enabled' | 'disabled';
    include_iframes: boolean;
    traversal_mode: AdvancedCrawlMode | null;
    request_delay_ms: number;
    host_memory_ttl_seconds?: number | null;
    max_pages?: number;
    max_scrolls?: number;
  };
  locality_profile: {
    geo_country: string;
    language_hint: string | null;
    currency_hint: string | null;
  };
  diagnostics_profile: {
    capture_html: boolean;
    capture_screenshot: boolean;
    capture_network: 'off' | 'matched_only' | 'all_small_json';
    capture_response_headers: boolean;
    capture_browser_diagnostics: boolean;
  };
  acquisition_contract: {
    preferred_browser_engine: 'auto' | 'patchright' | 'real_chrome';
    prefer_browser: boolean;
    handoff_eligible: boolean;
    handoff_cookie_engine: 'auto' | 'patchright' | 'real_chrome';
    required_rendering: boolean;
    required_traversal: boolean;
    required_network_payloads: boolean;
    last_quality_success: {
      method: string | null;
      browser_engine: 'auto' | 'patchright' | 'real_chrome' | null;
      record_count: number;
      field_coverage: Record<string, unknown>;
      source_run_id: number | null;
      timestamp: string | null;
    } | null;
    stale_after_failures: {
      failure_count: number;
      stale: boolean;
    };
  };
  source_run_id?: number | null;
  saved_at?: string | null;
};

type DomainRecipeSelectorCandidate = {
  candidate_key: string;
  field_name: string;
  selector_kind: string;
  selector_value: string;
  selector_source: string;
  sample_value?: string | null;
  source_record_ids: number[];
  source_run_id?: number | null;
  saved_selector_id?: number | null;
  already_saved: boolean;
  final_field_source?: string | null;
};

export type DomainRecipeFieldLearningItem = {
  field_name: string;
  value: unknown;
  source_labels: string[];
  selector_kind: string | null;
  selector_value: string | null;
  source_record_ids: number[];
  representative_url_result_ids: number[];
  feedback: {
    action: string;
    source_kind: string;
    source_value: string | null;
    source_run_id: number | null;
    created_at: string;
  } | null;
};

export type DomainRecipe = {
  run_id: number;
  domain: string;
  surface: string;
  requested_field_coverage: {
    requested: string[];
    found: string[];
    missing: string[];
  };
  acquisition_evidence: {
    actual_fetch_method: string | null;
    browser_used: boolean;
    browser_reason: string | null;
    acquisition_summary: Record<string, unknown>;
    cookie_memory_available: boolean;
  };
  field_learning: DomainRecipeFieldLearningItem[];
  selector_candidates: DomainRecipeSelectorCandidate[];
  affordance_candidates: {
    accordions: string[];
    tabs: string[];
    carousels: string[];
    shadow_hosts: string[];
    iframe_promotion: string | null;
    browser_required: boolean;
  };
  saved_selectors: SelectorRecord[];
  saved_run_profile: DomainRunProfile | null;
};

export type DomainRunProfileLookup = {
  domain: string;
  surface: string;
  saved_run_profile: DomainRunProfile | null;
};

export type DomainRunProfileRecord = {
  id: number;
  domain: string;
  surface: string;
  profile: DomainRunProfile;
  created_at: string;
  updated_at: string;
};

export type DomainCookieMemoryRecord = {
  id: number;
  domain: string;
  browser_engine?: string | null;
  cookie_count: number;
  origin_count: number;
  updated_at: string;
};

export type DomainFieldFeedbackRecord = {
  id: number;
  domain: string;
  surface: string;
  field_name: string;
  action: string;
  source_kind: string;
  source_value: string | null;
  source_run_id: number | null;
  selector_kind: string | null;
  selector_value: string | null;
  source_record_ids: number[];
  created_at: string;
};

export type FieldCommitPayload = {
  record_id: number;
  field_name: string;
  value: unknown;
};

export type FieldCommitResponse = {
  run_id: number;
  updated_records: number;
  updated_fields: number;
};

export type GroundedCorrectionPayload = {
  labels: Array<{
    target_kind:
      | 'page_region'
      | 'record_boundary'
      | 'field'
      | 'entity_relationship'
      | 'explicit_absence';
    subject_id?: string | null;
    record_id?: string | null;
    field_name?: string | null;
    canonical_value?: unknown;
    semantic_role?: string | null;
    locale_interpretation?: string | null;
    region_role?: 'primary' | 'recommendation' | 'boilerplate' | 'unrelated' | null;
    relationship?: Record<string, string> | null;
    grounding: Array<{
      kind: 'node' | 'path' | 'region' | 'absence_assertion';
      artifact_id: string;
      locator: string;
      bounding_box?: Record<string, number> | null;
    }>;
  }>;
  activate: boolean;
  representative_url_result_ids: number[];
};

export type GroundedCorrectionResponse = {
  correction_id: number;
  domain: string;
  surface: string;
  label_count: number;
  activation_status: string;
  replay: Record<string, unknown>;
};

// --- Diagnostics artifacts (diagnose.json / report.json) --------------------
// Mirrors backend `diagnose.v2` (app/observability/diagnose.py) and
// `run-report.v1` (app/observability/run_report.py). Bounded, self-contained
// root-cause artifacts surfaced read-only by the KG diagnostics drill-down.

type DiagnoseEvidenceLocator = {
  kind: string;
  value: unknown;
  preview?: unknown;
};

type DiagnoseFieldWinner = {
  collector_id?: string;
  locator?: DiagnoseEvidenceLocator;
  value?: unknown;
  rule_id?: string;
};

type DiagnoseFieldRejected = {
  reason: string;
  collector_id?: string;
  locator?: DiagnoseEvidenceLocator;
  value_preview?: unknown;
  omitted?: number;
};

type DiagnoseField = {
  field: string;
  status:
    | 'captured_and_resolved'
    | 'captured_published'
    | 'captured_suppressed'
    | 'captured_conflicting'
    | 'captured_unowned'
    | 'captured_but_rejected'
    | 'not_captured'
    | 'not_present_in_captured_sources'
    | 'not_present_in_source'
    | 'source_unavailable'
    | string;
  reason_codes?: string[];
  winner?: DiagnoseFieldWinner;
  rejected?: DiagnoseFieldRejected[];
  publication_policy?: unknown;
};

type DiagnoseContractOutcome = {
  field: string;
  outcome: string;
  selected_source?: string | null;
  selection_origin?: string | null;
  applied: boolean;
  detail?: string | null;
};

type DiagnoseEvidenceDispositionStatus =
  | 'accepted'
  | 'rejected_invalid'
  | 'rejected_lower_rank'
  | 'conflicted'
  | 'unowned'
  | 'outside_selected_target'
  | 'duplicate'
  | 'diagnostic_only'
  | string;

type DiagnoseEvidenceDisposition = {
  evidence_id: string;
  entity_id?: string | null;
  status: DiagnoseEvidenceDispositionStatus;
  reason_code: string;
  decision_id?: string | null;
  selected_fact_id?: string | null;
  derived_fact_id?: string | null;
};

export type ResultDiagnosis = {
  schema_version: string;
  verdict?: string;
  data_integrity?: 'clean' | 'partial' | 'defect' | 'blocked' | 'unknown' | 'divergent' | string;
  acquisition?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  fields: DiagnoseField[];
  variants?: { dropped: Array<Record<string, unknown>> };
  collectors?: Array<Record<string, unknown>>;
  stages?: Array<Record<string, unknown>>;
  findings?: Array<Record<string, unknown>>;
  evidence_dispositions?: {
    total: number;
    by_status: Partial<Record<DiagnoseEvidenceDispositionStatus, number>>;
    examples: DiagnoseEvidenceDisposition[];
  };
  contract_outcomes?: DiagnoseContractOutcome[] | null;
  truncated?: Record<
    string,
    { included: number; total: number } | { original_bytes: number; limit_bytes: number }
  >;
};

type RunReportRootCause = {
  root_cause: string;
  count: number;
  diagnose_links: string[];
};

export type RunReport = {
  schema_version: string;
  run_id: number;
  root_cause_count: number;
  root_causes: RunReportRootCause[];
};

export type CrawlCreatePayload = {
  run_type: 'crawl' | 'batch' | 'csv';
  url?: string;
  urls?: string[];
  surface: CrawlSurface;
  settings?: Record<string, unknown>;
  additional_fields?: string[];
};

export type LoginResponse = {
  user: User;
};

export type CrawlConfig = {
  module: CrawlModule;
  domain: CrawlDomain;
  mode: CrawlMode;
  target_url: string;
  bulk_urls: string;
  sitemap_domain?: string;
  sitemap_filter_keyword?: string;
  sitemap_max_urls?: number;
  csv_file: File | null;
  smart_extraction: boolean;
  max_records: number;
  respect_robots_txt: boolean;
  proxy_enabled: boolean;
  proxy_lines: string[];
  additional_fields: string[];
};
