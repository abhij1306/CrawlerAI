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

export type CrawlPhase = 'config' | 'running' | 'complete';

export type CrawlModule = 'category' | 'pdp';
export type CrawlDomain = 'commerce' | 'jobs';
export type CrawlSurface = 'ecommerce_listing' | 'ecommerce_detail' | 'job_listing' | 'job_detail';

export type CrawlMode = 'single' | 'sitemap' | 'bulk' | 'batch' | 'csv';
export type AdvancedCrawlMode = 'scroll' | 'load_more' | 'paginate' | 'view_all';

export type ResultSummaryQualityLevel = 'high' | 'medium' | 'low' | 'unknown';

export type ResultSummaryQuality = {
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

export type ResultSummary = {
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

export type ReviewSelection = {
  source_field: string;
  output_field: string;
  selected: boolean;
};

export type SelectorRuleInput = {
  id?: number | null;
  field_name: string;
  surface?: string | null;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status?: string | null;
  sample_value?: string | null;
  source?: string | null;
  is_active?: boolean;
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

export type ReviewPayload = {
  run: CrawlRun;
  normalized_fields: string[];
  discovered_fields: string[];
  canonical_fields: string[];
  domain_mapping: Record<string, string>;
  suggested_mapping: Record<string, string>;
  selector_memory: Array<Record<string, unknown>>;
  selector_suggestions: Record<string, Array<Record<string, unknown>>>;
  records: CrawlRecord[];
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

export type SelectorDomainSummary = {
  domain: string;
  surface: string;
  selector_count: number;
  updated_at: string | null;
};

export type ProductIntelligenceOptions = {
  max_source_products: number;
  max_candidates_per_product: number;
  search_provider: 'serpapi' | 'google_native';
  private_label_mode: 'include' | 'flag' | 'exclude';
  confidence_threshold: number;
  allowed_domains: string[];
  excluded_domains: string[];
  llm_enrichment_enabled: boolean;
};

export type ProductIntelligenceSourceRecordInput = {
  id?: number | null;
  run_id?: number | null;
  source_url?: string;
  data: Record<string, unknown>;
};

export type ProductIntelligenceJobCreatePayload = {
  source_run_id?: number | null;
  source_record_ids?: number[];
  source_records?: ProductIntelligenceSourceRecordInput[];
  options: ProductIntelligenceOptions;
};

export type ProductIntelligenceDiscoveryPayload = ProductIntelligenceJobCreatePayload;

export type ProductIntelligenceJob = {
  id: number;
  user_id: number;
  source_run_id: number | null;
  status: string;
  options: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ProductIntelligenceSourceProduct = {
  id: number;
  job_id: number;
  source_run_id: number | null;
  source_record_id: number | null;
  source_url: string;
  brand: string;
  normalized_brand: string;
  title: string;
  sku: string;
  mpn: string;
  gtin: string;
  price: number | null;
  currency: string;
  image_url: string;
  is_private_label: boolean;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ProductIntelligenceCandidate = {
  id: number;
  job_id: number;
  source_product_id: number;
  candidate_crawl_run_id: number | null;
  url: string;
  domain: string;
  source_type: string;
  query_used: string;
  search_rank: number;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProductIntelligenceMatch = {
  id: number;
  job_id: number;
  source_product_id: number;
  candidate_id: number;
  candidate_record_id: number | null;
  score: number;
  score_label: string;
  review_status: string;
  source_price: number | null;
  candidate_price: number | null;
  currency: string;
  availability: string;
  candidate_url: string;
  candidate_domain: string;
  score_reasons: Record<string, unknown>;
  llm_enrichment: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProductIntelligenceJobDetail = {
  job: ProductIntelligenceJob;
  source_products: ProductIntelligenceSourceProduct[];
  candidates: ProductIntelligenceCandidate[];
  matches: ProductIntelligenceMatch[];
};

export type ProductIntelligenceDiscoveryCandidate = {
  source_record_id: number | null;
  source_run_id: number | null;
  source_url: string;
  source_title: string;
  source_brand: string;
  source_price: number | null;
  source_currency: string;
  source_index: number;
  url: string;
  domain: string;
  source_type: string;
  query_used: string;
  search_rank: number;
  payload: Record<string, unknown>;
  intelligence?: Record<string, unknown>;
};

export type ProductIntelligenceDiscoveryResponse = {
  job_id: number;
  options: Record<string, unknown>;
  source_count: number;
  candidate_count: number;
  search_provider?: string;
  candidates: ProductIntelligenceDiscoveryCandidate[];
};

export type DataEnrichmentOptions = {
  max_source_records: number;
  llm_enabled: boolean;
};

export type DataEnrichmentSourceRecordInput = {
  id?: number | null;
  run_id?: number | null;
  source_url?: string;
  data: Record<string, unknown>;
};

export type DataEnrichmentJobCreatePayload = {
  source_run_id?: number | null;
  source_record_ids?: number[];
  source_records?: DataEnrichmentSourceRecordInput[];
  options: DataEnrichmentOptions;
};

export type DataEnrichmentJob = {
  id: number;
  user_id: number;
  source_run_id: number | null;
  status: string;
  options: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type EnrichedProduct = {
  id: number;
  job_id: number;
  source_run_id: number | null;
  source_record_id: number | null;
  source_url: string;
  status: string;
  price_normalized: Record<string, unknown> | null;
  color_family: string | null;
  size_normalized: string[] | null;
  size_system: string | null;
  gender_normalized: string | null;
  materials_normalized: string[] | null;
  availability_normalized: string | null;
  seo_keywords: string[] | null;
  category_path: string | null;
  taxonomy_version: string | null;
  intent_attributes: string[] | null;
  audience: string[] | null;
  style_tags: string[] | null;
  ai_discovery_tags: string[] | null;
  suggested_bundles: string[] | null;
  diagnostics: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DataEnrichmentJobDetail = {
  job: DataEnrichmentJob;
  enriched_products: EnrichedProduct[];
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

export type DomainRecipeSelectorCandidate = {
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
  field_learning: Array<{
    field_name: string;
    value: unknown;
    source_labels: string[];
    selector_kind: string | null;
    selector_value: string | null;
    source_record_ids: number[];
    feedback: {
      action: string;
      source_kind: string;
      source_value: string | null;
      source_run_id: number | null;
      created_at: string;
    } | null;
  }>;
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

export type SelectorCreatePayload = {
  domain: string;
  surface?: string | null;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status?: string | null;
  sample_value?: string | null;
  source?: string | null;
  source_run_id?: number | null;
  is_active?: boolean;
};

export type SelectorUpdatePayload = Partial<SelectorCreatePayload>;

export type SelectorTestResponse = {
  matched_value: string | null;
  count: number;
  selector_used?: string | null;
};

export type SelectorSuggestion = {
  field_name?: string | null;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  sample_value?: string | null;
  source?: string | null;
};

export type SelectorSuggestResponse = {
  surface: string;
  suggestions: Record<string, SelectorSuggestion[]>;
  preview_url?: string | null;
  iframe_promoted?: boolean;
};

export type KnowledgeSiteRecord = {
  id: string;
  domain: string;
  current_version: number;
  projection_status: string;
  last_projected_run_id?: number | null;
  last_projected_at?: string | null;
};

export type KnowledgeEntity = {
  id: string;
  entity_type: string;
  canonical_key: string;
  canonical_name: string;
  properties: Record<string, unknown>;
  status: string;
};

export type KnowledgeRelationship = {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  properties: Record<string, unknown>;
  confidence: number;
  status: string;
};

export type KnowledgeGraphResponse = {
  bounds: { depth: number; limit: number };
  nodes: KnowledgeEntity[];
  relationships: KnowledgeRelationship[];
};

// --- Diagnostics artifacts (diagnose.json / report.json) --------------------
// Mirrors backend `diagnose.v2` (app/observability/diagnose.py) and
// `run-report.v1` (app/observability/run_report.py). Bounded, self-contained
// root-cause artifacts surfaced read-only by the KG diagnostics drill-down.

export type DiagnoseEvidenceLocator = {
  kind: string;
  value: unknown;
  preview?: unknown;
};

export type DiagnoseFieldWinner = {
  collector_id?: string;
  locator?: DiagnoseEvidenceLocator;
  value?: unknown;
  rule_id?: string;
};

export type DiagnoseFieldRejected = {
  reason: string;
  collector_id?: string;
  locator?: DiagnoseEvidenceLocator;
  value_preview?: unknown;
  omitted?: number;
};

export type DiagnoseField = {
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

export type DiagnoseContractOutcome = {
  field: string;
  outcome: string;
  selected_source?: string | null;
  selection_origin?: string | null;
  applied: boolean;
  detail?: string | null;
};

export type DiagnoseEvidenceDispositionStatus =
  | 'accepted'
  | 'rejected_invalid'
  | 'rejected_lower_rank'
  | 'conflicted'
  | 'unowned'
  | 'outside_selected_target'
  | 'duplicate'
  | 'diagnostic_only'
  | string;

export type DiagnoseEvidenceDisposition = {
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

export type RunReportRootCause = {
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

export type KnowledgeContract = {
  id: string;
  template_id: string;
  surface: string;
  canonical_field: string;
  candidates: Array<Record<string, unknown>>;
  latest_values: Array<Record<string, unknown>>;
  success_count: number;
  rejection_count: number;
  resolver_rule: string;
  selected_source: string;
  selection_origin: string;
  selection_history: Array<Record<string, unknown>>;
  status: string;
};

export type KnowledgeSelectorContractPayload = {
  domain: string;
  url: string;
  surface: string;
  field_name: string;
  css_selector: string;
  sample_value?: string | null;
  source?: string | null;
};

export type KnowledgeContractSelectionPayload = {
  selected_source: string;
  expected_version?: number | null;
  template_id?: string;
  surface?: string;
  canonical_field?: string;
};

export type LlmConfigRecord = {
  id: number;
  provider: string;
  model: string;
  api_key_masked: string;
  api_key_set: boolean;
  task_type: string;
  per_domain_daily_budget_usd: string;
  global_session_budget_usd: string;
  is_active: boolean;
  created_at: string;
};

export type LlmConfigCreatePayload = {
  provider: string;
  model: string;
  task_type: string;
  api_key?: string | null;
  per_domain_daily_budget_usd?: string;
  global_session_budget_usd?: string;
  is_active?: boolean;
};

export type LlmConfigUpdatePayload = Partial<LlmConfigCreatePayload>;

export type LlmProviderCatalogItem = {
  provider: string;
  label: string;
  api_key_set: boolean;
  recommended_models: string[];
};

export type LlmConnectionTestResponse = {
  ok: boolean;
  message: string;
};

export type LlmCostLogRecord = {
  id: number;
  run_id: number | null;
  provider: string;
  model: string;
  task_type: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  domain: string;
  created_at: string;
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

export interface RunNowResponse {
  run_id: number;
  dispatched_at: string;
  url_count: number;
  run_ids?: number[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
