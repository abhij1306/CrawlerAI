# Plan: Site SEO/AEO Audit Crawler

**Created:** 2026-07-08  
**Agent:** GPT-5.5 Thinking  
**Status:** BLOCKED — audit complete; queued behind the active Extraction V3 plan and awaiting implementation approval  
**Touches buckets:** new `backend/app/site_audit/*` bounded context, audit models and Alembic migrations, `backend/app/api/site_audits.py`, crawl-run dispatch integration, audit exports, new `frontend/app/site-audit/*`, `frontend/components/site-audit/*`, `frontend/lib/api/site-audits.ts`, focused backend/frontend/E2E tests, and architecture documentation.

---

## Goal

Add a production-grade site-audit mode to CrawlerAI that starts from a domain, discovers all in-scope crawlable URLs through sitemaps and internal links, captures a stable technical/content snapshot for every page, evaluates versioned SEO and AEO rules, aggregates findings by severity and priority, and exposes a Screaming Frog-inspired investigation workspace.

Done means an operator can:

1. Enter a domain and configure crawl scope and limits.
2. Watch discovery and analysis progress while the URL total grows dynamically.
3. Inspect a server-paginated URL inventory.
4. Filter by technical, content, structured-data, SEO, AEO, and security facets.
5. Select an issue and see affected URLs, evidence, and remediation.
6. Select a URL and inspect metadata, headers, inlinks, outlinks, structured data, findings, and rendered/source evidence.
7. Export pages, links, findings, and aggregate reports.
8. Re-run the same audit later and compare meaningful changes.

The implementation must reuse CrawlerAI's proven acquisition, robots, URL-safety, run-state, logging, websocket, pause/kill, and export infrastructure without coupling the new audit domain to the product-extraction engine.

---

## Audit Scope and Evidence

The repository audit covered the existing crawl runtime, URL discovery, robots enforcement, acquisition contracts, run/result persistence, APIs, exports, frontend crawl workspace, tests, and the attached Screaming Frog UI reference.

### Current architecture assessment

| Area | Existing capability | Audit finding |
|---|---|---|
| Run lifecycle | Pending/running/paused/terminal states, queue metadata, heartbeats, leases, kill/pause checkpoints | Reusable |
| Batch execution | Sequential/parallel per-URL processing, timeout handling, progress summaries, per-URL DB ownership | Reusable with a new frontier-aware orchestrator |
| URL sources | Explicit URL, CSV, category sitemap resolver, rendered category-link discovery | Not a generic full-domain crawler |
| Robots | Cached `robots.txt` fetch and allow/disallow outcomes | Reusable |
| URL safety | Public-target validation and same-origin checks | Reusable and must remain mandatory |
| Acquisition | Final URL, HTML, status, content type, headers, browser diagnostics, network data, artifacts | Strong reusable foundation |
| Persistence | `CrawlRun`, extraction-oriented `CrawlUrlResult`, records, logs | Missing audit page, link-edge, finding, and rule-version entities |
| Analysis | Product/listing extraction, JSON-LD collection | No generic SEO/AEO analyzer or issue registry |
| APIs | Run creation/status, records, logs/websocket, actions, exports | Reusable patterns; audit-specific query APIs are required |
| Frontend | Crawl configuration, live logs, records/JSON output, history and exports | Extraction-centric; requires a dedicated audit workspace |
| Tests | Strong batch runtime, API, log-stream, polling, and crawl UI coverage | Good base; no audit rule/frontier/scale corpus |

### Main architectural gaps

1. **The existing batch runtime assumes a known URL list.** A site crawl has a dynamically expanding frontier, so progress cannot be modeled only as `processed / initial_total`.
2. **Current link discovery is category-specific.** It performs a bounded BFS, but scores only category/listing-like URLs and rejects ordinary content pages.
3. **Existing persistence is extraction-oriented.** Overloading `CrawlUrlResult.data` with dozens of audit columns would make filtering, aggregation, indexing, and historical comparison fragile.
4. **There is no rule registry.** SEO/AEO checks need stable IDs, versions, categories, severity, priority, evidence schemas, and remediation text.
5. **There is no link graph.** Inlinks, outlinks, orphan candidates, crawl depth, broken-link impact, and internal redirect findings require persisted edges.
6. **There is no generic page snapshot.** The analyzer needs one normalized representation independent of acquisition lane or HTML parsing implementation.
7. **The current frontend is record-centric.** A site auditor needs a synchronized URL grid, issue summary, and contextual details workspace with server-side filtering.

---

## Product Decisions to Lock Before Slice 0

The following defaults are proposed so implementation does not hide product choices inside code:

| Decision | Proposed default |
|---|---|
| Crawl scope | Exact host, with explicit toggles for `www` equivalence and subdomains |
| Scheme | Follow HTTP→HTTPS redirects; treat final origin as authoritative only after explicit scope validation |
| Discovery sources | `robots.txt` sitemap directives, conventional sitemap candidates, nested sitemap indexes, HTML links, canonical/hreflang references as observations rather than automatic frontier additions |
| Fetch strategy | HTTP-first; browser fallback only when configured signals show that rendered DOM is needed |
| URL normalization | Remove fragments, normalize host/scheme/default ports, preserve path case, normalize percent encoding, and apply an explicit query-parameter policy |
| Query policy | Keep unknown parameters initially; drop configured tracking parameters; expose include/exclude rules |
| Crawl traps | Per-pattern limits, duplicate-content limits, depth limit, page limit, per-host rate limits, calendar/faceted-navigation detection |
| Robots behavior | Respect by default; record disallowed URLs without fetching their page body |
| Raw HTML retention | Off by default for completed audits, or short TTL; retain normalized snapshots and evidence |
| Default limits | Product-configured rather than hard-coded; UI must display the effective page/depth/time/concurrency budget |
| AEO scoring | Category-level evidence and rubric; no single opaque “truth” score |
| Experimental checks | Clearly labeled, confidence-bearing, and excluded from deterministic readiness totals by default |

These values should be represented in an immutable audit-run settings snapshot.

---

## Target Architecture

### Bounded context

Create `backend/app/site_audit/` as a separate domain package. It may consume stable acquisition and run-control contracts, but it must not import product-extraction collectors, resolution logic, or persistence internals.

Proposed ownership:

```text
backend/app/site_audit/
├── contracts.py             # PageSnapshot, LinkObservation, Finding, RuleResult
├── settings.py              # Validated audit-run configuration
├── normalization.py         # URL identity and query policy
├── scope.py                 # Origin/subdomain/include/exclude decisions
├── frontier.py              # Persistent deduplicated crawl frontier
├── discovery.py             # Sitemaps + link observations
├── snapshot.py              # Acquisition result -> normalized page snapshot
├── html_analyzer.py         # Titles, headings, canonicals, robots, links, images, text
├── structured_data.py       # Generic JSON-LD/microdata summaries and validation inputs
├── rules/
│   ├── registry.py          # IDs, versions, metadata, execution contract
│   ├── crawlability.py
│   ├── metadata.py
│   ├── content.py
│   ├── links.py
│   ├── images.py
│   ├── canonicals.py
│   ├── structured_data.py
│   ├── security.py
│   └── aeo.py
├── aggregation.py           # Counts, percentages, category summaries
├── scoring.py               # Transparent category-level rubric
├── service.py               # Audit orchestration
├── crud.py                  # Audit persistence queries
├── exports.py
└── metrics.py
```

### Runtime flow

```text
Create Audit Run
      |
      v
Seed Resolver ---- robots/sitemaps/homepage
      |
      v
Persistent Frontier <------------------------+
      |                                      |
      v                                      |
Scope + Robots + Trap Policy                 |
      |                                      |
      v                                      |
Acquire Page (HTTP-first/browser fallback)   |
      |                                      |
      v                                      |
Page Snapshot + Link Observations -----------+
      |
      v
Versioned Rule Engine
      |
      +--> Page Findings
      +--> Link Findings
      +--> Run Findings
      |
      v
Incremental Aggregates + Live Progress
```

The frontier must persist enough state to resume safely after worker failure:

- normalized URL key
- requested URL and discovery source
- source page
- depth
- state: queued, fetching, analyzed, skipped, failed
- scope/robots decision
- attempt count and last error
- priority and next-attempt time
- created/updated timestamps

### Persistence model

Prefer dedicated tables rather than putting all fields in `CrawlRecord.data`.

#### `site_audit_runs`

Either a one-to-one extension of `CrawlRun` or an audit-specific run table linked to it.

Core fields:

- `crawl_run_id`
- analyzer/rule-set version
- immutable settings snapshot
- seed/final origin
- discovery counters
- terminal aggregate summary
- comparison baseline run ID, nullable

#### `site_audit_frontier`

- run ID
- normalized URL key
- requested URL
- source page ID, nullable
- discovery source
- depth
- state
- scope decision
- robots decision
- priority
- attempt count/error
- unique `(run_id, normalized_url_key)`

#### `site_audit_pages`

- run ID and frontier item
- requested, normalized, and final URL
- redirect chain summary
- status code/status group
- content type
- response headers subset
- response time and transferred/decoded size
- fetch lane and rendered flag
- robots/indexability directives
- canonical and hreflang summaries
- title/meta description and measured lengths
- H1/H2 counts and normalized values
- language
- word count and visible-text hash
- exact/near-duplicate group IDs
- structured-data type/error summary
- image/resource counts and issue counters
- analyzer version
- created/updated timestamps

Large variable evidence should live in bounded JSONB columns or external artifacts, not in frequently scanned columns.

#### `site_audit_links`

- run ID
- source page ID
- raw href
- resolved target URL and normalized key
- target page ID, nullable
- internal/external/resource classification
- anchor text
- `rel`, target, hreflang
- follow/nofollow/sponsored/ugc flags
- discovered in source/rendered DOM
- first-seen location and count

Use deduplication that preserves aggregate occurrence count while avoiding one row for every repeated footer link instance unless occurrence-level evidence is requested.

#### `site_audit_findings`

- run ID
- page ID, link ID, or run scope
- stable `rule_id`
- `rule_version`
- category
- issue type: issue, warning, opportunity
- priority: high, medium, low
- evidence JSON
- remediation key/text
- fingerprint for deduplication
- status/suppression metadata for future workflows

#### Aggregate strategy

Start with indexed SQL aggregation plus a compact run summary cache. Add materialized aggregate tables only after measured query plans show a need.

---

## Rule Engine Contract

Every rule must be deterministic by default and return a typed result:

```text
RuleDefinition
- id
- version
- title
- category
- default_issue_type
- default_priority
- scope: page | link | run
- required_snapshot_fields
- evaluate(context) -> zero or more FindingDraft
```

Requirements:

- Stable IDs survive UI wording changes.
- Rule versions change when evaluation semantics change.
- Evidence is machine-readable and bounded.
- Remediation is separate from evidence.
- A rule can return “not applicable” or “insufficient evidence.”
- Experimental/heuristic rules are tagged and excluded from deterministic rollups unless enabled.
- Findings are idempotent for the same analyzer/rule version.
- Aggregate percentages define their denominator explicitly.

---

## Initial SEO Rule Catalogue

### Crawlability and indexability

- robots disallowed
- robots fetch failure
- meta robots and `X-Robots-Tag` noindex/nofollow
- non-success status codes
- redirect chains, loops, and redirecting internal links
- soft-404 candidate with evidence threshold
- canonical missing, multiple, malformed, cross-origin, redirecting, non-indexable, or conflicting
- sitemap URL not internally linked
- crawled indexable URL absent from discovered sitemaps
- pagination/faceted URL pattern warnings
- conflicting indexability signals

### Titles and metadata

- title missing, empty, duplicated, unusually short/long
- meta description missing, empty, duplicated, unusually short/long
- viewport missing
- charset declaration problems
- Open Graph/Twitter metadata completeness as opportunities
- duplicate title/description clusters

Character thresholds must be configurable. Pixel-width checks should be named as estimates unless the implementation actually measures with a defined font/rendering model.

### Headings and content

- H1 missing or multiple
- duplicate H1 clusters
- heading-order anomalies
- low visible-text content
- exact duplicate content
- near-duplicate candidates with similarity evidence
- language declaration missing or inconsistent
- page has no meaningful main-content region
- stale/update metadata opportunities where applicable

Near-duplicate detection should be staged: normalized hash first, then a bounded similarity technique after scale validation.

### Internal links and site structure

- broken internal links
- internal links to redirects
- pages without internal inlinks, with sitemap-only discovery distinguished
- links with empty/non-descriptive anchor text
- excessive crawl depth
- isolated internal components
- nofollowed internal links
- target URL variants that collapse to the same normalized URL
- external-link errors only when explicitly enabled to avoid uncontrolled scope/cost

### Images and resources

- broken image resource
- missing/empty alt text
- oversized image by transferred/decoded bytes
- missing width/height opportunity
- mixed-content resource
- lazy-loaded image not represented in source/rendered evidence
- duplicate image observations aggregated by URL

### Structured data

- malformed JSON-LD
- recognized type with missing required/important properties according to the configured validator version
- duplicate or contradictory primary entities
- page/canonical/entity URL conflicts
- breadcrumb continuity problems
- FAQ/HowTo visible-content mismatch where those types are present
- organization/site identity inconsistency across pages

The snapshot should preserve the raw structured-data block as an artifact or bounded evidence reference rather than flattening every property into page columns.

### Security and headers

- HTTP page or downgrade redirect
- mixed active content
- missing configured security headers
- unsafe cross-origin `target="_blank"` link without appropriate `rel`
- overly permissive or conflicting indexing/security headers
- certificate/TLS checks only if the acquisition layer exposes reliable evidence

---

## Initial AEO Readiness Model

AEO must be an explainable evidence rubric, not a black-box score.

### Deterministic dimensions

1. **Entity clarity**
   - consistent organization/site/page entities
   - stable canonical/entity identifiers
   - authorship and publisher information where applicable
   - `sameAs` and identity references when present

2. **Answer structure**
   - descriptive heading hierarchy
   - question-and-answer sections
   - concise answer blocks near relevant headings
   - lists, tables, steps, and definitions represented semantically

3. **Structured data**
   - valid page-type markup
   - breadcrumbs
   - article/product/organization/FAQ/HowTo properties when applicable
   - visible content consistent with structured content

4. **Trust and provenance**
   - author/publisher/date metadata
   - source/citation links where claims require them
   - contact/about/editorial-policy discoverability as configurable opportunities
   - content update signals

5. **Accessibility to crawlers**
   - indexability
   - stable URLs/canonicals
   - readable server/rendered content
   - configurable user-agent access observations

6. **Content coverage**
   - topic and intent headings
   - explicit definitions, comparisons, procedures, and FAQs where relevant
   - internal links to supporting entities/pages

### Optional heuristic dimensions

- answer directness
- question coverage
- entity salience and consistency
- citation quality
- claim/source proximity
- content freshness relevance

Heuristic checks must:

- emit evidence excerpts/paths
- include confidence
- be labeled experimental
- have a model/prompt/rubric version
- never overwrite deterministic findings
- remain disabled by default until an evaluation corpus exists

An `llms.txt` observation may be surfaced as informational metadata, but it must not be treated as a universal requirement unless the product explicitly adopts that policy.

---

## UI Direction

Use the attached Screaming Frog screenshot as an interaction reference, not a visual or branding clone.

### Audit workspace layout

#### Top control bar

- seed domain
- scope summary
- start/pause/resume/stop
- crawl and analysis progress
- discovered/queued/fetched/analyzed/skipped/failed counts
- current URLs per second
- active concurrency and elapsed time
- export and saved-view actions

#### Facet tabs

- Overview
- Internal
- External
- Response Codes
- URL
- Page Titles
- Meta Descriptions
- H1
- H2
- Content
- Images
- Canonicals
- Directives
- Structured Data
- AEO
- Security
- Response Times

Tabs are saved server query presets, not separate copies of all page data.

#### Main three-pane workspace

1. **URL grid**
   - virtualized rows
   - server-side pagination/filter/sort
   - configurable columns
   - row selection and bulk export
   - live incremental updates without resetting sort/filter state

2. **Issue summary**
   - rule title
   - issue type
   - priority
   - affected URL count
   - percentage with explicit denominator
   - category and deterministic/experimental badge
   - selecting an issue filters the URL grid

3. **Context details**
   - URL details
   - findings/evidence/remediation
   - inlinks
   - outlinks
   - response headers and redirects
   - rendered/source summary
   - structured data
   - crawl/discovery history

A selected URL and selected issue must synchronize across panes. Deep-linkable query parameters should preserve run, facet, issue, filters, sort, and page.

### Frontend ownership

```text
frontend/app/site-audit/page-view.tsx
frontend/components/site-audit/
├── site-audit-config-screen.tsx
├── site-audit-run-screen.tsx
├── audit-control-bar.tsx
├── audit-facet-tabs.tsx
├── audit-url-grid.tsx
├── audit-issue-summary.tsx
├── audit-details-panel.tsx
├── audit-url-details.tsx
├── audit-links-panel.tsx
├── audit-findings-panel.tsx
├── audit-structured-data-panel.tsx
├── use-site-audit-run.ts
├── use-audit-pages.ts
├── use-audit-findings.ts
└── audit-query-state.ts
frontend/lib/api/site-audits.ts
```

Reuse existing UI primitives, query client, status patterns, history drawer, websocket fallback patterns, export handling, and route conventions. Do not reuse extraction-specific records/learning components.

---

## Acceptance Criteria

- [ ] A user can start an audit from a valid public domain with a persisted immutable scope/settings snapshot.
- [ ] Discovery combines configured sitemap and same-scope HTML-link sources and continues until the frontier is empty or a configured budget is reached.
- [ ] URL normalization, scope decisions, robots decisions, and trap-limit decisions are deterministic, persisted, and testable.
- [ ] Worker interruption can resume without duplicating analyzed pages or losing queued frontier items.
- [ ] Every acquired HTML page produces one versioned normalized `PageSnapshot`, or a typed skipped/failure outcome.
- [ ] Internal link edges are persisted and queryable for inlinks/outlinks, depth, broken-link, redirect, and orphan-candidate analysis.
- [ ] A versioned rule registry evaluates page, link, and run checks idempotently.
- [ ] Initial deterministic SEO rules cover crawlability/indexability, response codes, titles/descriptions, headings/content, canonicals/directives, links, images, structured data, and selected security checks.
- [ ] Initial deterministic AEO rubric exposes evidence by dimension without presenting heuristic output as objective truth.
- [ ] Audit APIs support server-side pagination, filtering, sorting, issue aggregation, page details, link details, and exports.
- [ ] Live UI shows dynamically changing discovery and analysis counters and remains usable during a multi-thousand-page crawl.
- [ ] Selecting an issue filters affected URLs; selecting a URL loads evidence, remediation, inlinks, outlinks, headers, and structured-data details.
- [ ] CSV/JSON exports exist for pages, links, findings, and run summary.
- [ ] A repeat audit can compare added/removed/changed URLs and findings after the MVP is stable.
- [ ] Private-network targets, DNS rebinding attempts, cross-scope redirects, crawl traps, and excessive resource use are blocked or bounded.
- [ ] Existing extraction crawl behavior and contracts remain unchanged.
- [ ] Focused backend, frontend, policy, and E2E verification exits 0.

---

## Do Not Touch

- `backend/app/extraction/*` — the active Extraction V3 plan owns this area; SEO/AEO analysis is a separate bounded context.
- Product/listing extraction contracts and record-resolution behavior — audit pages are not extraction records.
- Acquisition behavior or public result shapes unless a missing field is added through a backward-compatible adapter contract.
- Existing `CrawlUrlResult.data` as the primary audit datastore — dedicated indexed tables are required.
- Current run/log/export routes in a way that breaks existing clients; add audit-specific routes or backward-compatible run-type dispatch.
- Global frontend crawl record/learning components; share only generic hooks/primitives.
- Unrelated unstaged changes already present on the audited branch.

---

## Slices

Execution order is strict within each phase. The current active Extraction V3 plan remains the repository's active plan; this plan should be added to `docs/plans/ACTIVE.md` as queued, not substituted, until explicitly activated.

### Phase 0 — Contracts, product decisions, and evaluation fixtures

#### Slice 0.1: Lock audit semantics and settings

**Status:** TODO  
**Files:** `backend/app/site_audit/settings.py`, `contracts.py`, schema tests, API request schema, planning docs  
**What:** Define scope, normalization, query-parameter policy, robots behavior, browser fallback, budgets, data retention, progress counters, issue taxonomy, and deterministic-versus-experimental semantics. Store a versioned immutable settings snapshot.  
**Verify:** schema tests reject invalid/unsafe combinations and round-trip every supported setting.

#### Slice 0.2: Build a fixture corpus and expected findings

**Status:** TODO  
**Files:** `backend/tests/fixtures/site_audit/*`, fixture manifest, expected finding snapshots  
**What:** Add small static sites covering redirects, sitemap indexes, robots, canonicals, noindex, duplicate metadata/content, hreflang, broken links, images, malformed/valid structured data, JS-rendered metadata, and crawl traps. Include at least one synthetic multi-host scope case.  
**Verify:** fixture server starts offline and expected URL/link/finding counts are deterministic.

#### Slice 0.3: Freeze performance and safety budgets

**Status:** TODO  
**Files:** benchmark harness and test configuration  
**What:** Define target sizes for 100, 1,000, and 10,000-page synthetic audits; memory bounds; DB query latency targets; maximum evidence payloads; and crawl-rate behavior.  
**Verify:** baseline benchmark report is generated before feature implementation.

---

### Phase 1 — Generic domain discovery and page snapshots

#### Slice 1.1: URL normalization, scope, and trap policy

**Status:** TODO  
**Files:** `normalization.py`, `scope.py`, tests  
**What:** Implement canonical URL identity without conflating SEO canonical declarations; fragment removal; host/scheme/default-port normalization; path/query policy; include/exclude patterns; subdomain policy; tracking-parameter rules; depth/pattern/duplicate limits; cross-scope redirect handling.  
**Verify:** table-driven and property-based tests cover equivalent URLs, non-equivalent URLs, Unicode/IDN, percent encoding, path case, query order/repetition, malformed URLs, private targets, and traps.

#### Slice 1.2: Persistent frontier and seed discovery

**Status:** TODO  
**Files:** `frontier.py`, `discovery.py`, models, migration, worker/service tests  
**What:** Add deduplicated persistent frontier state, seed homepage, parse robots sitemap directives, try configured sitemap candidates, recurse sitemap indexes safely, enqueue same-scope HTML links, and support resume/leases. Reuse public-target validation and robots policy.  
**Verify:** fixture crawl discovers the expected union exactly once, resumes after injected worker failure, and never fetches disallowed/private/out-of-scope targets.

#### Slice 1.3: Acquisition adapter and normalized `PageSnapshot`

**Status:** TODO  
**Files:** `snapshot.py`, `html_analyzer.py`, `structured_data.py`, adapter tests  
**What:** Convert `PageAcquisitionResult` into a bounded stable snapshot: response, headers, directives, metadata, headings, visible text/hash, canonicals/hreflang, links, images/resources, structured-data summary, fetch lane, and timing. HTTP-first/browser fallback remains an acquisition decision exposed through audit settings.  
**Verify:** source and rendered fixture variants produce expected snapshots; snapshot schema remains stable across fetch lanes.

#### Slice 1.4: Page and link persistence

**Status:** TODO  
**Files:** audit models, Alembic migration, `crud.py`, indexes, repository tests  
**What:** Persist pages, redirect observations, deduplicated links, structured-data evidence references, and analyzer versions. Add indexes for run/status/content type/indexability/title/canonical/depth/rule queries.  
**Verify:** migration upgrade/downgrade succeeds; query-plan tests or measured explain plans cover the primary list/filter/aggregate paths.

---

### Phase 2 — Deterministic SEO rule engine

#### Slice 2.1: Rule registry and finding lifecycle

**Status:** TODO  
**Files:** `rules/registry.py`, finding model/CRUD, tests  
**What:** Add typed rule definitions, stable IDs/versions, applicability, evidence schemas, remediation metadata, deterministic/experimental flags, idempotent replacement, and suppression-ready fingerprints.  
**Verify:** rerunning the same analyzer version yields no duplicate findings; version changes coexist or replace according to explicit policy.

#### Slice 2.2: Page-level technical and content rules

**Status:** TODO  
**Files:** crawlability, metadata, content, canonical, image, structured-data, security rules  
**What:** Implement the initial page-level catalogue with focused evidence and configurable thresholds. Avoid misleading pixel/Core Web Vitals claims unless those measurements are actually captured.  
**Verify:** golden fixture tests assert exact rule IDs, priorities, and evidence.

#### Slice 2.3: Link-graph and run-level rules

**Status:** TODO  
**Files:** links rules, run rules, graph queries  
**What:** Implement broken links, redirecting links, no-anchor links, no-inlink/orphan candidates, depth, isolated components, sitemap/internal-link mismatches, duplicate clusters, and cross-page entity consistency checks.  
**Verify:** fixture graph produces exact affected URL counts and denominators.

#### Slice 2.4: Incremental aggregation and transparent category scoring

**Status:** TODO  
**Files:** `aggregation.py`, `scoring.py`, metrics, tests  
**What:** Maintain issue counts and percentages while pages arrive. Define category scores from documented weights/denominators, expose incomplete-crawl status, and keep raw counts authoritative.  
**Verify:** incremental aggregates equal a clean full recomputation after completion.

---

### Phase 3 — Audit APIs, live progress, and exports

#### Slice 3.1: Audit run endpoints and actions

**Status:** TODO  
**Files:** `backend/app/api/site_audits.py`, request/response schemas, dispatch integration, component tests  
**What:** Add create/get/list, pause/resume/kill, settings summary, progress counters, and comparison references. Reuse authentication, ownership, dispatch, and run-control behavior.  
**Verify:** component tests cover authorization, validation, state transitions, and unsafe-domain rejection.

#### Slice 3.2: Query APIs

**Status:** TODO  
**Files:** audit API routes and CRUD queries  
**What:** Add paginated/sorted/filtered page inventory, issue aggregates, affected pages, page detail, inlinks, outlinks, structured data, and finding evidence. Filters must be typed and allowlisted rather than raw SQL-like expressions.  
**Verify:** API tests cover combined filters, stable cursors/pages, sorting, empty states, and large result counts.

#### Slice 3.3: Live event stream

**Status:** TODO  
**Files:** audit event serializer, websocket/polling endpoints, frontend API contracts  
**What:** Emit bounded progress/aggregate/page-update events. Reuse the existing websocket reconnect plus polling fallback pattern; do not stream full HTML or unbounded findings.  
**Verify:** reconnect and polling fallback preserve monotonic counters without duplicate UI rows.

#### Slice 3.4: Exports

**Status:** TODO  
**Files:** `exports.py`, routes, export tests  
**What:** Stream CSV/JSON for pages, links, findings, and summary, with selected filters and rule/analyzer versions included.  
**Verify:** exports handle zero rows and large paged datasets without loading the whole audit into memory.

---

### Phase 4 — Screaming Frog-inspired audit workspace

#### Slice 4.1: Route, configuration screen, and audit query state

**Status:** TODO  
**Files:** new site-audit route/page, config components, API client, query keys, tests  
**What:** Add domain/scope/limit/rendering settings and persist run/facet/filter/sort/selection state in URL parameters.  
**Verify:** configuration validation and deep-link restoration tests pass.

#### Slice 4.2: Live control bar and URL grid

**Status:** TODO  
**Files:** run screen, control bar, URL grid, data hooks, tests  
**What:** Show dynamic frontier counters and actions. Build a virtualized, server-driven grid with column presets, selection, resizing, sorting, filtering, and incremental refresh that does not jump the viewport. Add a grid dependency only after checking existing primitives and bundle budget.  
**Verify:** component tests cover live updates, filters/sort, pagination, selection persistence, and 10,000 synthetic rows without rendering every DOM row.

#### Slice 4.3: Facets and issue summary pane

**Status:** TODO  
**Files:** facet tabs, issue summary, query-state integration  
**What:** Implement named facets and issue aggregate rows matching the attached interaction model: issue type, priority, affected count, percentage, category, and experimental badge. Issue selection updates the URL query.  
**Verify:** selecting/clearing an issue produces the expected server request and preserves unrelated filters.

#### Slice 4.4: Context details pane

**Status:** TODO  
**Files:** details shell, URL/findings/links/headers/structured-data panels  
**What:** Add synchronized contextual inspection with evidence and remediation, inlinks/outlinks, redirect/header data, structured-data blocks, and source/rendered summaries. Load expensive panes lazily.  
**Verify:** stale requests are cancelled when selection changes; accessibility keyboard/focus tests pass.

#### Slice 4.5: Responsive, accessibility, and E2E pass

**Status:** TODO  
**Files:** CSS/layout, component tests, `frontend/e2e/site-audit.spec.ts`  
**What:** Preserve dense desktop usability while allowing collapsed issue/details drawers at smaller widths. Add keyboard navigation, labels, empty/error/loading states, and export flow.  
**Verify:** focused `vp check`, `vp test`, policy checks, and Playwright audit flow exit 0.

---

### Phase 5 — AEO readiness

#### Slice 5.1: Deterministic AEO rules

**Status:** TODO  
**Files:** `rules/aeo.py`, structured-data/entity helpers, tests, UI facet  
**What:** Implement the deterministic dimensions in this plan with page-type applicability, evidence, and category rollups.  
**Verify:** golden fixtures distinguish applicable, passing, failing, and insufficient-evidence outcomes.

#### Slice 5.2: AEO evaluation corpus

**Status:** TODO  
**Files:** labeled corpus, scorer, report  
**What:** Create a human-reviewed cross-page-type corpus before introducing model-based AEO checks. Define precision/recall or agreement metrics per heuristic and false-positive budgets.  
**Verify:** corpus and frozen deterministic baseline run offline.

#### Slice 5.3: Optional evidence-grounded heuristic checks

**Status:** TODO  
**Files:** experimental analyzer adapter, settings, metrics, tests  
**What:** Add only heuristics that beat the corpus baseline. Ground outputs to text/DOM paths, include confidence/model/prompt version, cap costs, and keep them excluded from deterministic totals by default.  
**Verify:** evaluation gate and grounding/cost limits pass; disabling the feature makes no provider calls.

---

### Phase 6 — Historical comparison and production hardening

#### Slice 6.1: Repeat-audit comparison

**Status:** TODO  
**Files:** comparison queries, API, frontend diff views, tests  
**What:** Compare normalized URL inventories, snapshots, status/indexability/metadata changes, finding additions/removals, duplicate-cluster movement, and aggregate trends.  
**Verify:** fixture audit v1→v2 produces exact added/removed/changed findings without treating rule-version changes as page regressions.

#### Slice 6.2: Scale, retention, and observability hardening

**Status:** TODO  
**Files:** query/index tuning, retention jobs, metrics/dashboards, load tests  
**What:** Test multi-worker frontier claims, backpressure, per-host politeness, browser budget, DB batching, retention, artifact cleanup, cancellation, and degraded external dependencies.  
**Verify:** target-scale benchmark stays within the Phase 0 budgets and leaves no stuck leases after forced failures.

#### Slice 6.3: Production rollout

**Status:** TODO  
**Files:** feature flags, deployment/config docs, runbooks  
**What:** Roll out behind an audit feature flag with conservative limits, metrics, and an operator kill switch. Expand defaults only after observed resource and finding-quality data.  
**Verify:** staged smoke audit, rollback procedure, and operational alerts are tested.

---

## Verification Commands

Exact focused paths should be adjusted to the final test layout, but the repository-supported command style is:

```powershell
# Backend
cd backend
uv run pytest tests/unit/site_audit tests/component/test_site_audits_api.py -q
uv run ruff check app/site_audit app/api/site_audits.py tests/unit/site_audit tests/component/test_site_audits_api.py
uv run mypy app/site_audit

# Frontend
cd frontend
pnpm check
pnpm test -- components/site-audit
pnpm check:policy
pnpm test:e2e -- --grep "site audit"
```

Do not make the full backend test suite a default slice gate. Run the focused tests named by each slice, plus affected regression tests for shared run/acquisition contracts.

---

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — site-audit bounded context, data flow, persistence, worker/frontier behavior, API ownership.
- [ ] `docs/frontend-architecture.md` — audit route, synchronized three-pane workspace, server query state, virtualization.
- [ ] `docs/CODEBASE_MAP.md` — new packages, models, routes, and frontend ownership.
- [ ] `docs/INVARIANTS.md` — URL identity, scope/SSRF, robots, frontier idempotency, rule versioning, evidence limits.
- [ ] `docs/ENGINEERING_STRATEGY.md` — audit-vs-extraction boundary and dynamic-frontier pattern.
- [ ] `docs/plans/ACTIVE.md` — add this plan to Queue while Extraction V3 remains active; activate only on explicit approval.
- [ ] Operator documentation — crawl budgets, robots behavior, experimental AEO semantics, retention, exports, and comparison caveats.

---

## Risks and Required Safeguards

| Risk | Required control |
|---|---|
| SSRF/private targets | Validate every seed, redirect hop, sitemap URL, and discovered URL; protect against DNS rebinding |
| Crawl traps | Pattern/depth/page/time/query budgets; repeated-content detection; operator-visible skip reasons |
| Site overload | Per-host rate/concurrency limits, backoff, Retry-After support, pause/kill |
| Infinite dynamic frontier | Persisted budgets and terminal “limit reached” outcome distinct from completed exhaustion |
| URL identity mistakes | Property-tested normalization; keep observed canonical separate from crawler dedup identity |
| Browser cost explosion | HTTP-first policy, explicit fallback reasons, per-run browser budget |
| Huge evidence/HTML | Bounded evidence, artifact references, retention TTL, no HTML in websocket events |
| Rule churn | Stable IDs, versions, analyzer snapshot, version-aware comparisons |
| Misleading AEO score | Transparent dimensions, applicability, evidence, confidence, experimental separation |
| Slow UI/DB | Server pagination/filter/sort, indexes, virtualization, incremental aggregates |
| Orphan-page overclaim | Distinguish sitemap-only/no-inlink candidates from proven orphans; pure crawl cannot know every external source |
| Existing feature regression | Dedicated bounded context and focused shared-contract regression tests |

---

## Notes

- The audited branch already has unrelated unstaged extraction changes and an active Extraction V3 plan. This plan deliberately avoids implementation or modifications to those files.
- ThinkForge's current workspace connection exposed read-only audit tools, so this document was produced as a standalone plan artifact rather than written into `C:\Projects\CrawlerAI`.
- When repository write access is available, place this file at `docs/plans/site-seo-aeo-audit-plan.md` and add it to the queue in `docs/plans/ACTIVE.md`; do not replace the active extraction plan.
- The existing runtime is a strong foundation, but this is not a small extension to the current category crawler. The dynamic frontier, audit data model, rule registry, link graph, and dedicated UI are first-class product subsystems.
