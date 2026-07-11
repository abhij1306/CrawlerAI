# CrawlerAI Site Audit V2
## HTTP-Only SEO, AEO and GEO Architecture & Delivery Plan

**Date:** 2026-07-11  
**Status:** Implementation plan; no code changes made  
**Repository audited:** `C:\Projects\CrawlerAI`  
**Product route:** `/site-audit`  
**API root:** `/api/site-audits`

---

## 1. Executive decision

Build Site Audit as a new bounded product area rather than extending the extraction-oriented Crawl Studio screen or storing audit data in `CrawlRecord.data`.

The first production release must have these hard properties:

1. **HTTP-only acquisition.** No Playwright, browser fallback, JavaScript execution, scrolling, screenshots, network replay or product extraction logic. A page that requires client rendering is reported as an HTTP rendering gap; it is not silently re-fetched with a browser.
2. **A persistent dynamic frontier.** The URL set grows while crawling from robots sitemap directives, sitemap indexes, sitemap URL sets and same-scope HTML links.
3. **Up to 50 global in-flight HTTP requests per audit run.** This is a concurrency target, not a promise of 50 requests per second. Per-host concurrency, pacing, `Retry-After`, backoff and resource budgets still apply.
4. **Network concurrency is separated from database concurrency.** Fifty fetch slots must not mean fifty long-lived SQLAlchemy sessions. Fetch workers produce bounded results into queues; a small writer pool persists batches.
5. **Deterministic SEO and AEO checks are the core audit.** Model-based checks are optional, evidence-grounded, versioned, budgeted and excluded from deterministic scores by default.
6. **GEO visibility is a related but separate product capability.** Site crawling can assess readiness and accessibility; it cannot truthfully claim a brand's share of voice or ranking in ChatGPT, Perplexity, Gemini or Google AI surfaces. Prompt monitoring needs its own run type, persistence and disclosures.
7. **Server-log AI crawler analytics is a future connector.** A site crawl cannot determine which AI bots actually visited a production site. That requires edge/CDN/server logs and verified crawler identity.

### Recommended delivery boundary

The implementation should be split into three clearly separated capabilities:

- **Site Audit MVP:** HTTP crawling, technical SEO, content structure, structured data, AEO readiness, AI crawler accessibility, issue workspace and exports.
- **Site Audit Intelligence:** optional LLM-assisted page/template analysis after the deterministic crawl is complete.
- **AI Visibility & Agent Analytics:** later modules for prompt monitoring and server-log AI crawler activity. They should share UI vocabulary and domain identity, but not audit tables or scoring semantics.

---

## 2. Evidence reviewed

### Repository

The audit covered the run lifecycle, Celery/local dispatch, HTTP and browser acquisition, sitemap and link discovery, robots handling, URL safety, persistence, API patterns, WebSocket logging, exports, LLM runtime, frontend routing/query ownership, tests and migrations.

Key files included:

- `backend/app/crawl/batch_runtime.py`
- `backend/app/crawl/sitemap_resolver.py`
- `backend/app/crawl/site_link_discovery.py`
- `backend/app/crawl/robots_policy.py`
- `backend/app/core/url_safety.py`
- `backend/app/acquisition/runtime.py`
- `backend/app/acquisition/fetch/fetch_context.py`
- `backend/app/models/crawl_run.py`
- `backend/app/crawl/service.py`
- `backend/app/tasks.py`
- `backend/app/core/celery_app.py`
- `backend/app/connectors/llm/*`
- `backend/app/main.py`
- `frontend/src/app/route-registry.ts`
- `frontend/src/api/query-keys.ts`
- `frontend/lib/api/crawls.ts`
- `frontend/components/crawl/*`
- `frontend/package.json`

### Supplied artifacts

- Screaming Frog desktop UI screenshot.
- Fifty CSV exports containing overview and affected-URL/link/resource reports.

### External product and search-engine research

The feature taxonomy below was cross-checked against current official materials for Ahrefs Brand Radar/Bot Analytics, Profound Answer Engine Insights/Agent Analytics, Google Search Central AI guidance and OpenAI crawler controls.

---

## 3. Architecture decisions and rationale

These decisions follow from the audited repository, the HTTP-only performance requirement, the supplied Screaming Frog issue exports and the need to keep deterministic site evidence separate from prompt-based AI visibility measurement.

| Decision | Rationale |
|---|---|
| **HTTP-only hard invariant for Site Audit MVP** | Preserves speed, makes the received server response auditable and avoids silently masking rendering gaps with browser fallback. |
| Request/settings contracts in `site_audit/contracts.py`; environment tunables in `backend/app/core/config/site_audit.py` | Matches current repository ownership for API contracts and runtime configuration. |
| Build an audit coordinator/frontier runtime | The existing crawl loop assumes a fixed URL list and creates all tasks up front; a site audit must discover URLs continuously. |
| Persist pages, links, resources/images and structured-data blocks separately | The supplied issue reports distinguish page, target/resource and occurrence counts; one generic record cannot represent them accurately. |
| Typed, sequenced audit events with aggregate deltas | Supports a fast live workspace without treating extraction logs as the frontend data contract. |
| Deterministic AEO and AI-crawler accessibility rules in the initial registry | These are source-verifiable checks and should not depend on LLM availability. |
| Separate crawl-based readiness, prompt-based AI visibility and server-log agent analytics | Each uses a different evidence source and must have different scoring and disclosure semantics. |
| Use the current Vite/React route registry, central query keys and API chokepoint | Integrates with the existing frontend without importing extraction-specific UI ownership. |
| Add a new additive Alembic revision after `20260703_0001` | Keeps the current baseline immutable and makes the feature independently deployable. |

---

## 4. Current architecture assessment

### 4.1 Reusable foundations

| Area | Existing capability | Reuse decision |
|---|---|---|
| Run lifecycle | pending/running/paused/terminal states, task IDs, heartbeats, leases, stale-run recovery | Reuse through a run-kind-aware control contract |
| Dispatch | Celery and local dispatchers | Reuse patterns; add a site-audit task instead of routing through extraction `process_run` |
| HTTP transport | shared `httpx.AsyncClient`, connection pooling, timeouts, configured user agent | Reuse the client/building blocks through a narrow audit fetcher |
| URL safety | scheme validation, DNS resolution, private/loopback/link-local/reserved/CGNAT blocking | Mandatory for seed, discovered URL, sitemap and every redirect hop |
| Robots | cached robots snapshot with in-flight deduplication | Extend to expose sitemap directives and harden redirect/safety behavior |
| Sitemaps | XML parsing, sitemap indexes, URL sets, public-target checks | Reuse parsing ideas; replace category filters and sequential child traversal |
| HTML abstraction | `HtmlDocument` and safe selectors | Reuse only if it remains extraction-independent and benchmarked; otherwise use a dedicated parser adapter |
| API access | ownership checks, typed schemas, pagination patterns | Reuse patterns in a separate router |
| Live UI | WebSocket reconnect plus polling fallback | Reuse behavior, not extraction log payloads |
| LLM runtime | provider config, encrypted/env keys, prompt registry, cache, budgets, cost log, validation | Reuse for optional audit task types |
| Frontend shell | route registry, TanStack Query, generic primitives, history drawer | Reuse without importing extraction-specific record/learning components |

### 4.2 Gaps that require new first-class components

1. The current batch runtime resolves a fixed URL list before processing. Site auditing needs a frontier that expands during execution.
2. Existing rendered link discovery is category/listing-specific and browser-preferred. It intentionally discards ordinary informational pages.
3. Current default URL concurrency is eight, and local dispatch forces one. The new audit needs an explicit HTTP audit concurrency model.
4. The current run task internally creates one task per known URL and each URL owns a database session. That design should not be scaled directly to fifty concurrent fetches.
5. Existing HTTP acquisition applies product/platform block heuristics and may attempt multiple transports. A technical audit needs a stable, observable selected user agent/transport and must preserve the received status rather than trying to bypass it.
6. `PageFetchResult` does not expose a complete audit response contract such as redirect hops, response elapsed time, bytes transferred, decoded size and truncation reason.
7. Existing robots handling does not expose `Sitemap:` directives and does not clearly apply the same redirect-hop URL safety checks as sitemap fetching.
8. Existing persistence is extraction-oriented and cannot efficiently filter or aggregate hundreds of audit dimensions.
9. The frontend table is a regular DOM table, and the current run screen is extraction-centric. A large, continuously updating audit needs server queries and row virtualization.
10. No rule registry currently defines stable IDs, versions, applicability, evidence schemas or denominators.

---

## 5. Product scope

### 5.1 In scope for the initial Site Audit release

- One public HTTP/HTTPS seed URL.
- Exact host by default, optional `www` equivalence and subdomain inclusion.
- Discovery through:
  - seed page;
  - `Sitemap:` directives in `robots.txt`;
  - conventional sitemap candidates;
  - nested sitemap indexes;
  - same-scope links in returned HTML.
- HTTP GET crawling with configurable user agent, authentication headers only when explicitly supported, redirect limit and body limits.
- Optional internal/external resource status checks under separate budgets.
- Deterministic SEO, structured-data, security-header, accessibility-to-crawlers and AEO-readiness checks.
- Live progress, issue aggregation, URL inventory, evidence panes and exports.
- Pause, resume, stop, retry failed URLs and rerun.
- Historical comparison after the MVP query/data model is stable.

### 5.2 Explicit non-goals for MVP

- JavaScript rendering or rendered-DOM assertions.
- Real-user Core Web Vitals or Lighthouse lab scores.
- Search rankings, traffic estimates or backlink indexes.
- Automatic CMS patches or content publication.
- Claiming `llms.txt` is required for AI visibility.
- Claiming an API-model benchmark equals consumer ChatGPT Search, Perplexity, Gemini or Google AI results.
- Detecting real AI crawler visits without server/edge logs.
- Downloading full image, video, font or document bodies by default.

### 5.3 Honest HTTP-only evidence labels

Every field must indicate its evidence origin where ambiguity matters:

- `http_source`: found in returned response HTML.
- `response_header`: derived from HTTP headers.
- `sitemap`: found in a sitemap.
- `robots`: found in robots policy.
- `inferred`: deterministic derivation from persisted evidence.
- `not_observable_http_only`: requires rendering, user data, search-engine data or server logs.

A page with very little source text and substantial script/app shell signals should emit a rule such as `rendering.http_source_thin`, not a false statement that its rendered page has no content.

---

## 6. Target backend architecture

### 6.1 Bounded context

Create:

```text
backend/app/site_audit/
├── __init__.py
├── contracts.py
├── normalization.py
├── scope.py
├── traps.py
├── robots.py
├── sitemaps.py
├── discovery.py
├── frontier.py
├── http_fetcher.py
├── snapshot.py
├── html_analysis.py
├── structured_data.py
├── link_graph.py
├── resources.py
├── coordinator.py
├── worker.py
├── writer.py
├── aggregation.py
├── scoring.py
├── events.py
├── crud.py
├── exports.py
├── comparison.py
├── llm_analysis.py
├── metrics.py
└── rules/
    ├── registry.py
    ├── crawlability.py
    ├── response.py
    ├── urls.py
    ├── metadata.py
    ├── headings.py
    ├── content.py
    ├── canonicals.py
    ├── hreflang.py
    ├── links.py
    ├── resources.py
    ├── structured_data.py
    ├── security.py
    ├── sitemaps.py
    ├── aeo.py
    └── ai_crawlers.py
```

Repository-owned supporting files:

```text
backend/app/core/config/site_audit.py
backend/app/models/site_audit.py
backend/app/schemas/site_audit.py
backend/app/api/site_audits.py
backend/app/site_audit/tasks.py
backend/alembic/versions/<next_revision>_site_audit.py
```

The package may import stable core contracts for database sessions, URL safety, metrics, authentication, logging and shared HTTP client creation. It must not import product extraction collectors, adapters, field resolution, product persistence, browser runtime or network replay.

### 6.2 Runtime data flow

```text
POST /api/site-audits
        |
        v
Create CrawlRun(run_type=site_audit) + SiteAuditRun
        |
        v
Dispatch site_audit.process_run
        |
        v
Audit Coordinator
  ├─ seed validation / robots / sitemap discovery
  ├─ persistent frontier claims
  ├─ bounded HTTP fetch queue (up to 50 global in flight)
  ├─ bounded parse/analyse queue
  ├─ small batched DB writer pool
  ├─ incremental issue aggregation
  └─ sequenced progress events
        |
        v
Complete when frontier is exhausted or a persisted budget is reached
```

### 6.3 Concurrency model

#### Proposed defaults to validate in Phase 0

| Control | Proposed default | Reason |
|---|---:|---|
| Global page fetch concurrency | 50 | User requirement and existing HTTP pool capacity |
| Per-origin page concurrency | 8 | Prevent a single site from receiving all 50 simultaneous connections |
| Minimum start interval per origin | 100–250 ms profile-dependent | Politeness and rate-limit protection |
| Parser/analyser concurrency | 4–8 | CPU work should not block the event loop |
| DB writers | 1 per run initially | Ordered, batched persistence and low connection pressure |
| Page write batch | 25–50 pages or 250 ms | Bound transaction size and UI latency |
| Link/resource write batch | 250–1,000 rows | Reduce per-row insert overhead |
| Event flush | at most 1 Hz plus terminal transitions | Avoid UI/DB event storms |
| HTML decoded body cap | 5 MB | Memory/trap control; configurable |
| Sitemap decoded body cap | 20–50 MB | Large sitemap support with a hard safety ceiling |

These are not final constants. The benchmark fixture must establish safe values for the actual database, worker count and deployment memory.

#### Important implementation rule

A fetch worker must not hold a database session while awaiting the network. Frontier claims occur in short transactions. The claimed work is copied into an in-memory bounded queue, fetched, parsed and then submitted to the writer as a typed result.

#### Queue layout

```text
frontier claim batch
      |
      v
bounded fetch queue
      |
      +--> N asynchronous HTTP fetch coroutines
                  |
                  v
          bounded analysis queue
                  |
                  +--> parser/analyser workers via asyncio.to_thread or measured process pool
                              |
                              v
                      bounded persistence queue
                              |
                              +--> batch writer + aggregate updater
```

Backpressure must propagate from the writer to analysis and fetch. The coordinator must never materialize all site URLs or all HTML in memory.

### 6.4 Worker topology

#### MVP topology

Use one Celery task per audit run, matching the existing one-task-per-run operational model. Inside that task, run the asynchronous coordinator with up to fifty fetch coroutines, a bounded parser pool and one batch writer.

This is the least risky reuse of existing task IDs, pause/kill semantics, heartbeats and worker lifecycle. It avoids the overhead and race complexity of one Celery task per URL.

#### Scale-out topology after measurement

When one run must span multiple worker processes, workers should claim frontier rows through PostgreSQL using a short lease and `FOR UPDATE SKIP LOCKED`. The coordinator remains the run owner/aggregator. Distributed mode should be introduced only after the single-task architecture passes 10,000-page benchmarks.

Do not distribute by enqueuing tens of thousands of independent URL tasks without a persisted frontier, host-level rate limiter and idempotent writer.

### 6.5 Celery registration and run control

The current Celery app includes only `app.tasks`. Add `app.site_audit.tasks` to the explicit include/import list and register a named task such as `site_audit.process_run`.

Create an audit dispatcher conforming to the existing run-dispatch protocol, or generalize the dispatcher to choose a task by `run_type`. Pause/resume/kill logic must resolve the correct task object instead of always importing `app.tasks.process_run_task`.

Do not add Site Audit branching throughout `crawl/batch_runtime.py`; the audit coordinator is a separate execution engine.

---

## 7. HTTP acquisition contract

### 7.1 Narrow audit response type

Define an audit-owned response contract rather than passing extraction `PageAcquisitionResult` through the analyzer:

```text
AuditHttpResponse
- requested_url
- final_url
- redirect_hops[]
  - from_url
  - to_url
  - status_code
  - location
  - elapsed_ms
- status_code
- reason_phrase
- content_type
- charset
- headers (bounded/multi-value aware)
- body_bytes or decoded_html (bounded)
- transferred_bytes
- decoded_bytes
- elapsed_ms
- dns/connect/ttfb timings when reliably available, otherwise null
- transport
- truncated
- truncation_reason
- error_type/error_message
- fetched_at
```

Do not invent timing phases that the transport does not expose. Total elapsed time is mandatory; detailed phases are optional until instrumented reliably.

### 7.2 Transport policy

- Default to the shared HTTPX infrastructure and connection pooling.
- Use one configured transport/user-agent identity for a run.
- Do not automatically switch to browser or anti-bot bypass modes after 403/429.
- Treat status codes and blocks as audit evidence.
- Allow an advanced explicit transport profile later, but record it in the immutable run settings.
- Follow redirects manually or through a hook that validates every hop before it is requested.
- Revalidate the final target and every discovered/sitemap target using the public-target policy.
- Add a DNS-rebinding-safe connection strategy or document the residual risk; pre-request resolution alone is not sufficient evidence of pinning.

### 7.3 Retry policy

Retry only transport failures and explicitly configured transient statuses such as 408, 425, 429 and selected 5xx responses. Respect `Retry-After`, use exponential backoff with jitter and cap attempts. Do not retry deterministic 4xx responses or loop through alternate transports.

Persist each terminal outcome and the attempt summary, not unbounded exception traces.

### 7.4 Resource checks

Resource crawling must use an independent queue and budget:

- HTML pages: enabled by default.
- Internal images/CSS/JS/documents: status checking optional.
- External links/resources: off by default or tightly capped.
- Prefer `HEAD` only for resource metadata when the host is known to support it; fall back to a bounded ranged `GET` on 405/501 or unusable metadata.
- Never download complete large assets only to obtain size/status.
- Store occurrence counts and first-seen evidence separately from unique resource identity.

---

## 8. URL identity, scope and trap control

### 8.1 Crawler identity versus declared canonical

The frontier deduplication key is a crawler normalization decision. It must never be replaced by the page's declared canonical URL.

Normalization must explicitly define:

- fragment removal;
- lowercase scheme/host;
- default-port removal;
- IDN normalization;
- percent-encoding normalization without changing path semantics;
- path case preservation;
- empty path handling;
- query ordering and repeated parameter behavior;
- configured tracking-parameter removal;
- optional trailing-slash policy only when selected by the user;
- no global lowercasing of path or query.

### 8.2 Scope decisions

Persist a typed decision for every observed target:

- in scope and enqueueable;
- in scope but excluded by pattern;
- disallowed by robots;
- out of host/subdomain scope;
- unsupported scheme;
- private/unsafe target;
- trap budget exceeded;
- resource-only;
- observation-only canonical/hreflang;
- invalid URL.

### 8.3 Crawl-trap controls

- page, depth, duration and byte budgets;
- per-pattern URL limits;
- maximum unique query combinations per path;
- calendar/date sequence detection;
- faceted-navigation growth detection;
- repeated near-identical content limits;
- redirect-loop and maximum-hop handling;
- maximum links extracted per page;
- maximum URL length;
- include/exclude regex validation and execution time bounds;
- terminal run outcome `limit_reached` distinct from `frontier_exhausted`.

---

## 9. Persistent data model

Use dedicated indexed tables. JSONB is appropriate for bounded variable evidence, not for every filterable audit column.

### 9.1 `site_audit_runs`

One-to-one with `crawl_runs`.

Key fields:

- `crawl_run_id` primary/foreign key;
- `settings_version` and immutable settings snapshot;
- analyzer and rule-set versions;
- seed URL, validated seed origin and final authoritative origin;
- completion reason;
- incomplete/limit-reached flags;
- rule-set hash;
- optional baseline audit ID;
- aggregate summary cache;
- event sequence counter;
- created/started/completed timestamps.

### 9.2 `site_audit_frontier`

- ID and run ID;
- normalized URL key;
- requested URL;
- source page/frontier ID;
- discovery source;
- depth;
- priority;
- state: observed, queued, leased, fetched, analysed, skipped, failed;
- scope, robots and trap decisions;
- lease owner/expiry;
- attempt count and next-attempt time;
- terminal error code;
- first/last seen timestamps;
- unique `(run_id, normalized_url_key)`.

Indexes must support queue claims, state counts, depth queries and stale lease recovery.

### 9.3 `site_audit_pages`

Filterable columns should include:

- requested, normalized and final URLs;
- status/status group;
- content type and charset;
- indexability and reason;
- depth and discovery source;
- redirect count/final target;
- response elapsed, transferred and decoded bytes;
- body truncation state;
- title, title character length and optional measured-width estimate version;
- meta description and length;
- canonical count/value/status;
- robots directives and `X-Robots-Tag` summary;
- H1/H2 counts and primary values;
- language and hreflang counts;
- visible source text word count;
- source-text hash and duplicate cluster IDs;
- readability values with formula/version;
- internal/external inlink/outlink counts;
- image/resource counts and issue counters;
- structured-data type/error counts;
- parser/analyzer versions;
- fetched/analyzed timestamps.

Large headers, redirect details, bounded source excerpts and variable arrays belong in JSONB or artifact references.

### 9.4 `site_audit_redirect_hops`

Persist one row per hop when detailed redirect investigation is enabled. This avoids embedding an unqueryable redirect chain in every page row.

### 9.5 `site_audit_links`

Use a deduplicated source-target observation row with `occurrence_count`, while retaining enough first-seen evidence for debugging:

- source page;
- raw href and resolved target;
- target normalized key/page ID;
- internal/external classification;
- link type/path type;
- anchor text, image alt fallback and position;
- rel tokens, target, hreflang;
- follow/nofollow/sponsored/ugc flags;
- first DOM path/selector or compact locator;
- occurrence count;
- source evidence kind.

This model is required because the supplied CSVs contain many more link occurrences than affected source URLs.

### 9.6 `site_audit_resources`

Unique resource per run and normalized URL:

- kind: image, stylesheet, script, font, document, media, other;
- internal/external;
- observed/fetched status;
- content type;
- transferred/declared size;
- width/height declarations where observed;
- response/error metadata;
- occurrence count.

### 9.7 `site_audit_resource_occurrences`

Add only when occurrence-level evidence is required for alt text, dimensions or source position. This can be compacted or retained for a shorter period than unique resources.

### 9.8 `site_audit_structured_data_blocks`

- page ID;
- syntax: JSON-LD, microdata, RDFa;
- block index/type summary;
- parse status/errors;
- primary entity IDs/types;
- bounded normalized payload or artifact reference;
- content fingerprint.

### 9.9 `site_audit_findings`

- run ID;
- scope: page, link, resource, structured-data block, run;
- target ID;
- stable rule ID and rule version;
- category/subcategory;
- issue class: error, warning, opportunity, informational;
- priority: critical/high/medium/low;
- deterministic/experimental flag;
- applicability and denominator key;
- bounded evidence JSON;
- remediation key;
- fingerprint;
- confidence/model/prompt version when experimental;
- suppression/status fields reserved for later workflow.

### 9.10 `site_audit_issue_aggregates`

Maintain one compact row per run/rule/issue class as pages arrive:

- affected unique pages;
- affected unique targets;
- occurrence count;
- applicable denominator;
- percentage;
- first/last occurrence timestamps;
- incomplete flag.

Raw findings remain authoritative. Aggregate rows are a query acceleration and live-UI contract.

### 9.11 `site_audit_events`

A bounded, sequenced event/outbox table or Redis stream:

- sequence;
- event type;
- compact payload;
- created time.

It must never contain HTML, complete headers, complete findings arrays or LLM prompts/responses.

---

## 10. Rule engine contract

```text
RuleDefinition
- id
- version
- title
- description
- category/subcategory
- scope
- issue_class
- default_priority
- deterministic | experimental
- applicability(context)
- required_evidence
- denominator_key
- evaluate(context) -> RuleEvaluation
- remediation_key
```

`RuleEvaluation` supports pass, fail, not applicable and insufficient evidence. A failure can emit one or more bounded finding drafts.

Rules must satisfy:

- stable IDs survive UI wording changes;
- version changes reflect semantic changes;
- idempotent reruns for the same analyzer/rule version;
- explicit denominator and affected-unit semantics;
- bounded evidence with no full HTML;
- remediation text separated from observed evidence;
- deterministic and experimental findings never overwrite each other;
- comparison logic is rule-version aware.

---

## 11. Deterministic SEO catalogue

The initial catalogue should cover the supplied Screaming Frog categories and close technical gaps, without creating checks that HTTP-only evidence cannot support.

### 11.1 Response, crawlability and indexability

- network/no-response outcome;
- 3xx, 4xx and 5xx pages;
- redirect chain, loop, hop limit and protocol downgrade;
- internal links to redirects/errors;
- robots disallowed/missing/fetch failure;
- meta robots and `X-Robots-Tag` noindex/nofollow conflicts;
- unsupported or invalid content type;
- soft-404 candidate with threshold and evidence;
- indexability signal conflicts;
- sitemap URL blocked/non-indexable/error/redirecting;
- indexable crawled URL absent from known sitemaps;
- sitemap-only page with no internal inlinks, labeled as an orphan candidate rather than a proven orphan.

### 11.2 URL hygiene

- uppercase characters;
- spaces/non-ASCII encoding anomalies;
- underscores;
- excessive URL length;
- query parameters;
- repeated/tracking/session parameters;
- multiple URL variants collapsing to one normalized key;
- insecure HTTP URL;
- faceted/calendar/trap pattern warning.

These are warnings/opportunities, not blanket ranking failures.

### 11.3 Titles and descriptions

- missing/empty/multiple title;
- duplicate title cluster;
- short/long title using configurable character thresholds;
- optional width estimate with explicit font/algorithm/version;
- title equals H1 informational check;
- missing/empty/multiple meta description;
- duplicate description cluster;
- short/long description;
- Open Graph/Twitter metadata completeness as opportunities.

### 11.4 Headings and source content

- missing/multiple H1;
- duplicate H1 cluster;
- missing/duplicate H2;
- heading-level order anomaly;
- low source-visible word count;
- exact duplicate normalized content;
- bounded near-duplicate candidate;
- language missing/inconsistent;
- readability formula result with language/applicability guard;
- source HTML appears to be a client-rendered shell;
- no meaningful source main-content region;
- stale/missing update metadata only where page type makes it applicable.

### 11.5 Canonicals and hreflang

- missing/multiple/malformed canonical;
- canonical to redirect/error/noindex/out-of-scope page;
- self-canonical mismatch;
- conflicting header/HTML canonical;
- canonical chain/loop;
- hreflang invalid language/region;
- missing reciprocal hreflang;
- hreflang target error/non-indexable/canonical mismatch;
- multiple defaults or invalid `x-default` setup.

### 11.6 Internal link graph

- broken internal links;
- redirecting internal links;
- empty/non-descriptive anchor;
- internal nofollow;
- excessive depth;
- page with no internal outlinks;
- no-inlink/sitemap-only candidate;
- isolated strongly connected component;
- inconsistent URL variants;
- excessive links per page;
- unsafe cross-origin `_blank` without appropriate `rel`;
- external status checks only when enabled and bounded.

### 11.7 Images and resources

- broken resource;
- image over configurable transferred/declared size;
- missing alt attribute versus empty alt text as separate semantics;
- missing width/height declarations;
- mixed-content active/passive resource;
- duplicate resource URL variants;
- resource content-type mismatch;
- lazy-load source present only in custom attributes as an informational observation;
- image occurrence evidence aggregated to unique affected pages and unique images.

### 11.8 Structured data

- malformed JSON-LD/microdata/RDFa;
- unsupported/unknown type informational observation;
- required/recommended property checks tied to a validator/ruleset version;
- duplicate/contradictory primary entities;
- canonical/page/entity URL mismatch;
- breadcrumbs discontinuity;
- organization/site identity inconsistency;
- Product/Offer/Article/Person/Organization/Breadcrumb applicability;
- FAQ/HowTo visible-source mismatch only where source content is observable;
- multiple conflicting WebSite/Organization identities.

Do not claim Google rich-result eligibility unless a maintained rule profile and all required evidence exist. Label it as schema conformance/readiness.

### 11.9 Security and headers

- HTTP or downgrade redirect;
- mixed active content;
- missing/invalid Content-Security-Policy;
- missing/invalid Referrer-Policy;
- missing X-Content-Type-Options;
- missing frame protection using X-Frame-Options or applicable CSP `frame-ancestors`;
- invalid content type/charset;
- insecure cross-origin target handling;
- HSTS only when HTTPS and observation scope make the check valid;
- TLS/certificate checks only through a dedicated reliable probe, not inferred from a successful page response.

### 11.10 Sitemaps and robots

- robots unavailable/malformed/conflicting groups;
- sitemap directive invalid, unsafe, out of scope or inaccessible;
- sitemap index recursion/depth/size limit;
- sitemap duplicate URL;
- sitemap URL with fragment or unsupported scheme;
- sitemap content-type/parse errors;
- URL present in multiple sitemap groups;
- lastmod invalid/future/inconsistent as informational opportunities.

---

## 12. Deterministic AEO readiness

AEO must be a set of explainable dimensions, not one opaque score.

### 12.1 Dimensions

1. **Crawl and answer accessibility**
   - indexable and snippet-eligible signals;
   - stable canonical;
   - meaningful HTTP source content;
   - crawler access matrix;
   - no contradictory robots/snippet directives.

2. **Entity clarity**
   - consistent Organization/WebSite/Page/Article/Product/Person entities;
   - stable `@id` and URL references;
   - publisher/author identity where applicable;
   - sameAs references when present;
   - page subject/title/heading/schema alignment.

3. **Answer structure**
   - descriptive hierarchy;
   - question headings and concise answer blocks;
   - semantic lists, tables, steps, definitions and comparisons;
   - summary/key-points sections where page type makes them useful;
   - FAQ patterns in visible source content without requiring FAQ schema.

4. **Trust and provenance**
   - author, publisher, published/updated date;
   - contact/about/editorial policy discoverability as opportunities;
   - citations/source links for claim-heavy informational pages;
   - claim/source proximity heuristics only when deterministic evidence supports them.

5. **Structured consistency**
   - page-type schema;
   - breadcrumbs;
   - entity URL/canonical alignment;
   - structured values consistent with visible source values;
   - no duplicate contradictory primary entity.

6. **Coverage and navigation**
   - supporting entity/topic links;
   - definitions, procedures, comparisons and FAQs where applicable;
   - hub/detail relationships and internal paths to related content.

### 12.2 AI crawler accessibility matrix

Report separate policy rows for at least:

- Googlebot and snippet controls;
- Google-Extended where observable;
- OAI-SearchBot;
- GPTBot;
- ChatGPT-User as informational/user-triggered behavior, not a normal search crawler assumption;
- other maintained crawler profiles only when based on official documentation.

Never collapse search inclusion, model training and user-triggered retrieval into one “AI allowed” flag.

### 12.3 `llms.txt`

Observe and validate `llms.txt` only as optional informational metadata:

- presence/status/content type;
- valid links and basic format diagnostics;
- whether referenced URLs are indexable/in scope.

Do not fail an AEO readiness score because the file is absent. Current mainstream search guidance does not establish it as a universal requirement.

---

## 13. Optional LLM-assisted audit intelligence

### 13.1 Use the existing runtime

Register explicit task types, prompt files and Pydantic payload adapters through the existing LLM connector. Reuse:

- active provider configuration and encrypted/env API keys;
- immutable run config snapshots;
- provider timeouts/retries/circuit breaker;
- cache;
- per-run call budget;
- cost logging;
- typed response validation.

Do not read raw API keys inside the site-audit package.

### 13.2 Do not call a model for every page by default

After deterministic analysis:

1. group pages by template signature, page type, normalized content hash and heading/schema shape;
2. select representative pages and high-value outliers;
3. batch compact evidence rather than send complete HTML;
4. cap calls, tokens and cost;
5. persist prompt/model/rubric version and evidence references.

Proposed default: disabled. When enabled, start with a maximum of 10–20 calls per run, still bounded by the existing global run limit.

### 13.3 Suitable experimental tasks

- answer directness and extractability;
- entity ambiguity/conflict explanation;
- question/intent coverage gaps;
- claim-to-source proximity;
- citation quality classification;
- page-template content brief/opportunity summary;
- representative-page comparison across a cluster.

### 13.4 Output contract

Every model finding must contain:

- finding type;
- page/template IDs;
- bounded source excerpts or DOM/text paths;
- rationale;
- confidence;
- applicable/not-applicable state;
- model, provider, prompt and rubric versions;
- input fingerprint;
- cost/tokens;
- no deterministic score mutation.

No model output may directly write title, description, schema or body changes to a site.

---

## 14. GEO / AI visibility module: separate epic

### 14.1 Why it is separate

A crawler can measure whether content is technically accessible and well structured. It cannot derive actual brand mentions, citation share or sentiment across answer engines from site HTML.

A future `/ai-visibility` module should own prompt-based observations:

- prompt/topic library;
- market, locale and language;
- tracked brand and competitors;
- provider/engine/surface;
- repeated observations because answers vary;
- answer text fingerprint;
- brand mentions/position/share of voice;
- cited source URLs and domains;
- citation ownership/overlap;
- sentiment/themes;
- model/API/frontend evidence class;
- timestamp, model/version, cost and run metadata.

### 14.2 Disclosure requirement

Existing provider API keys can power a useful **model/API benchmark**. That output must not be labeled as consumer ChatGPT Search, Perplexity, Gemini or Google AI ranking unless the system actually captures those consumer surfaces through an authorized, reliable method.

### 14.3 Prompt generation

LLM-generated prompts may help expand a reviewed prompt set, but prompts must retain:

- origin: manual, imported, generated;
- topic/intent;
- locale;
- target audience;
- approval status;
- version.

Generated prompts should not silently change longitudinal benchmarks.

### 14.4 Future agent analytics

A separate server-log connector can later report verified AI crawler activity, crawl frequency, bot-specific 404s, low-value crawl waste and page coverage. It must ingest edge/CDN/server logs, verify crawler identity where possible and avoid client-side JavaScript analytics as the source of truth.

---

## 15. API contract

### 15.1 Run and actions

```text
POST   /api/site-audits
GET    /api/site-audits
GET    /api/site-audits/{audit_id}
POST   /api/site-audits/{audit_id}/pause
POST   /api/site-audits/{audit_id}/resume
POST   /api/site-audits/{audit_id}/kill
POST   /api/site-audits/{audit_id}/retry-failures
POST   /api/site-audits/{audit_id}/rerun
DELETE /api/site-audits/{audit_id}
```

Creation stores a validated immutable settings snapshot and returns the audit/run ID.

### 15.2 Query endpoints

```text
GET /api/site-audits/{id}/pages
GET /api/site-audits/{id}/pages/{page_id}
GET /api/site-audits/{id}/pages/{page_id}/findings
GET /api/site-audits/{id}/pages/{page_id}/inlinks
GET /api/site-audits/{id}/pages/{page_id}/outlinks
GET /api/site-audits/{id}/pages/{page_id}/resources
GET /api/site-audits/{id}/pages/{page_id}/structured-data
GET /api/site-audits/{id}/issues
GET /api/site-audits/{id}/issues/{rule_id}/targets
GET /api/site-audits/{id}/summary
GET /api/site-audits/{id}/comparison
```

Use allowlisted typed filters and sort keys. Prefer cursor/keyset pagination for large inventories, with stable secondary sorting by ID. Do not expose raw SQL-like filter syntax.

### 15.3 Live events

```text
WS  /api/site-audits/{id}/events/ws?after_sequence=
GET /api/site-audits/{id}/events?after_sequence=&limit=
```

Event types may include:

- run_state_changed;
- progress_snapshot;
- frontier_delta;
- page_batch_committed;
- issue_aggregate_delta;
- warning;
- terminal_summary.

Counters must be monotonic where semantically applicable. Reconnect uses the last sequence and polling remains the fallback.

### 15.4 Exports

```text
GET /api/site-audits/{id}/export/pages.csv
GET /api/site-audits/{id}/export/links.csv
GET /api/site-audits/{id}/export/resources.csv
GET /api/site-audits/{id}/export/findings.csv
GET /api/site-audits/{id}/export/summary.json
```

Exports accept the same typed filters as the UI and stream rows rather than loading the complete result set in memory. Include rule/analyzer versions and affected-unit semantics.

---

## 16. Frontend plan

### 16.1 Route and ownership

Add an authenticated route to `frontend/src/app/route-registry.ts`:

```text
/site-audit
```

Proposed files:

```text
frontend/app/site-audit/page-view.tsx
frontend/components/site-audit/
├── site-audit-page.tsx
├── site-audit-config-screen.tsx
├── site-audit-workspace.tsx
├── audit-control-bar.tsx
├── audit-progress-strip.tsx
├── audit-facet-tabs.tsx
├── audit-url-grid.tsx
├── audit-column-manager.tsx
├── audit-filter-builder.tsx
├── audit-issue-pane.tsx
├── audit-details-pane.tsx
├── audit-page-details.tsx
├── audit-findings-panel.tsx
├── audit-inlinks-panel.tsx
├── audit-outlinks-panel.tsx
├── audit-resources-panel.tsx
├── audit-structured-data-panel.tsx
├── audit-response-panel.tsx
├── audit-export-menu.tsx
├── audit-history-drawer.tsx
├── audit-query-state.ts
├── use-site-audit.ts
├── use-audit-pages.ts
├── use-audit-issues.ts
├── use-audit-details.ts
├── use-audit-events.ts
└── use-audit-actions.ts
frontend/lib/api/site-audits.ts
frontend/lib/api/site-audit-schemas.ts
frontend/src/api/query-keys.ts
```

Reuse generic button, dialog, tabs, badge, tooltip, resizable layout, error/loading and history primitives. Do not reuse extraction record selection, learning or result-summary components.

### 16.2 Configuration screen

Required controls:

- seed URL;
- scope: exact host, `www` equivalence, subdomains;
- include/exclude patterns;
- query parameter/tracking parameter policy;
- page/depth/time/byte budgets;
- global and per-origin concurrency;
- polite/fast/custom pacing profile;
- robots behavior;
- sitemap and HTML-link discovery toggles;
- external link/resource checking budgets;
- user-agent profile;
- optional deterministic/experimental rule groups;
- LLM analysis toggle and visible call/cost cap;
- retention settings if exposed to the user.

The UI must display effective limits before start. Unsafe or internally contradictory settings must be rejected server-side even if client validation passes.

### 16.3 Screaming Frog-inspired workspace

Use the supplied screenshot as an interaction model, not a visual clone.

#### Top control bar

- seed/domain;
- start/pause/resume/stop;
- state and completion reason;
- discovered, queued, fetching, analysed, skipped and failed;
- URLs per second and rolling response time;
- active/global/per-origin concurrency;
- elapsed time and budget usage;
- export, saved view and rerun.

#### Facet tabs

- Overview;
- Internal;
- External;
- Response Codes;
- URL;
- Page Titles;
- Meta Descriptions;
- H1;
- H2;
- Content;
- Images;
- Resources;
- Canonicals;
- Directives;
- Hreflang;
- Structured Data;
- AEO;
- AI Crawlers;
- Security;
- Response Times;
- Sitemaps.

A facet is a saved server query preset, not a copied client-side dataset.

#### Three synchronized regions

1. **URL grid**
   - server pagination/filter/sort;
   - row virtualization;
   - configurable/persisted columns;
   - selection without fetching all rows;
   - stable viewport during incremental refresh;
   - keyboard navigation and copy/export.

2. **Issue summary pane**
   - rule title and ID;
   - error/warning/opportunity;
   - priority;
   - affected pages, targets and occurrences;
   - explicit denominator and percentage;
   - deterministic/experimental badge;
   - selecting an issue filters the grid.

3. **Context details pane**
   - page metadata/status/timings;
   - findings, evidence and remediation;
   - inlinks/outlinks;
   - redirect chain and headers;
   - resources/images;
   - structured-data blocks;
   - discovery/frontier history;
   - source excerpt only when retained and authorized.

### 16.4 Grid technology

The repository currently has no virtualization/table dependency. Evaluate `@tanstack/react-table` plus `@tanstack/react-virtual` against bundle policy, or implement a narrowly scoped virtualized grid. Do not render thousands of rows into the DOM.

Server-side sorting/filtering is mandatory even with virtualization. Virtualization alone does not solve query or memory scale.

### 16.5 URL-addressable state

Persist these in query parameters:

- audit ID;
- facet;
- issue/rule ID;
- filters;
- sort;
- visible column preset;
- selected page ID;
- details tab.

Do not encode large row selections or complete filter objects without a bounded serialization format.

### 16.6 Live update behavior

- Events invalidate or patch aggregate/query caches in bounded batches.
- Do not prepend every page result into a large client array.
- The grid should refresh the current window/cursor without resetting sort, filters, selection or scroll.
- When an issue count changes, show a subtle delta without moving the selected row unexpectedly.
- Polling fallback uses a slower interval after the initial fast window.

### 16.7 Responsive behavior

Desktop retains the dense three-pane layout. At narrower widths, issue and details panes become drawers/tabs; the URL grid remains the primary surface. Keyboard/focus behavior, labels, loading/error/empty states and contrast are acceptance criteria, not a polish phase.

---

## 17. Progress and scoring semantics

### 17.1 Progress

A dynamic frontier cannot use only `processed / initial_total`.

Expose:

- URLs discovered;
- unique URLs accepted into frontier;
- queued;
- leased/fetching;
- fetched;
- analysed;
- skipped by scope/robots/trap;
- failed terminal/retryable;
- known frontier remaining;
- page/depth/time/byte budget consumed;
- frontier still expanding boolean;
- completion reason.

A percentage may be displayed only as “known work completed” and must be labeled unstable while discovery is active.

### 17.2 Scores

Raw issue counts are authoritative. If category scores are added:

- publish the formula, weights, applicability and denominator;
- exclude not-applicable and insufficient-evidence pages correctly;
- mark scores incomplete during an active/limited crawl;
- exclude experimental LLM findings by default;
- never mix prompt visibility metrics into technical readiness scores.

---

## 18. Performance and safety budgets

Phase 0 must freeze benchmark targets before implementation. Proposed starting gates:

### 18.1 Synthetic crawl sizes

- 100 pages: correctness and interactive development gate.
- 1,000 pages: default performance gate.
- 10,000 pages: production-scale gate for frontier, batching, memory and queries.
- 100,000 persisted pages: query/index benchmark without requiring one live crawl in CI.

### 18.2 Required measurements

- fetch throughput by response latency distribution;
- event-loop lag;
- peak worker RSS;
- number and duration of DB connections/transactions;
- frontier claim latency;
- page/link/resource write throughput;
- aggregate recomputation parity;
- API p50/p95 for URL list, issue list and page detail;
- WebSocket event volume;
- cancellation-to-terminal latency;
- resume correctness after forced process death.

### 18.3 Safety controls

- validate seed, redirects, sitemaps and discovered URLs;
- bound bodies before decoding and parsing;
- decompression-bomb ratio/size protection;
- XML entity-safe parser and sitemap recursion limits;
- no credentials forwarded across origins on redirect;
- strip fragments and reject unsupported schemes;
- cap headers, cookies, URLs, links and evidence sizes;
- per-origin concurrency/rate limiting;
- `Retry-After` and backoff;
- operator kill switch and feature flag;
- no HTML or secret headers in logs/events;
- retention/cleanup job for source artifacts.

---

## 19. Delivery plan

The slices below are ordered. Do not start the frontend against invented payloads; freeze contracts and fixture results first.

### Phase 0 — Decisions, fixtures and baselines

#### Slice 0.1: Freeze product semantics

Define HTTP-only evidence, scope, normalization, robots behavior, user agents, query policy, resource checking, budgets, progress counters, issue classes, denominators and deterministic/experimental semantics.

**Outputs:** architecture decision record, Pydantic settings contract, config schema, API examples.  
**Gate:** invalid/unsafe combinations fail schema tests.

#### Slice 0.2: Build an offline audit corpus

Create fixture sites for redirects, statuses, robots, sitemap indexes, duplicates, canonicals, hreflang, headings, metadata, structured data, client-rendered shells, query traps, resources and cross-host safety cases.

Encode the supplied Screaming Frog CSV cases as rule/evidence fixtures where licensing and data handling permit.

**Gate:** expected page/link/resource/finding counts are deterministic.

#### Slice 0.3: Benchmark existing primitives

Measure the shared HTTP client, HTML parser, Postgres pool and insert patterns at 8/20/50 concurrency. Verify that the proposed transport and parser do not route into browser/product logic.

**Gate:** written baseline with selected concurrency, queue and body limits.

### Phase 1 — Contracts, models and migration

#### Slice 1.1: Add configuration and contracts

Add `core/config/site_audit.py`, request/response contracts, stable enums and immutable settings serialization.

#### Slice 1.2: Add models and additive migration

Create run, frontier, page, redirect, link, resource, structured-data, finding, aggregate and event tables with indexes and constraints.

**Gate:** upgrade/downgrade and model metadata tests pass; baseline migration remains unchanged.

#### Slice 1.3: Run-kind dispatch contract

Add a site-audit task/dispatcher and make pause/resume/kill task-aware without breaking extraction runs.

**Gate:** existing crawl dispatch regression tests remain green.

### Phase 2 — HTTP acquisition, normalization and discovery

#### Slice 2.1: Audit HTTP fetcher

Implement bounded GET, redirect validation, timing/size capture, retry policy, user-agent profile and typed errors. No browser imports.

#### Slice 2.2: URL identity, scope and traps

Implement table-driven/property tests for URL equivalence and non-equivalence, IDNs, percent encoding, query repetition, path case and unsafe targets.

#### Slice 2.3: Robots and sitemap discovery

Expose robots sitemap directives; validate redirect hops; crawl nested sitemap indexes concurrently within budgets; stream/limit large XML rather than holding unbounded trees.

#### Slice 2.4: HTML link discovery

Extract same-scope links, resources, canonicals and hreflang observations from HTTP source HTML. Do not apply category/listing scoring.

### Phase 3 — Persistent frontier and high-concurrency runtime

#### Slice 3.1: Frontier CRUD and leases

Implement idempotent enqueue, short claims, stale lease recovery, priority and terminal states.

#### Slice 3.2: Coordinator and bounded queues

Implement global/per-origin fetch slots, pacing, backpressure, checkpoints, pause/kill and monotonic progress.

#### Slice 3.3: Batched writer

Persist pages/links/resources/findings in short transactions. Benchmark COPY/bulk insert versus SQLAlchemy multi-row insert before selecting an approach.

#### Slice 3.4: Failure and resume tests

Inject worker death during fetch, parse and write. Resume without duplicate pages/findings or lost queued URLs.

### Phase 4 — Snapshot and deterministic rule engine

#### Slice 4.1: Normalized page snapshot

Parse response directives, metadata, headings, source-visible text, links, resources, schema and hashes into a stable versioned contract.

#### Slice 4.2: Rule registry and lifecycle

Implement stable IDs, versions, applicability, denominators, evidence limits and idempotent finding replacement.

#### Slice 4.3: Page-level rules

Implement response, URL, metadata, headings, content, canonical, hreflang, resource, structured-data and security groups.

#### Slice 4.4: Graph/run-level rules

Implement broken/redirecting links, inlink/outlink candidates, depth/components, sitemap mismatches, duplicate clusters and cross-page entity consistency.

#### Slice 4.5: Incremental aggregation

Ensure incremental counts exactly equal a clean terminal recomputation.

### Phase 5 — API, events and exports

#### Slice 5.1: Run APIs

Create/list/detail/actions with ownership and unsafe-target tests.

#### Slice 5.2: Query APIs

Pages, issues, affected targets, details, links, resources and structured data with keyset pagination and allowlisted filters/sorts.

#### Slice 5.3: Event stream

Sequenced WebSocket plus polling fallback; bounded event payloads and reconnect tests.

#### Slice 5.4: Streaming exports

Pages, links, resources, findings and summary with filters and version fields.

### Phase 6 — Frontend workspace

#### Slice 6.1: Route, API client and query state

Add `/site-audit`, schemas, query keys, configuration form and deep-link state.

#### Slice 6.2: Control bar and live progress

Implement actions, counters, throughput, budgets and event reconnect/fallback.

#### Slice 6.3: Virtualized URL grid

Server filters/sorts/cursors, column presets, selection and stable live refresh.

#### Slice 6.4: Issue pane and synchronized filtering

Show affected pages/targets/occurrences and explicit denominators.

#### Slice 6.5: Details pane

Lazy-load page evidence, findings, links, resources, headers, redirects and schema.

#### Slice 6.6: Accessibility, responsive and E2E

Keyboard navigation, focus, drawers, errors/empty states, export and pause/resume/kill flows.

### Phase 7 — Deterministic AEO and AI crawler controls

#### Slice 7.1: AEO rules

Implement applicability-aware entity, answer structure, provenance, structured consistency and coverage checks.

#### Slice 7.2: AI crawler matrix

Version official user-agent profiles and distinguish search discovery, training and user-triggered retrieval.

#### Slice 7.3: AEO UI

Dimension summaries with evidence; no opaque single “AI score” as the primary view.

### Phase 8 — Optional LLM intelligence

#### Slice 8.1: Evaluation corpus

Human-review representative page types and establish false-positive/grounding thresholds.

#### Slice 8.2: Typed task registrations

Add prompt registry entries, payload validators, prompt files and budget settings.

#### Slice 8.3: Cluster sampling and execution

Analyse representative templates/outliers, not every page.

#### Slice 8.4: Experimental UI

Separate badge/filter/score behavior, evidence paths, confidence, cost and model versions.

### Phase 9 — Comparison and recurring audits

- rerun settings clone;
- URL/snapshot/finding diffs;
- rule-version-aware comparisons;
- scheduled audits and alerts;
- retention and trend charts;
- always-on audit mode only after resource usage is measured.

### Phase 10 — Separate AI Visibility and Agent Analytics epics

- prompt library and model/API benchmark;
- repeated observations/share of voice/citations/sentiment;
- provider/surface evidence labeling;
- edge/server log connector and verified AI bot analytics;
- no coupling to the site-audit frontier or readiness score.

---

## 20. Acceptance criteria

### Runtime

- A valid public seed starts an HTTP-only audit with an immutable settings snapshot.
- No Site Audit execution imports or starts the browser runtime.
- A configured global concurrency of 50 produces at most 50 page fetches in flight and obeys per-origin limits.
- Network waits do not hold fifty database sessions.
- The frontier expands from robots/sitemaps/HTML links and persists all decisions.
- Pause, resume, kill and forced worker death leave no permanently leased rows.
- Completion distinguishes exhausted frontier, user stop, failure and each budget limit.

### Correctness

- Every attempted page has one typed terminal outcome.
- Every fetched HTML page has one versioned snapshot.
- Link/resource occurrences aggregate to unique affected pages/targets without losing occurrence counts.
- Rule reruns are idempotent for the same versions.
- Incremental issue aggregates equal terminal recomputation.
- HTTP-only limitations are visible and no rendered-DOM claim is made.

### API/UI

- Pages/issues/details remain responsive at 10,000 pages and a persisted 100,000-page dataset benchmark.
- Selecting an issue filters affected URLs; selecting a URL loads evidence without disturbing filters/scroll.
- Live updates do not reset sort, selection or viewport.
- WebSocket reconnect resumes by sequence; polling fallback reaches the same terminal state.
- CSV/JSON exports stream and include rule/analyzer versions.
- URL query state restores facet, filters, sort, selected page and details tab.

### SEO/AEO/GEO integrity

- Deterministic and experimental findings are visually and computationally separate.
- AEO dimensions expose evidence and applicability.
- `llms.txt` absence is not a universal failure.
- AI crawler controls distinguish search, training and user-triggered agents.
- Prompt-based visibility output is never represented as crawl-derived readiness or consumer-surface ranking without matching evidence.

### Safety/regression

- Private-network targets, unsafe redirects, DNS rebinding cases, decompression bombs and XML/URL traps are blocked or bounded.
- Existing extraction crawl APIs, task execution and frontend routes remain unchanged in behavior.
- Focused backend, frontend, policy and E2E suites exit zero.

---

## 21. Test strategy

### Unit

- URL normalization/scope/traps;
- robots and sitemap parsing;
- redirect safety;
- HTTP response/body limits;
- snapshot parsing;
- every rule's applicability/evidence;
- aggregation and scores;
- event sequencing;
- LLM payload validation.

### Property/fuzz

- URL percent/query/IDN/path cases;
- malformed HTML/XML/JSON-LD;
- redirect graphs;
- decompression/body-size boundaries;
- include/exclude patterns;
- idempotent enqueue/finding fingerprints.

### Component

- API authorization and pagination;
- frontier claims/leases with PostgreSQL;
- pause/resume/kill;
- batch writer rollback/retry;
- export streaming;
- LLM disabled means zero provider calls.

### Load and chaos

- 100/1,000/10,000-page fixture sites;
- 8/20/50 fetch concurrency;
- slow responses, 429/Retry-After, connection resets;
- writer slowdown/backpressure;
- worker SIGTERM and database reconnect;
- event disconnect/replay;
- multi-run host contention.

### Frontend

- configuration validation;
- query-state restoration;
- server filter/sort requests;
- virtual row count rather than full DOM rendering;
- selection and scroll persistence during updates;
- stale detail request cancellation;
- keyboard/focus and responsive drawers;
- E2E start → live progress → issue filter → details → export → rerun.

### Suggested focused commands

```powershell
# Backend
cd backend
uv run pytest tests/unit/site_audit tests/component/test_site_audits_api.py -q
uv run ruff check app/site_audit app/api/site_audits.py app/models/site_audit.py app/schemas/site_audit.py
uv run mypy app/site_audit app/api/site_audits.py

# Frontend
cd frontend
pnpm check
pnpm test -- components/site-audit
pnpm check:policy
pnpm test:e2e -- --grep "site audit"
```

Add affected shared run/dispatcher regression tests to each slice. Do not use the full repository suite as the only feedback loop.

---

## 22. Files likely to change

### New backend files

- `backend/app/core/config/site_audit.py`
- `backend/app/models/site_audit.py`
- `backend/app/schemas/site_audit.py`
- `backend/app/api/site_audits.py`
- `backend/app/site_audit/**`
- `backend/alembic/versions/<next_revision>_site_audit.py`
- `backend/tests/unit/site_audit/**`
- `backend/tests/component/test_site_audits_api.py`
- `backend/tests/fixtures/site_audit/**`

### Existing backend files with narrow integrations

- `backend/app/models/__init__.py`
- `backend/app/main.py`
- `backend/app/core/celery_app.py`
- run dispatcher/control abstractions under `backend/app/workers/*` and `backend/app/crawl/service.py`
- LLM prompt registry/payload validation only when Phase 8 starts
- metrics and architecture documentation

### New frontend files

- `frontend/app/site-audit/page-view.tsx`
- `frontend/components/site-audit/**`
- `frontend/lib/api/site-audits.ts`
- `frontend/lib/api/site-audit-schemas.ts`
- focused component/MSW/E2E tests

### Existing frontend files with narrow integrations

- `frontend/src/app/route-registry.ts`
- `frontend/src/api/query-keys.ts`
- API export barrel if required
- navigation metadata and bundle budget configuration if a grid dependency is approved

---

## 23. Do not touch or overload

- `backend/app/extraction/*` and product/listing extraction semantics.
- Existing `CrawlRecord.data` as the audit datastore.
- Browser runtime as an audit fallback.
- Existing extraction run UI components as the new workspace.
- The current greenfield baseline migration.
- Unrelated pre-existing working-tree changes.
- Existing public extraction result contracts to expose audit fields.
- Search-engine/AI visibility claims unsupported by the captured evidence source.

---

## 24. Risks and required controls

| Risk | Required control |
|---|---|
| Fifty workers overload one site | Global and per-origin limits, pacing profiles, Retry-After, backoff and user-visible effective rate |
| Fifty workers exhaust DB pool | No session during network waits; one/small writer pool; batched short transactions |
| Infinite frontier | Persisted page/depth/time/bytes/pattern/query budgets and limit-reached outcome |
| SSRF/DNS rebinding | Validate every target/hop and implement rebinding-safe connection behavior |
| Memory growth | Bounded queues/body/evidence; streamed XML/exports; no full frontier/HTML collection |
| Misleading HTTP-only content findings | Source-evidence labels and rendering-gap rules |
| Occurrence counts confused with affected URLs | Separate page/target/occurrence metrics and explicit denominators |
| Rule churn breaks comparisons | Stable IDs, semantic versions, analyzer snapshot and version-aware diff |
| LLM cost/false positives | Default off, cluster sampling, budgets, typed outputs, corpus gate, evidence grounding |
| GEO claims exceed evidence | Separate module and API/frontend-versus-consumer-surface disclosure |
| AI bot UA spoofing | Server-log verification and clear confidence; no client-JS bot analytics claim |
| UI slows with live data | Server queries, keyset pagination, virtualization, delta events and stable view state |
| Existing extraction regressions | Dedicated context/task/routes plus shared-contract regression tests |

---

## 25. Product decisions to approve before coding

Recommended defaults are shown, but they must be approved and represented in the immutable settings snapshot.

| Decision | Recommended default |
|---|---|
| Acquisition | HTTP GET only |
| Global page concurrency | 50 after benchmark gate |
| Per-origin concurrency | 8 |
| Pacing | balanced 100–250 ms minimum start interval |
| Scope | exact host; explicit `www`/subdomain toggles |
| Robots | respect by default; persist disallowed observations |
| Sitemaps | robots directives plus conventional candidates |
| Unknown query parameters | preserve initially; remove configured tracking params |
| External link checking | off by default, capped when enabled |
| Resource body fetching | off; HEAD/ranged GET metadata under budget |
| Raw HTML retention | short TTL/off by default after normalized snapshot |
| Experimental LLM | off by default |
| LLM sampling | representative templates/outliers, not every page |
| Technical score | category-level transparent rubric; raw counts primary |
| GEO visibility | separate run type/module |
| `llms.txt` | informational observation only |

---

## 26. Supplied issue-report implications

The supplied Screaming Frog exports confirm the initial issue registry must support at least:

- missing/duplicate/short/long title and title-width estimates;
- uppercase/spaces/underscores/long URLs/query parameters;
- noindex directives;
- low-content, exact-duplicate and readability findings;
- missing/canonicalised canonical states;
- missing H1, missing/duplicate H2;
- oversized images, missing/empty alt and missing dimensions;
- no-response, 3xx and link-level failures;
- pages without outlinks and links without anchors;
- content-type and security-header findings;
- unsafe cross-origin target links.

More importantly, the report shapes prove that counts have different units. Examples observed in the supplied exports include an overview count of affected pages alongside a much larger raw set of link or image occurrences. The UI and API therefore need three distinct metrics:

1. affected source pages;
2. affected unique target URLs/resources;
3. total occurrences.

The inlink reports also require source, destination, status, anchor/alt, follow state, target, rel, path type, link path, position and origin evidence. This is why a page-only JSON result would be insufficient.

---

## 27. Final implementation recommendation

Approve Phases 0–7 as the Site Audit product. Treat Phase 8 as an experiment gated by a reviewed corpus. Treat prompt-based GEO visibility and server-log agent analytics as separate epics after the deterministic crawler and data model are stable.

The critical architecture choice is not simply “set concurrency to 50.” It is to introduce a persistent frontier and a bounded fetch → analysis → batched-write pipeline so fifty HTTP requests can be in flight without fifty database transactions, unbounded memory or extraction/browser coupling.
