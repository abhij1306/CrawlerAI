# CrawlerAI Final App Architecture Simplification and Hardening Plan — Revised After Capability Audit

**Audit source:** complete uploaded `backend(2).zip`, current artifacts under `backend/artifacts/runs/1`, and the previous `CrawlerAI_Final_App_Architecture_Simplification_and_Hardening_Plan.md`  
**Objective:** remove technical debt and duplicate ownership while retaining capabilities that demonstrably improve crawl coverage, resilience, debugging, enrichment, and product intelligence.  
**Architecture style:** production-ready modular monolith  
**Companion plan:** the revised extraction pipeline implementation plan remains the authority for extraction internals.

---

# 1. Audit conclusion

The previous plan correctly identified duplicated ownership and oversized orchestration, but it was too aggressive in several places.

The correct objective is not:

```text
delete every advanced capability
```

It is:

```text
retain useful capabilities
centralize their ownership
make execution bounded and observable
delete only duplicate, stale, no-op, or bypass paths
```

The most important correction applies to acquisition.

The latest run proves that advanced browser capabilities are useful:

- Real Chrome produced usable content after an Akamai-classified block.
- Patchright also recovered usable content for several sites.
- origin warmup established sessions on multiple protected sites;
- engine-specific cookie/state storage is implemented;
- host memory tracks Patchright and Real Chrome successes and blocks;
- challenge recovery, proxy handling, route blocking, and traversal are active production capabilities.

These should remain.

The technical debt is that acquisition policy is distributed across:

```text
fetch/
acquisition/
pipeline/retry/
field-based extraction retry modules
runtime settings
domain profile logic
host protection memory
```

The final architecture therefore preserves the capabilities while replacing overlapping orchestration with one finite acquisition plan.

---

# 2. Architectural principles

## 2.1 One owner per decision

| Decision | Sole owner |
|---|---|
| User-selected surface | API/UI request contract |
| Acquisition strategy plan | AcquisitionPlanner |
| Execution of one acquisition attempt | AttemptExecutor |
| Browser session lifecycle | BrowserSessionManager |
| Whether more artifacts are required | ExtractionResult.retry_request |
| Extracted facts and URL-level extraction verdict | ExtractionEngine |
| Public record shape | Typed record models |
| Persistence transaction | UrlResultRepository |
| Artifact file layout and retention | ArtifactRepository |
| Run-level aggregation | RunAggregator |
| Product match score | MatchScorer |
| Enrichment output | EnrichmentEngine |
| Observability interpretation | Read-only diagnostics over canonical results |

## 2.2 Preserve proven capabilities

A capability is retained when at least one applies:

- current artifacts demonstrate successful value;
- it protects security or reliability;
- it supports an explicit user feature;
- it has active production call sites;
- it has focused tests and a clear owner;
- replacing it would reduce coverage or operational control.

## 2.3 Retire code only with evidence

A module or path may be deleted only when:

```text
no active callers remain
and replacement coverage exists
and no unique capability is lost
and replay/integration tests prove equivalent or intentionally changed behavior
```

## 2.4 Typed boundaries

Cross-domain business boundaries use typed contracts.

Untyped dictionaries remain acceptable only for:

```text
decoded third-party JSON
database JSON serialization
artifact serialization
provider-specific payloads inside provider modules
```

## 2.5 No downstream semantic repair

Once `ExtractionResult` is produced, persistence, observability, product intelligence, and enrichment may consume it but may not reinterpret its facts or verdict.

---

# 3. Target modular-monolith structure

```text
app/
  api/
  core/
  crawl/
  acquisition/
  extraction/
  persistence/
  connectors/
  intelligence/
  enrichment/
  observability/
  workers/
```

Recommended top-level flow:

```text
API/UI
  -> RunCoordinator
      -> UrlProcessor
          -> AcquisitionPlanner
          -> AttemptExecutor
          -> ExtractionEngine
          -> optional capability escalation
          -> UrlResultRepository
          -> ArtifactRepository
      -> RunAggregator
  -> API/UI
```

This does not require each component to be a single file. It requires one public owner and one contract for each responsibility.

---

# 4. Capability disposition summary

## 4.1 Keep and harden

```text
curl-cffi HTTP acquisition
httpx for APIs/connectors/internal requests
Patchright
Real Chrome escalation
proxy support and proxy session handling
origin warmup
engine-specific cookie/storage-state reuse
host protection memory
challenge classification and bounded recovery
resource/route blocking
browser pooling
listing traversal: scroll/load more/view all/pagination
internal API/network payload capture
RunTrace
browser artifact shaping
run audit
baseline drift detection
optional LLM diagnosis
SerpAPI product search
Google-native search capability
deterministic product matching
human match review
Shopify taxonomy/catalog enrichment
deterministic enrichment
optional LLM enrichment
Celery execution
PostgreSQL/SQLAlchemy persistence
local artifact storage abstraction
```

## 4.2 Consolidate or redesign

```text
fetch + acquisition + pipeline retry orchestration
browser engine-selection rules
browser interaction/humanization policy
field-based retry rules
pipeline mutable contexts
record persistence shaping
normalization/coercion layers
config ownership
product-intelligence service orchestration
observability data sources
selector/domain recipe ownership
```

## 4.3 Retire when migration gates pass

```text
no-op adapter registry and no-op adapter calls
adapter compatibility records
duplicate verdict recomputation
legacy CandidateSet/field-repair trace fields
semantic public-record firewall
legacy extraction retry modules
surface inference
unused generated extraction config exports
stale tests tied to removed internals
compatibility facades with no external consumers
```

---

# 5. Acquisition architecture — corrected design

## 5.1 What must be preserved

The acquisition layer should continue supporting:

```text
HTTP-first acquisition
browser-first user/profile mode
Patchright
Real Chrome
direct and proxy attempts
engine-specific cookie/state memory
origin warmup
challenge wait and recovery
interstitial handling
bounded interaction activity
network/API payload capture
listing traversal
host protection/capability memory
resource blocking
browser pool reuse
explicit browser-only and HTTP-only modes
```

Real Chrome is not a temporary compatibility path. It is a valid acquisition strategy for sites where Chromium/Patchright is blocked or behaves differently.

## 5.2 Actual debt

Current policy and execution are split across:

```text
app/services/fetch/fetch_context.py
app/services/fetch/browser_policy.py
app/services/acquisition/acquirer.py
app/services/acquisition/browser_runtime.py
app/services/acquisition/browser_page_flow.py
app/services/acquisition/browser_detail.py
app/services/acquisition/browser_recovery.py
app/services/pipeline/retry/stage.py
app/services/pipeline/extraction_retry_decision.py
app/services/pipeline/listing_escalation_decision.py
```

This creates several risks:

- multiple modules can initiate a browser attempt;
- requested fields can trigger browser use before extraction explains why;
- attempt budgets are difficult to understand;
- the same block state is classified multiple times;
- browser fallback can be automatic but not represented as a first-class transition;
- warmup, challenge waiting, interactions, and traversal consume independent timing budgets;
- policy and execution are coupled to global runtime settings.

## 5.3 Target acquisition contracts

```python
class AcquisitionRequest:
    run_id: int
    url: str
    surface: Surface
    mode: AcquisitionMode
    requested_artifacts: ArtifactRequirements
    domain_profile: DomainAcquisitionProfile
    deadline: datetime
    proxies: tuple[ProxySpec, ...]
```

```python
class AttemptSpec:
    attempt_id: str
    transport: Literal["curl", "httpx", "patchright", "real_chrome"]
    proxy: ProxySpec | None
    warmup: WarmupPolicy
    interaction: InteractionPolicy
    traversal: TraversalPolicy | None
    capture: ArtifactRequirements
    timeout_seconds: float
    reason: str
```

```python
class AcquisitionPlan:
    attempts: tuple[AttemptSpec, ...]
    total_deadline: datetime
    policy_version: str
```

```python
class AcquisitionResult:
    attempts: tuple[AttemptResult, ...]
    selected_attempt_id: str | None
    capture_bundle: CaptureBundle
    outcome: AcquisitionOutcome
```

## 5.4 AcquisitionPlanner

`AcquisitionPlanner` creates a finite ordered plan using:

```text
explicit user mode
surface requirements
domain acquisition profile
host capability memory
available proxies
available browser engines
prior attempt outcomes
ExtractionResult.retry_request
remaining deadline
```

It does not execute attempts.

## 5.5 AttemptExecutor

Executes exactly one `AttemptSpec`.

It owns:

```text
transport call
browser/session setup
warmup
interactions
navigation
challenge recovery
traversal
artifact capture
attempt diagnostics
```

It does not decide the next attempt.

## 5.6 Real Chrome policy

Keep Real Chrome escalation when:

```text
Patchright was blocked or failed with an engine-specific navigation error
host memory records Real Chrome success
host memory records durable Patchright blocking
a vendor-block classification indicates an engine escalation lane
the user/domain profile explicitly selects Real Chrome
the browser strategy requires a genuine installed Chrome profile
```

The planner may choose Real Chrome first for a host with reliable historical evidence.

Every engine transition must record:

```text
source attempt
target engine
reason
host policy snapshot
remaining budget
proxy
outcome
```

## 5.7 Origin warmup policy

Keep origin warmup, but make it conditional.

Run warmup when:

```text
domain profile requires session establishment
host history shows direct deep links fail but origin-first succeeds
challenge/vendor classification recommends warmup
no reusable engine-compatible storage state exists
```

Skip warmup when:

```text
valid reusable storage state is loaded
the same engine/proxy/origin has recently warmed successfully
the proxy rotates per request and warmup state cannot be reused
remaining deadline is insufficient
the user selected a strict fast/no-warmup profile
```

Warmup remains:

```text
best effort
non-fatal
maximum once per compatible session/proxy/origin window
fully traced
bounded by a fraction of the URL deadline
```

## 5.8 Interaction and humanization policy

Do not delete interaction recovery.

Replace generic always-on randomness with named bounded profiles:

```text
none
light_humanization
challenge_recovery
lazy_content
listing_traversal
form_interaction
```

Prefer purposeful actions:

```text
dismiss consent
scroll a required root into view
bounded lazy-load scrolling
click load-more
expand configured sections
wait for a specific network/DOM condition
```

Random pointer movement and scroll jitter may remain inside `light_humanization` or `challenge_recovery`, but:

```text
must be bounded
must have a recorded random seed or action summary
must have a strict time cap
must not run for every browser page
```

## 5.9 Challenge recovery

Keep:

```text
challenge classification
bounded polling for challenge clearance
one permitted reload/re-navigation where policy allows
bounded activity intended to allow provider scripts to complete
engine/proxy escalation
challenge-state cookie rejection
```

Do not implement unbounded challenge loops.

Do not classify a semantically invalid product/job page as valid merely because the challenge cleared. Acquisition owns block clearance; extraction owns content correctness.

## 5.10 Automatic fallback

Automatic browser fallback remains valid.

The rule is:

```text
automatic is allowed
silent is not
```

Every fallback must be represented in:

```text
AcquisitionPlan
AttemptResult
RunTrace
artifact manifest
metrics
```

## 5.11 Field-based retries

Do not remove the capability to acquire richer artifacts for variants, prices, listings, or job details.

Change the owner.

Extraction returns a typed request such as:

```python
class RetryRequest:
    required_capabilities: frozenset[
        Literal[
            "rendered_dom",
            "network_payloads",
            "real_chrome",
            "interaction",
            "listing_traversal",
        ]
    ]
    reason: str
    finding_ids: tuple[str, ...]
```

The planner translates capabilities into the next valid attempt.

Avoid direct rules such as:

```text
price missing -> browser
image missing -> browser
any requested detail field -> browser
```

## 5.12 Attempt budget

Do not hard-code one browser attempt for all sites.

Use:

```text
one global URL deadline
a configurable maximum number of attempts
no identical engine/proxy/profile attempt repeated
a maximum per capability lane
early stop after a successful extraction result
```

Recommended default automatic ladder:

```text
HTTP
-> Patchright if required
-> Real Chrome if Patchright is blocked/engine-incompatible
```

Proxy alternatives may be included when explicitly configured, within the same deadline and attempt cap.

## 5.13 Acquisition modules: keep, consolidate, retire

### Keep as capabilities

```text
browser_pool*
browser_storage_state.py
cookie_store.py
host_protection_memory.py
browser_proxy_config.py
browser_proxy_bridge.py
browser_route_blocking.py
rate_limiter.py
pacing.py
internal_api_replay.py
traversal*
browser_interstitial.py
browser_recovery.py
browser_capture.py
browser_diagnostics.py
```

These may be refactored but should not be deleted without capability-specific replacement tests.

### Consolidate orchestration

Merge responsibilities from:

```text
fetch/fetch_context.py
fetch/browser_policy.py
acquisition/acquirer.py
browser_stage_runner.py
browser_page_flow.py
browser_detail.py
browser_result_builder.py
pipeline/retry/stage.py
```

into clear planner/executor/session-runner boundaries.

### Retire after consolidation

```text
requested_detail_fields_require_browser()
legacy extraction_retry_decision.py
legacy listing_escalation_decision.py
duplicate browser initiation paths
untraced fallback branches
```

---

# 6. Crawl and pipeline architecture

## 6.1 Preserve useful crawl capabilities

Keep:

```text
single URL runs
bulk/CSV runs
sitemap discovery
category/listing traversal
pause/cancel
progress events
batch execution
per-run concurrency
run access control
domain profiles
```

Do not reduce the crawl domain to two giant files.

## 6.2 Remove duplicated state ownership

Create explicit public owners:

### RunCoordinator

Owns:

```text
run lifecycle
URL work creation
concurrency
pause/cancel
progress aggregation
final run status
```

### UrlProcessor

Owns one URL workflow:

```text
load request
plan acquisition
execute attempt
extract
request next capability if justified
persist
return UrlResult
```

### SitemapService

Continues to own sitemap parsing and URL discovery.

### TraversalService

Continues to own listing traversal mechanics, while acquisition executes traversal attempts.

## 6.3 Celery

Keep Celery.

Recommended task granularity:

```python
process_url(run_id: int, url_id: int) -> UrlResultReference
```

Use a run finalizer or chord/group completion mechanism where appropriate, but preserve current operational reliability if a simpler existing task model is already stable.

## 6.4 Idempotency

Use database-enforced uniqueness where possible:

```text
run_id
normalized URL
surface
processing generation
```

Attempt-level artifacts use:

```text
URL result ID
attempt ID
```

Do not include `attempt` in the record identity if multiple attempts belong to one final URL result.

---

# 7. Extraction and normalization boundary

The companion extraction plan remains authoritative.

System-wide rules:

```text
ExtractionEngine consumes CaptureBundle
ExtractionEngine returns canonical ExtractionResult
normalization occurs at evidence admission
typed materialization occurs once
persistence does not repair records
observability does not recompute verdicts
```

## 7.1 Keep useful normalization primitives

Keep or relocate pure functions for:

```text
text cleanup
URL resolution/canonicalization
money parsing
currency normalization
availability normalization
identifier normalization
job date normalization
safe HTML-to-text conversion where required
```

## 7.2 Retire duplicate semantic layers

After extraction migration, remove:

```text
generic coerce_field_value dispatch
legacy normalizers operating on public records
field winner/source-priority repair
public_record_firewall semantic rewriting
post-extraction field repair
publish-time value correction
```

Do not remove primitives merely because they currently live in a legacy module. Move them first and prove callers.

---

# 8. Persistence and artifact architecture — corrected design

## 8.1 Preserve existing useful foundations

Keep:

```text
ArtifactStorage protocol
LocalArtifactStorage implementation
artifact_store facade if it remains a thin stable boundary
PostgreSQL/SQLAlchemy models
CrawlRecord during migration
record content fingerprints
URL identity keys
browser artifact shaping
artifact readers
```

The current storage abstraction is useful and should be hardened rather than replaced wholesale.

## 8.2 Immediate persistence correction

Persistence must accept the canonical `UrlResult`/`ExtractionResult` and store it without semantic modification.

Remove from persistence:

```text
public_record_data_for_surface semantic filtering
field coercion
variant repair
verdict recomputation
legacy source-trace construction from internal record dictionaries
```

## 8.3 Artifact manifest

Add a versioned manifest:

```python
class ArtifactManifest:
    schema_version: str
    run_id: int
    url_result_id: int
    bundle_id: str
    attempts: tuple[AttemptArtifactSet, ...]
    extraction_artifacts: ExtractionArtifactSet
    redaction_policy_version: str
```

## 8.4 Atomic local writes

Harden the existing local backend:

```text
write to temporary file
flush/fsync where practical
atomic rename
write manifest last
never expose partial JSON/replay packages
```

## 8.5 Hashes and content addressing

Add SHA-256 to every stored artifact for integrity and replay verification.

Do not require a global content-addressed blob store immediately.

Adopt global deduplication only after measuring:

```text
artifact volume
duplicate rate
retention cost
multi-node storage requirements
```

The local run/page layout is acceptable for the first production deployment if writes are atomic and manifests are authoritative.

## 8.6 Database migration

Do not force a disruptive new `crawl_url_results` table before extraction stabilizes.

Use a staged migration:

1. add canonical verdict, extraction version, bundle ID, and manifest URI to the current URL/record ownership model;
2. dual-read during API migration;
3. create a dedicated URL result table only if the current schema cannot represent one URL with multiple typed records cleanly;
4. remove duplicated `raw_data`, `discovered_data`, and `source_trace` only after API and review consumers move to canonical artifacts.

---

# 9. Adapter and connector architecture

## 9.1 Current audit

The adapter registry currently returns no adapters and all adapter operations are no-ops.

The pipeline still calls those no-op boundaries.

That is technical debt.

## 9.2 Immediate action

Remove:

```text
no-op adapter registry calls
adapter recovery calls that can never return a provider
legacy AdapterResult.records compatibility behavior
tests that only preserve the empty facade
```

## 9.3 Preserve the connector concept

Do not ban platform connectors.

Create a connector interface when the first concrete provider is added:

```python
class Connector(Protocol):
    name: str

    async def supports(self, request: ConnectorRequest) -> bool:
        ...

    async def acquire_artifacts(
        self,
        request: ConnectorRequest,
    ) -> tuple[ArtifactRef, ...]:
        ...
```

Connectors may:

```text
call documented/public platform APIs
capture structured JSON
normalize transport metadata
reuse acquisition HTTP/proxy/rate-limit infrastructure
```

They may not:

```text
return final public records
choose extraction winners
change surface
set URL verdicts
```

Potentially valuable future connector families include:

```text
Shopify
Workday
Greenhouse
iCIMS
Oracle HCM
ADP
Jibe
Bullhorn
Algolia-backed catalogs/job boards
```

Each connector requires a replay fixture showing unique value.

---

# 10. Configuration architecture — corrected design

## 10.1 Preserve useful configuration

Keep configuration for:

```text
security and block signatures
browser fingerprint/profile selection
network capture
proxy behavior
timeouts and budgets
sitemap limits
artifact retention
observability thresholds
product-intelligence providers/scoring thresholds
enrichment taxonomy paths and limits
LLM providers and budgets
user/domain acquisition profiles
```

## 10.2 Separate three kinds of configuration

### Operational settings

Environment-driven:

```text
timeouts
concurrency
credentials
endpoints
feature enablement
storage paths
resource limits
```

### Versioned policy

Code-owned and tested:

```text
acquisition attempt policy
quality thresholds
match-scoring weights
baseline acceptance policy
```

### Declarative recipes/data

Versioned data:

```text
CSS extraction recipes
taxonomy repositories
brand aliases
provider mappings
block signatures
```

## 10.3 Remove duplicate/stale ownership

Retire only after import and behavior analysis:

```text
unused extraction_rules modules
wildcard export aggregators
duplicated Python + generated JSON exports
variant migration tables no longer used
adapter settings without adapters
field mapping tables replaced by typed surface schemas
```

Do not reduce configuration to an arbitrary line count at the expense of clarity.

## 10.4 Runtime settings

Split the broad runtime settings hub by domain, but retain one application-level composition object:

```text
settings.acquisition
settings.extraction
settings.storage
settings.workers
settings.observability
settings.intelligence
settings.enrichment
```

This avoids global imports while preserving centralized environment loading.

---

# 11. Observability architecture — corrected design

## 11.1 Preserve current useful capabilities

Keep:

```text
RunTrace
browser artifact shaping
artifact_reader
run_audit
baseline drift detection
optional LLM diagnosis
Prometheus metrics
Logfire/structured logging
```

The current observability package documents these as read-only. That is the correct invariant.

## 11.2 Correct the data source

All observability must consume canonical:

```text
AttemptResult
AcquisitionResult
ExtractionResult
UrlResult
RunSummary
```

Remove legacy fields derived from:

```text
CandidateSet
completed extraction tiers from the old pipeline
field repair structures
ad hoc public record inspection
```

## 11.3 RunTrace

Retain RunTrace as the per-URL causal timeline.

Recommended events:

```text
plan_created
attempt_started
warmup_started/completed
navigation_completed
challenge_detected/cleared
interaction_executed
artifacts_captured
extraction_started/completed
retry_requested
record_persisted
url_completed
```

Extraction summary comes directly from `ExtractionResult.metrics`.

## 11.4 Browser artifact shaping

Keep browser artifact shaping.

It provides useful:

```text
redaction
noise removal
honest naming
compact persisted diagnostics
derivable-field reconstruction
```

It must not alter in-memory runtime decisions.

## 11.5 Run audit

Keep run audit as a read-only diagnostics layer.

It may:

```text
flag contradictions
identify missing artifacts
compare persisted and canonical verdicts
flag latency budget breaches
link symptoms to architecture owners
```

It may not:

```text
change a verdict
repair a record
modify a domain profile automatically
write selector recipes
```

## 11.6 Baseline drift

Keep baseline monitoring, with hardening:

```text
version baselines by surface and engine/extraction version
learn only from accepted successful runs
require minimum samples
exclude manually flagged anomalous runs
use robust timing statistics
never mutate run status
```

## 11.7 LLM diagnosis

Keep as:

```text
user-triggered
or automatically invoked only for flagged/failed runs
```

It consumes saved artifacts and produces diagnostics with citations to artifact fields.

It is not part of the success path.

## 11.8 Telemetry

Add/retain metrics for:

```text
attempt count by engine
Real Chrome escalation rate and success rate
warmup execution, skip reason, duration, and benefit
challenge recovery success
proxy success by lane
acquisition deadline exhaustion
extraction verdict counts
variant completeness
lineage coverage
persistence failures
replay determinism
product-intelligence provider/match quality
```

---

# 12. Product intelligence architecture — corrected design

## 12.1 Preserve valuable current capabilities

Keep:

```text
SerpAPI search
Google-native search
query generation
candidate URL normalization/deduplication
brand registry
private-label handling
deterministic matching
candidate crawl creation
human review
optional LLM enrichment/reranking
job persistence and refresh
```

The debt is that provider calls, provider HTML parsing, candidate filtering, candidate extraction orchestration, scoring, LLM work, and job persistence are concentrated in two very large modules.

## 12.2 Target components

```text
intelligence/
  contracts.py
  service.py
  providers/
    base.py
    serpapi.py
    google_native.py
  query_builder.py
  candidate_policy.py
  match_features.py
  match_scorer.py
  repository.py
  llm_reranker.py
```

## 12.3 SearchProvider

Providers may parse their own search-result pages or API responses.

This is valid provider behavior.

Rules:

```text
provider-specific HTML parsing stays inside the provider module
prefer Selectolax for HTML parsing
provider parsing produces SearchCandidate objects only
provider code does not extract product detail records
```

The earlier rule “product intelligence contains no HTML parser” was too broad.

The corrected rule is:

```text
product-detail pages always use normal AcquisitionEngine + ExtractionEngine
search-provider result pages may be parsed inside provider adapters
```

## 12.4 Candidate acquisition

Candidate product URLs use:

```text
normal AcquisitionEngine
surface = ecommerce_detail
normal ExtractionEngine
```

Do not create a second product scraper.

## 12.5 Matching

Preserve existing useful matching features:

```text
GTIN match
manufacturer/style-code match
brand compatibility
title similarity
distinctive model tokens
variant specification mismatch
price band
source/domain policy
private-label policy
```

Refactor the score into a typed feature breakdown.

Exact identifier conflicts cannot be overridden by an LLM.

## 12.6 LLM role

LLM may:

```text
rerank ambiguous top candidates
fill explicitly enrichment-only explanatory fields
summarize match rationale
```

LLM may not:

```text
invent source identifiers
override exact conflicts
bypass deterministic extraction
directly write final match status without policy validation
```

---

# 13. Data enrichment architecture — corrected design

## 13.1 Preserve valuable capabilities

Keep:

```text
Shopify taxonomy/category repository
attribute repository
deterministic category matching
material normalization
size-system detection
audience and SEO keyword generation
discovery tags
optional LLM enrichment
enrichment job lifecycle
```

These are product features, not extraction debt.

## 13.2 Refactor boundaries

```text
enrichment/
  contracts.py
  engine.py
  deterministic/
  taxonomy/
  providers/
  llm.py
  repository.py
  service.py
```

## 13.3 Rules

- enrichment consumes persisted typed records;
- enrichment never changes extraction verdict or provenance;
- deterministic output and LLM output remain separately attributed;
- taxonomy and attribute data are versioned;
- provider integrations are isolated;
- large deterministic functions are split by feature, not deleted.

---

# 14. LLM and LangGraph position

## 14.1 LLM

Retain LLM capabilities at explicit boundaries:

```text
product-intelligence reranking
data enrichment
flagged-run diagnosis
human-reviewed recipe suggestions
evidence adjudication after deterministic abstention
```

Do not use LLM for:

```text
normal field extraction
surface selection
browser engine selection
price/identifier/variant invention
verdict recomputation
```

## 14.2 LangGraph

LangGraph remains unnecessary for the normal crawl path.

It may be considered later for workflows that genuinely need:

```text
long-lived human review
pause/resume approval
multi-stage offline recipe evaluation
evidence adjudication with explicit interrupts
```

Do not use it to replace the finite AcquisitionPlanner or UrlProcessor state machines.

---

# 15. Persistence, API, and model hardening

## 15.1 Shared enums

Use exact shared enums for:

```text
Surface
UrlVerdict
RunStatus
UrlStatus
AcquisitionOutcome
BrowserEngine
AttemptOutcome
ArtifactType
```

## 15.2 Versioned contracts

Version:

```text
AcquisitionPlan
CaptureBundle
ExtractionResult
UrlResult
ArtifactManifest
ProductSnapshot
MatchResult
EnrichmentResult
```

## 15.3 Error model

Use typed errors with stable API mappings:

```text
InvalidRequest
UnsafeUrl
AcquisitionBlocked
AcquisitionTimeout
AcquisitionExhausted
ExtractionInvalid
WrongSurface
PersistenceConflict
ProviderUnavailable
```

## 15.4 Security capabilities to retain

```text
SSRF protection
redirect revalidation
private-network blocking
safe headers and cookies
challenge-state cookie filtering
secret redaction
artifact authorization
provider credential isolation
response/artifact size limits
safe filesystem paths
rate limiting
```

---

# 16. Revised implementation program

## Phase 1 — Canonical results and verdict ownership

1. Complete the revised extraction plan.
2. Introduce canonical `UrlResult`.
3. Make `ExtractionResult.verdict` the only URL extraction verdict.
4. Remove persistence and publish verdict recomputation.
5. Rebase RunTrace and run audit on canonical results.

**Gate:** replay, DB, trace, and API agree on the verdict and record count.

---

## Phase 2 — Acquisition planner without capability loss

1. Inventory every current acquisition capability and its tests.
2. Introduce `AcquisitionPlan` and `AttemptSpec`.
3. Move engine/proxy/warmup/interaction selection into `AcquisitionPlanner`.
4. Move attempt mechanics into `AttemptExecutor`.
5. Preserve Patchright, Real Chrome, warmup, challenge recovery, cookie reuse, proxies, and traversal.
6. Replace duplicate pipeline retry modules with typed extraction capability requests.
7. Record every transition.

**Gate:** current protected-site replay/live tests retain or improve success rates, including Real Chrome recovery.

---

## Phase 3 — Pipeline and crawl state ownership

1. Introduce `UrlProcessor`.
2. Make RunCoordinator the sole run-state owner.
3. Preserve sitemap, batch, category discovery, pause/cancel, and progress services.
4. Remove mutable semantic post-processing.
5. add database-backed idempotency.

**Gate:** worker restart or duplicate delivery does not duplicate records or lose final state.

---

## Phase 4 — Persistence and artifact hardening

1. Add canonical artifact manifest.
2. add hashes and atomic local writes.
3. persist all attempts and extraction replay.
4. remove semantic persistence shaping.
5. migrate API/review consumers away from duplicated raw/discovered/trace fields.
6. evaluate content-addressed global storage only after measurement.

**Gate:** every URL is replayable from its manifest, and interrupted writes are not visible.

---

## Phase 5 — Normalization and configuration ownership

1. Move pure primitives to `core/`.
2. delete generic record coercion after callers migrate.
3. split runtime settings by domain.
4. classify config as operational, policy, or data.
5. delete only orphaned or duplicated extraction-rule exports.

**Gate:** each business decision has one code owner and no duplicate config representation.

---

## Phase 6 — Observability consolidation

1. preserve RunTrace, browser artifact shaping, run audit, baseline, and LLM diagnosis;
2. change all inputs to canonical result contracts;
3. version drift baselines;
4. invoke LLM diagnosis only on demand or flagged runs;
5. add acquisition capability metrics.

**Gate:** observability is read-only and can explain every acquisition transition.

---

## Phase 7 — Product intelligence refactor

1. split search providers;
2. retain SerpAPI and Google-native capabilities;
3. isolate provider result parsing;
4. reuse normal acquisition/extraction for candidates;
5. extract deterministic match features and scorer;
6. keep human review and optional LLM reranking;
7. thin job service and repository.

**Gate:** no independent product-detail scraper exists inside product intelligence.

---

## Phase 8 — Enrichment refactor

1. introduce typed input/output contracts;
2. split taxonomy, materials, sizing, SEO, and audience deterministic components;
3. preserve Shopify taxonomy and attribute repositories;
4. isolate optional LLM and provider enrichers;
5. retain lineage/versioning.

**Gate:** enrichment cannot change extraction facts or verdicts.

---

## Phase 9 — Evidence-based retirement

For each candidate module:

1. list active callers;
2. identify unique capability;
3. map replacement;
4. add focused/replay tests;
5. remove call sites;
6. delete module;
7. run architecture and live capability gates.

Prioritize deletion of:

```text
no-op adapters
duplicate retry decision modules
duplicate verdict owners
legacy semantic persistence shaping
legacy field repair/coercion
stale extraction config exports
stale implementation-coupled tests
```

Do not delete a capability module merely to hit a line-count target.

---

# 17. Quantitative guardrails

LOC should be used as a debt indicator, not as the sole acceptance criterion.

Recommended goals:

```text
reduce acquisition orchestration LOC by at least 35%
reduce pipeline/crawl duplicated orchestration LOC by at least 30%
reduce stale extraction/config code by at least 50%
reduce files over 700 LOC by splitting responsibilities
eliminate functions over 100 LOC unless explicitly justified
```

Exceptions may be allowed for:

```text
static taxonomy/provider data
pure parsers with strong focused tests
generated migrations
```

Every reduction must preserve or improve:

```text
site success rate
block recovery rate
variant completeness
job/listing coverage
replay determinism
latency budgets
debuggability
```

---

# 18. Production hardening gates

## Acquisition

```text
Real Chrome recovery remains tested
origin warmup has measured benefit/skip metrics
challenge loops are bounded
attempt transitions are complete and traceable
no duplicate engine/proxy attempt
global deadline enforced
```

## Extraction

```text
one canonical engine contract
all public fields have lineage
variants/offers/assets remain entity-scoped
one verdict owner
deterministic replay
```

## Persistence

```text
atomic artifact writes
manifest integrity hashes
transactional URL result persistence
idempotent retries
no semantic record mutation
```

## Observability

```text
read-only diagnostics
canonical result source
versioned baselines
no verdict mutation
on-demand LLM diagnosis
```

## Intelligence and enrichment

```text
normal extraction reused
deterministic feature breakdowns
LLM boundaries enforced
human review preserved
provider failures isolated
```

## Security

```text
SSRF and redirect checks
private-network blocking
cookie/header redaction
artifact access control
provider secret isolation
rate and size limits
```

---

# 19. Architecture enforcement tests

CI should fail if:

```text
a second URL verdict owner is added
persistence imports semantic field normalization
observability mutates records or verdicts
product intelligence adds a separate product-detail extractor
an adapter/connector returns public records
acquisition calls materialization
extraction starts network acquisition
surface inference returns
browser fallback occurs without an AttemptResult
the same attempt specification can repeat without policy authorization
a warmup/challenge/interaction loop has no explicit deadline
a public record loses lineage
```

CI should also verify that these useful capabilities remain:

```text
Patchright attempt support
Real Chrome attempt support
host capability memory
engine-specific storage state
origin warmup policy
challenge recovery
proxy attempts
listing traversal
RunTrace
baseline drift
SerpAPI/Google-native provider contracts
Shopify taxonomy enrichment
```

---

# 20. Final implementation directive

> Use this revised plan as the app-wide architecture contract. Remove duplicate ownership and stale compatibility paths, but preserve useful acquisition, browser, observability, product-intelligence, and enrichment capabilities. Centralize HTTP, Patchright, Real Chrome, proxy, warmup, interaction, challenge recovery, and traversal policy in a finite AcquisitionPlanner and execute each strategy through a typed AttemptExecutor. Keep automatic escalation, but make every transition bounded and observable. Make ExtractionResult and UrlResult canonical so persistence, publish, and observability cannot reinterpret them. Harden the existing storage abstraction with manifests, hashes, and atomic writes before considering global content-addressed storage. Remove the current no-op adapter path while preserving a future artifact-only connector contract. Retain RunTrace, browser artifact shaping, run audit, drift baselines, provider search, deterministic matching, Shopify taxonomy, and optional LLM features behind explicit boundaries. Delete code only after caller, capability, replacement, and regression evidence proves it is technical debt rather than useful functionality.
