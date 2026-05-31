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
// Domain boundaries: content is the generic catch-all; article is a specific editorial subtype.
// forum_thread means an individual discussion thread, while commerce/jobs/automobiles are verticals.
export type CrawlDomain =
  | 'auto'
  | 'content'
  | 'commerce'
  | 'jobs'
  | 'automobiles'
  | 'article'
  | 'forum_thread';
export type CrawlSurface =
  | 'auto'
  | 'content_detail'
  | 'content_listing'
  | 'ecommerce_listing'
  | 'ecommerce_detail'
  | 'job_listing'
  | 'job_detail'
  | 'automobile_listing'
  | 'automobile_detail'
  | 'article_listing'
  | 'article_detail'
  | 'forum_detail'
  | 'design_system';

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

export type UcpAuditOptions = {
  sample_size?: number;
  llm_enabled?: boolean;
  report_formats?: string[];
  jobsPollInterval?: number | false;
};

export type UcpAuditJobCreatePayload = {
  domain: string;
  options?: UcpAuditOptions;
};

export type UcpAuditJob = {
  id: number;
  user_id: number | null;
  domain: string;
  status: string;
  options: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type UcpAuditPageResult = {
  id: number;
  job_id: number;
  url: string;
  acquisition_mode: string;
  dimension_payloads: Record<string, unknown>;
  findings: Array<Record<string, unknown>>;
  created_at: string;
};

export type UcpAuditReport = {
  id: number;
  job_id: number;
  overall_score: number;
  dimension_scores: Array<{
    dimension_id: string;
    score: number;
    status: string;
    findings: Array<Record<string, unknown>>;
    weight: number;
  }>;
  findings: Array<Record<string, unknown>>;
  report_json: Record<string, unknown>;
  markdown_report: string;
  created_at: string;
  updated_at: string;
};

export type UcpAuditJobDetail = {
  job: UcpAuditJob;
  page_results: UcpAuditPageResult[];
  report: UcpAuditReport | null;
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
    prefer_curl_handoff: boolean;
    handoff_cookie_engine: 'auto' | 'patchright' | 'real_chrome';
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

export type MonitorPriority = 'on_demand' | 'priority' | 'background';
export type MonitorStatus = 'active' | 'paused' | 'archived' | 'triggered' | 'error';
export type MonitorEventType = 'field_changed' | 'record_new' | 'record_removed';
export type NotificationStatus = 'pending' | 'sent' | 'skipped';

export interface MonitorJob {
  id: number;
  name: string;
  urls: string[];
  domains: string[];
  surface: string;
  tracked_fields: string[];
  schedule_interval_hours: number;
  priority: MonitorPriority;
  retention_days: number;
  status: MonitorStatus;
  settings: Record<string, unknown>;
  target_rules?: AlertTargetRule[];
  condition?: string | null;
  webhook_url?: string | null;
  poll_interval_seconds?: number | null;
  last_known_values?: Record<string, unknown>;
  last_checked_at?: string | null;
  consecutive_failure_count?: number;
  last_error?: string | null;
  last_crawl_method?: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
  change_count?: number;
}

export interface MonitorEvent {
  id: number;
  monitor_id: number;
  run_id: number | null;
  source_url: string;
  event_type: MonitorEventType;
  field_name: string | null;
  old_value: unknown;
  new_value: unknown;
  detected_at: string;
  notified_at?: string | null;
  notification_status?: NotificationStatus;
  condition_met?: boolean;
}

export interface MonitorSnapshotRecord {
  id: number;
  snapshot_id: number;
  monitor_id: number;
  source_url: string;
  url_identity_key: string;
  field_values: Record<string, unknown>;
  created_at: string;
}

export interface MonitorSnapshot {
  id: number;
  monitor_id: number;
  run_id: number;
  snapshot_data?: Record<string, unknown>;
  record_count: number;
  change_count: number;
  created_at: string;
}

export interface MonitorCreatePayload {
  name: string;
  urls: string[];
  surface: string;
  tracked_fields: string[];
  schedule_interval_hours: number;
  priority: MonitorPriority;
  retention_days: number;
  requested_fields: string[];
  settings?: Record<string, unknown>;
}

export interface MonitorUpdatePayload {
  name?: string;
  tracked_fields?: string[];
  schedule_interval_hours?: number;
  priority?: MonitorPriority;
  retention_days?: number;
  status?: MonitorStatus;
  settings?: Record<string, unknown>;
  condition?: string | null;
  webhook_url?: string | null;
  poll_interval_seconds?: number | null;
}

export interface AlertCreatePayload {
  url: string;
  target_fields: string[];
  target_rules?: AlertTargetRule[];
  condition?: string | null;
  webhook_url?: string | null;
  poll_interval_seconds: number;
}

export interface AlertUpdatePayload {
  target_fields?: string[];
  target_rules?: AlertTargetRule[];
  condition?: string | null;
  webhook_url?: string | null;
  poll_interval_seconds?: number | null;
  status?: MonitorStatus;
}

export interface AlertTargetRule {
  path: string;
  label?: string | null;
  operator?: string;
  value?: unknown;
  variant_match?: Record<string, unknown> | null;
}

export interface AlertJob {
  id: number;
  url: string;
  domain: string;
  surface: string;
  target_fields: string[];
  target_rules?: AlertTargetRule[];
  condition?: string | null;
  webhook_url?: string | null;
  poll_interval_seconds: number;
  status: MonitorStatus;
  last_checked_at: string | null;
  last_known_values: Record<string, unknown>;
  last_error?: string | null;
  last_crawl_method?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertTestResponse {
  alert: AlertJob;
  run_id: number;
  current_snapshot: Record<string, unknown>;
  delta_count: number;
}

export interface AlertHistoryItem {
  id: number;
  alert_id: number;
  source_url: string;
  event_type: MonitorEventType;
  field_name: string | null;
  previous_value: unknown;
  current_value: unknown;
  detected_at: string;
  condition_met: boolean;
}

export interface WebhookDelivery {
  id: number;
  monitor_id: number;
  event_id: number | null;
  status: string;
  attempt: number;
  response_code?: number | null;
  error_message?: string | null;
  payload_preview: Record<string, unknown>;
  delivered_at?: string | null;
  created_at: string;
}

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

export interface InAppNotification {
  id: number;
  user_id: number | null;
  monitor_id: number;
  event_count: number;
  message: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
}

export type PlaygroundSessionResponse = {
  id: number;
  input_url: string;
  state: string;
  step_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

// --- Observability (Run Trace) ---
export type RunAuditFlag = {
  code: string;
  severity: string;
  symptom: string;
  invariant: string;
  owner: string;
  url?: string;
  evidence?: Record<string, unknown>;
};

export type RunAuditFlags = {
  schema_version: number;
  run_id: number;
  flag_count: number;
  severity_counts: Record<string, number>;
  flags: RunAuditFlag[];
  llm_diagnosis?: Record<string, unknown>;
};

export type RunTraceArtifact = {
  schema_version: number;
  tier: string;
  run_id: number;
  url: string;
  surface: string;
  requested_fields: string[];
  high_value_fields: string[];
  verdict: string;
  acquire_timeline: Array<{
    kind: string;
    sequence: number;
    duration_ms?: number;
    detail?: Record<string, unknown>;
  }>;
  extraction: {
    completed_tiers: string[];
    dom_skipped?: boolean;
    skip_decision?: Record<string, unknown>;
    field_provenance?: Array<{
      field: string;
      winning_source?: string;
      candidates?: Array<{
        source: string;
        won: boolean;
        value_preview?: string;
        reject_reason?: string;
      }>;
    }>;
  };
  host_outcome?: Record<string, unknown>;
  normalize_edits?: Array<{ field: string; reason: string }>;
};

export type RunObservability = {
  run_id: number;
  flags: RunAuditFlags | null;
  traces: RunTraceArtifact[];
  llm_diagnosis: Record<string, unknown> | null;
};
