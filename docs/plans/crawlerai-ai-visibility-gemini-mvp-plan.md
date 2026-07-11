# CrawlerAI AI Visibility — Gemini Grounded Search MVP Plan

**Status:** Standalone implementation plan  
**Target:** A testable MVP using the existing Gemini API key  
**Primary surface:** `/ai-visibility`  
**Primary API:** `/api/ai-visibility`  
**Initial provider:** Gemini Developer API with Google Search grounding  
**Default model:** `gemini-2.5-flash`  

---

## 1. Objective

Build a small, reliable AI-visibility benchmark inside CrawlerAI that can run independent, non-branded buyer-intent prompts through Gemini with Google Search grounding and explain the complete observable path:

```text
Prompt
  → generated Google Search queries
  → grounded answer
  → explicit URL citations
  → deterministic brand/domain scoring
  → provider-level benchmark report
```

The MVP must solve the immediate Best&Less audit problem:

- remove account memory and previous-chat contamination;
- execute every prompt as an independent request;
- capture Gemini's generated search-query fanout;
- preserve the answer and explicit citation evidence;
- measure Best&Less and competitor visibility without telling Gemini which brands are being measured;
- repeat prompts so normal answer volatility is visible;
- export evidence that can be used in the Monday presentation.

This is a separate bounded context. It does not depend on, modify, or wait for any other CrawlerAI feature plan.

---

## 2. MVP scope

### Included

1. One benchmark project with:
   - brand name and aliases;
   - owned domains and unintended related domains;
   - competitors, aliases and owned domains;
   - country/language configuration;
   - reusable prompt panel.
2. Gemini grounded-search provider adapter.
3. One fresh stateless Gemini interaction per prompt and repetition.
4. Randomized execution order with a persisted seed.
5. First-class storage of generated search queries.
6. First-class storage of explicit citation annotations.
7. Deterministic mention, citation, domain and fanout scoring.
8. Durable background execution through Celery.
9. Live polling UI.
10. CSV and Markdown exports.
11. Environment-based Gemini credential for the first release.
12. Provider abstraction that allows OpenAI and Anthropic adapters later without schema or UI redesign.

### Explicitly excluded from the MVP

- OpenAI and Anthropic execution adapters.
- Consumer-interface automation or scraping.
- Scheduled monthly monitoring.
- Historical trend charts across months.
- LLM-based sentiment or semantic citation grading.
- Fetching and auditing cited pages.
- Automatic prompt generation.
- A single composite “AEO score.”
- Claims about all sources Gemini considered internally.
- Any claim that the Gemini API is identical to the Gemini consumer application or Google AI Overviews.

---

## 3. Correct product terminology

The UI and exports must label the initial surface as:

> **Gemini grounded API — Google Search**

Do not label it:

- Gemini consumer visibility;
- Google AI Overview visibility;
- Google AI Mode visibility;
- total Google AI share of voice.

The API exposes generated Google Search queries and explicit URL citation annotations. It does **not** provide a defensible complete ledger of every search result or page the model considered. Therefore the MVP may calculate:

- query-fanout metrics;
- answer mention metrics;
- explicit citation metrics.

It must not calculate an “owned retrieval rate” until a provider exposes a complete, verifiable consulted-source set.

---

## 4. Gemini API choice

### 4.1 Use the Interactions API

Use the Gemini Interactions API through direct REST with `httpx`, not a new SDK dependency.

```text
POST https://generativelanguage.googleapis.com/v1beta/interactions
x-goog-api-key: <server-side-key>
```

Request contract:

```json
{
  "model": "gemini-2.5-flash",
  "input": "<standalone benchmark prompt>",
  "system_instruction": "Answer the shopping question using current web information. Cite the sources supporting your recommendations.",
  "tools": [{"type": "google_search"}],
  "store": false
}
```

Rules:

- Never send `previous_interaction_id`.
- Always set `store=false`.
- Never send prior answers or other prompts.
- Keep the system instruction identical for every execution in a run.
- Never include the tracked brand or competitor list in the system instruction.
- Preserve the exact model ID and request configuration in the execution snapshot.

### 4.2 Why `gemini-2.5-flash`

Use `gemini-2.5-flash` for the first benchmark because:

- it supports Google Search grounding;
- its free tier currently includes up to 500 grounded requests per day, shared with Flash-Lite;
- its free-tier input and output tokens are currently free;
- a 5-prompt × 3-repetition test uses 15 requests;
- a 25-prompt × 3-repetition panel uses 75 requests;
- even a 25-prompt × 5-repetition panel uses 125 requests.

Do not automatically switch models if a model is unavailable. A benchmark must remain pinned and reproducible. Surface a configuration error instead.

### 4.3 Response evidence to retain

Extract only observable, useful output:

```text
google_search_call.arguments.queries
model_output.content[].text
model_output.content[].annotations[type=url_citation]
interaction/request ID
usage metadata, when returned
latency and HTTP metadata
```

Do not persist or expose:

- API keys;
- thought summaries;
- thought signatures;
- hidden reasoning;
- search-suggestion HTML;
- unnecessary provider headers.

Store a sanitized provider envelope for debugging rather than the unfiltered raw response.

---

## 5. Current CrawlerAI audit and reuse decisions

### Reuse

The repository already provides the required foundations:

- FastAPI authenticated APIs and user scoping;
- SQLAlchemy async sessions and PostgreSQL JSONB;
- Celery and Redis;
- shared `httpx` provider-client conventions;
- environment-backed settings;
- React Router route registry;
- TanStack React Query polling and cache keys;
- job/history UI patterns;
- CSV/JSON export conventions;
- existing secret encryption for the later admin-key phase.

### Do not reuse directly

#### Existing `run_prompt_task()`

The current generic LLM task path reduces provider output to text/validated JSON and token counts. It would discard search-query fanout, citation offsets and provider execution steps.

**Decision:** create a separate `answer_engines`/`ai_visibility` provider layer. Reuse HTTP, retry, logging and secret patterns, but not the generic prompt-task response contract.

#### Data Enrichment `BackgroundTasks`

The existing Data Enrichment API starts jobs using FastAPI `BackgroundTasks`. That is fast to implement but is not durable across process restarts and is not suitable for a benchmark whose paid calls and evidence must not be duplicated or lost.

**Decision:** use Celery from the first MVP.

#### Crawl tables and run UI

`CrawlRun` and `CrawlRecord` represent acquisition/extraction runs. AI visibility has different evidence and scoring semantics.

**Decision:** use dedicated tables and a dedicated route.

---

## 6. Backend package layout

```text
backend/app/
  ai_visibility/
    __init__.py
    constants.py
    contracts.py
    credentials.py
    service.py
    runner.py
    scoring.py
    normalization.py
    aggregates.py
    exports.py
    recovery.py
    providers/
      __init__.py
      base.py
      gemini.py
      gemini_parser.py
  api/
    ai_visibility.py
  schemas/
    ai_visibility.py
  models/
    ai_visibility.py
  core/config/
    ai_visibility.py
```

Integration files:

```text
backend/app/main.py
backend/app/models/__init__.py
backend/app/core/celery_app.py
backend/app/tasks.py
backend/alembic/versions/20260711_0002_ai_visibility_mvp.py
```

Tests:

```text
backend/tests/unit/test_ai_visibility_normalization.py
backend/tests/unit/test_ai_visibility_scoring.py
backend/tests/unit/test_gemini_interactions_parser.py
backend/tests/unit/test_ai_visibility_run_planner.py
backend/tests/component/test_ai_visibility_api.py
backend/tests/component/test_ai_visibility_runner.py
backend/tests/regression/test_ai_visibility_idempotency.py
backend/tests/fixtures/gemini_interactions_grounded.json
```

---

## 7. Data model

Use six normalized tables. This is still small, but avoids burying query fanout and citations in opaque JSON.

### 7.1 `ai_visibility_projects`

```text
id                    integer PK
user_id               FK users.id, indexed
name                  varchar(160)
brand_name            varchar(160)
brand_aliases         jsonb list[str]
owned_domains         jsonb list[str]
unintended_domains    jsonb list[str]
competitors           jsonb list[object]
country_code          varchar(2), default "AU"
language_code         varchar(16), default "en-AU"
default_repetitions   integer, default 3
created_at            timestamptz
updated_at            timestamptz
```

Example competitor object:

```json
{
  "name": "Kmart",
  "aliases": ["Kmart", "Kmart Australia"],
  "domains": ["kmart.com.au"]
}
```

### 7.2 `ai_visibility_prompts`

```text
id              integer PK
project_id      FK ai_visibility_projects.id ON DELETE CASCADE
prompt_text     text
theme           varchar(80)
intent          varchar(40)
position        integer
is_active       boolean
created_at      timestamptz
updated_at      timestamptz
```

Constraints:

- unique `(project_id, position)`;
- non-empty prompt text;
- accepted intents: `discovery`, `comparison`, `purchase`, `service`, `local`.

### 7.3 `ai_visibility_runs`

```text
id                    integer PK
project_id            FK ai_visibility_projects.id ON DELETE CASCADE
user_id               FK users.id
status                varchar(24)
provider               varchar(32), initial value "gemini"
model                  varchar(160)
repetitions           integer
random_seed           bigint
system_instruction    text
configuration         jsonb
summary               jsonb
requested_count       integer
completed_count       integer
failed_count          integer
created_at            timestamptz
started_at            timestamptz nullable
completed_at          timestamptz nullable
updated_at            timestamptz
```

Statuses:

```text
pending
running
completed
degraded
failed
cancelled
```

### 7.4 `ai_visibility_executions`

One row per prompt × repetition.

```text
id                    integer PK
run_id                FK ai_visibility_runs.id ON DELETE CASCADE
prompt_id             FK ai_visibility_prompts.id ON DELETE SET NULL nullable
prompt_text_snapshot  text
prompt_theme_snapshot varchar(80)
prompt_intent_snapshot varchar(40)
provider              varchar(32)
model                 varchar(160)
repetition            integer
randomized_position   integer
status                varchar(24)
attempt_count         integer default 0
answer_text           text
request_snapshot      jsonb
provider_metadata     jsonb
score                  jsonb
error_code             varchar(80) nullable
error_message          text nullable
latency_ms             integer nullable
started_at             timestamptz nullable
completed_at           timestamptz nullable
created_at             timestamptz
updated_at             timestamptz
```

Unique constraint:

```text
(run_id, prompt_id, provider, repetition)
```

Execution statuses:

```text
pending
running
completed
failed
cancelled
```

### 7.5 `ai_visibility_search_events`

One row per query generated by Gemini.

```text
id                integer PK
execution_id      FK ai_visibility_executions.id ON DELETE CASCADE
sequence          integer
query_text        text
normalized_query  text
features          jsonb list[str]
injected_brands   jsonb list[str]
created_at        timestamptz
```

Unique constraint:

```text
(execution_id, sequence)
```

### 7.6 `ai_visibility_citations`

One row per explicit `url_citation` annotation.

```text
id                    integer PK
execution_id          FK ai_visibility_executions.id ON DELETE CASCADE
ordinal               integer
url                   text
normalized_url        text
normalized_domain     varchar(255)
title                 text
start_index           integer nullable
end_index             integer nullable
cited_text            text
is_owned_domain       boolean
is_unintended_domain  boolean
matched_competitor    varchar(160) nullable
created_at            timestamptz
```

Indexes:

```text
(execution_id, ordinal)
(normalized_domain)
(is_owned_domain)
(matched_competitor)
```

---

## 8. Provider abstraction

### 8.1 Contracts

```python
@dataclass(frozen=True, slots=True)
class AnswerEngineRequest:
    execution_id: int
    prompt: str
    system_instruction: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SearchEventResult:
    sequence: int
    query: str


@dataclass(frozen=True, slots=True)
class CitationResult:
    ordinal: int
    url: str
    title: str
    start_index: int | None
    end_index: int | None
    cited_text: str


@dataclass(frozen=True, slots=True)
class AnswerEngineResponse:
    provider: str
    model: str
    answer_text: str
    search_events: tuple[SearchEventResult, ...]
    citations: tuple[CitationResult, ...]
    provider_metadata: dict[str, object]
    usage: dict[str, object]
    latency_ms: int
```

```python
class AnswerEngineAdapter(Protocol):
    provider_id: str

    async def execute(
        self,
        request: AnswerEngineRequest,
    ) -> AnswerEngineResponse: ...
```

### 8.2 Gemini adapter

`GeminiAnswerEngineAdapter` should:

1. obtain the key from `AiVisibilityCredentialResolver`;
2. use one shared `httpx.AsyncClient`;
3. submit a new Interactions request with `store=false`;
4. apply the configured timeout;
5. parse query events and citations;
6. sanitize provider metadata;
7. classify provider errors;
8. never retry a valid answer merely because the brand is absent.

### 8.3 Future providers

Later adapters must implement the same contract:

```text
OpenAIAnswerEngineAdapter
AnthropicAnswerEngineAdapter
ManualConsumerImportAdapter
```

No future adapter should require changes to projects, runs, executions, search events, citations, scoring or the main results UI.

---

## 9. Credential and settings design

### 9.1 MVP environment settings

Add a dedicated settings class rather than overloading the extraction LLM settings:

```python
class AiVisibilitySettings(BaseSettings):
    model_config = settings_config(env_prefix="AI_VISIBILITY_")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_interactions_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    request_timeout_seconds: float = 60.0
    run_concurrency: int = 2
    max_retries: int = 2
    retry_base_delay_seconds: float = 2.0
    stale_execution_seconds: int = 300
    max_executions_per_run: int = 250
    daily_request_soft_cap: int = 400
```

Environment variable:

```text
AI_VISIBILITY_GEMINI_API_KEY=<key>
```

The 400-request soft cap leaves headroom below the current 500 grounded-request free-tier limit. The cap is a CrawlerAI safety control, not a replacement for Google's real quota response.

### 9.2 Credential resolver

```python
class AiVisibilityCredentialResolver:
    async def resolve(self, provider: str) -> ProviderCredential | None:
        ...
```

MVP resolution order:

```text
environment variable
  → not configured
```

Later resolution order:

```text
encrypted database config
  → environment fallback
  → not configured
```

The API must expose only:

```json
{
  "provider": "gemini",
  "configured": true,
  "model": "gemini-2.5-flash",
  "supports_search_fanout": true,
  "supports_citations": true
}
```

Never return or log the key.

---

## 10. Run creation and independence controls

### 10.1 Run planning

When a run is created:

1. validate project ownership;
2. load active prompts;
3. validate execution count against the configured maximum;
4. generate a cryptographically random 64-bit seed;
5. materialize all prompt × repetition execution rows;
6. shuffle the execution order using the persisted seed;
7. freeze prompt, project, model and instruction snapshots;
8. commit the entire plan;
9. dispatch the Celery task only after commit.

### 10.2 Independence invariants

Every execution must satisfy:

```text
one prompt
one fresh Interactions request
no previous_interaction_id
store=false
no previous answer
no provider conversation
no tracked-brand list in the request
```

The scorer receives brand and competitor metadata only **after** generation.

### 10.3 Prompt design

The prompt text must remain the shopper question. For the benchmark panel, every prompt should already carry the intended geography, for example:

```text
cheapest place to buy school uniforms in Australia
```

A fixed neutral system instruction may require current sources and citations, but must not insert candidate brands.

The setup screen should display the exact effective request before a run starts.

---

## 11. Celery execution and durability

### 11.1 Task

Add:

```text
ai_visibility.process_run
```

Prefer a small refactor of `backend/app/tasks.py` so the current worker-loop lifecycle helper can run either:

```text
crawl.process_run
ai_visibility.process_run
```

The helper should accept a task label and async coroutine factory rather than hard-coding crawl processing.

### 11.2 Runner algorithm

```text
load run
  → mark running
  → reset stale running executions to pending
  → load pending executions in randomized order
  → execute through asyncio.Semaphore(run_concurrency)
  → persist every completed or failed execution immediately
  → update counters after every result
  → finalize completed/degraded/failed
```

Use a default concurrency of 2. This avoids unnecessary quota bursts and makes evidence easier to inspect. Speed is not the bottleneck for 15–75 requests.

### 11.3 Idempotency

- All execution rows exist before dispatch.
- The unique execution constraint prevents duplicates.
- Completed rows are never called again during resume.
- A task restart resets only stale `running` executions.
- Provider request IDs are persisted when returned.
- User-triggered `retry-failed` resets only retryable failures.

### 11.4 Retry policy

Retry:

- connection failures;
- read/connect timeouts;
- HTTP 429;
- HTTP 500, 502, 503 and 504.

Do not retry:

- HTTP 400 invalid request;
- HTTP 401/403 credential failure;
- a valid response with no search call;
- a valid response with no tracked-brand mention;
- a valid response with no owned-domain citation;
- a valid but surprising answer.

Persist the original failure, attempt count and final error category.

### 11.5 Cancellation

`POST /runs/{id}/cancel` sets the run to `cancelled`. The worker checks status before taking the next pending execution and marks unstarted rows cancelled. In-flight provider calls may finish and persist, but no new calls start.

---

## 12. Gemini response parser

Build a tolerant parser because provider JSON field casing may differ between REST examples and SDK objects.

### Search fanout

For every step whose type is `google_search_call`:

```text
arguments.queries[]
```

Create one `SearchEventResult` per query in observed order.

### Answer

Concatenate text blocks from `model_output.content[]` in provider order. Preserve paragraph boundaries.

### Citations

For each annotation whose type is `url_citation`:

- read URL and title;
- accept both `start_index`/`end_index` and `startIndex`/`endIndex`;
- validate offsets against the containing text block;
- derive cited text from the answer rather than trusting a duplicate provider field;
- preserve duplicate URLs when they support different answer spans;
- assign a stable ordinal.

### Search-not-used result

If Gemini returns a valid answer without `google_search_call`:

```text
status = completed
score.search_used = false
search_events = []
```

This is a real benchmark result, not an execution failure.

### Sanitization

`provider_metadata` may retain:

```text
interaction ID
finish/status information
usage metadata
model ID
HTTP request ID
step type sequence
```

It must strip:

```text
thought steps
thought summaries
signatures
API key
search-suggestion HTML
full request headers
```

---

## 13. Deterministic scoring

The MVP's headline metrics must not depend on another LLM.

### 13.1 Text normalization

Normalize for matching:

- Unicode NFKC;
- case-folding;
- `&` and `and` equivalence;
- punctuation removal for alias matching;
- whitespace collapse;
- domain lowercase and `www.` removal;
- URL fragment removal.

Avoid fuzzy brand matching in the initial release. Use configured aliases to prevent false positives.

### 13.2 Per-execution score

```json
{
  "search_used": true,
  "search_query_count": 3,
  "brand_mentioned": true,
  "brand_first_offset": 121,
  "brand_injected_in_search": false,
  "owned_domain_cited": true,
  "owned_citation_count": 1,
  "unintended_domain_cited": false,
  "citation_count": 6,
  "competitors_mentioned": ["Kmart", "BIG W"],
  "competitors_injected_in_search": ["Kmart"],
  "competitor_domains_cited": ["kmart.com.au"],
  "fanout_features": ["commercial", "comparison"]
}
```

### 13.3 Fanout feature taxonomy

Use transparent keyword rules:

```text
community: reddit, forum, discussion, experiences
review: review, reviews, rating, ratings, customer feedback
comparison: vs, versus, alternative, alternatives, compare, best
commercial: price, prices, cheap, affordable, budget, sale, under
local: near me, nearby, store, Sydney, Melbourne, Brisbane, Perth
service: click and collect, delivery, returns, shipping
freshness: latest, current, today, 2026
product_evidence: material, fabric, size, multipack, availability, stock
```

Persist the matched features on each search event so the UI can explain every classification.

### 13.4 Run aggregates

For each run calculate:

```text
brand mention rate
owned-domain citation rate
mention-to-owned-citation conversion
brand fanout-injection rate
competitor fanout-injection rate
search-use rate
average generated queries per execution
wrong/unintended-domain citation rate
citation share by domain
competitor mention rate
competitor citation rate
per-prompt repetition variance
```

Do not report recommendation rank in the MVP. The order of textual mentions is not always equivalent to recommendation order. Store first mention offset only as an inspectable signal.

### 13.5 Volatility

For Boolean metrics across repetitions:

```text
stability = max(true_count, false_count) / repetition_count
```

Examples with three repetitions:

```text
3/3 same outcome → stable
2/3 same outcome → variable
```

The UI should show `3/3`, `2/3`, or `1/3`, not hide the individual runs behind one percentage.

---

## 14. API design

Router prefix:

```text
/api/ai-visibility
```

### Provider status

```text
GET  /providers
POST /providers/gemini/test
```

The connection test executes one minimal grounded request only when explicitly invoked.

### Projects

```text
POST   /projects
GET    /projects
GET    /projects/{project_id}
PUT    /projects/{project_id}
DELETE /projects/{project_id}
```

### Prompts

```text
PUT  /projects/{project_id}/prompts
POST /projects/{project_id}/prompts/import
```

`PUT` performs an ordered bulk replacement inside one transaction for the MVP.

### Runs

```text
POST /runs
GET  /runs?project_id=&limit=
GET  /runs/{run_id}
POST /runs/{run_id}/cancel
POST /runs/{run_id}/retry-failed
```

Create-run payload:

```json
{
  "project_id": 1,
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "repetitions": 3,
  "prompt_ids": [1, 2, 3, 4, 5]
}
```

### Evidence

```text
GET /runs/{run_id}/executions?page=&limit=&status=&theme=
GET /executions/{execution_id}
```

Execution detail returns:

```text
answer
search events
citations
score
provider metadata
error details
```

### Exports

```text
GET /runs/{run_id}/export.csv
GET /runs/{run_id}/export.md
```

CSV uses one row per execution. Markdown provides a presentation-ready provider summary plus a per-prompt evidence appendix.

---

## 15. Frontend architecture

### 15.1 Route

Add an authenticated Intelligence route:

```text
/ai-visibility
```

Suggested nav label:

```text
AI Visibility
```

### 15.2 Files

```text
frontend/app/ai-visibility/
  page-view.tsx
  ai-visibility-state.ts
  project-setup.tsx
  prompt-panel.tsx
  provider-status.tsx
  run-progress.tsx
  result-summary.tsx
  prompt-matrix.tsx
  execution-detail.tsx
  search-fanout-table.tsx
  citation-table.tsx

frontend/lib/api/
  ai-visibility.ts

frontend/lib/api/types.ts
frontend/lib/api/index.ts
frontend/src/api/query-keys.ts
frontend/src/app/route-registry.ts
```

### 15.3 One-page MVP workflow

Use three top-level tabs or states:

```text
Setup | Running | Results
```

#### Setup

Fields:

```text
Project name
Brand name
Aliases
Owned domains
Unintended domains
Competitors
Country/language
Prompt panel
Repetitions
Provider/model status
```

Include a visible effective-request preview proving that the brand list is not sent to Gemini.

#### Running

Show:

```text
completed / total
failed count
current provider/model
prompt/repetition matrix
elapsed time
cancel action
```

Poll run detail every 2 seconds while active and every 10 seconds when degraded. WebSockets are unnecessary for the MVP.

#### Results

Headline cards:

```text
mention rate
owned citation rate
fanout injection rate
search-use rate
unintended-domain citations
```

Primary table:

| Prompt | Repetition | Search queries | Brand mentioned | Owned citation | Competitors |
|---|---:|---:|---|---|---|

Execution detail tabs:

```text
Answer | Search Fanout | Citations | Raw Metadata
```

“Raw Metadata” must display sanitized metadata only.

### 15.4 React Query keys

```typescript
aiVisibility: {
  all: ['ai-visibility'],
  providers: () => ['ai-visibility', 'providers'],
  projects: () => ['ai-visibility', 'projects'],
  project: (projectId: number) => ['ai-visibility', 'project', projectId],
  runs: (projectId: number) => ['ai-visibility', 'runs', projectId],
  run: (runId: number) => ['ai-visibility', 'run', runId],
  executions: (runId: number, filters: object) =>
    ['ai-visibility', 'executions', runId, filters],
  execution: (executionId: number) =>
    ['ai-visibility', 'execution', executionId],
}
```

---

## 16. Export contracts

### 16.1 CSV

One row per execution:

```text
run_id
execution_id
prompt_id
prompt
prompt_theme
prompt_intent
provider
model
repetition
randomized_position
status
search_used
search_queries
fanout_features
injected_brands
answer_text
brand_mentioned
brand_first_offset
owned_domain_cited
owned_citation_count
unintended_domain_cited
competitors_mentioned
competitors_injected_in_search
competitor_domains_cited
citation_urls
citation_domains
latency_ms
error_code
error_message
```

Use JSON strings for multi-value cells so evidence is not lost.

### 16.2 Markdown

Structure:

```text
Methodology
Configuration snapshot
Provider summary
Prompt-level results
Fanout themes
Citation-domain summary
Volatility observations
Failures and limitations
Evidence appendix
```

The methodology section must automatically state:

- provider/model;
- execution date;
- one fresh stateless request per execution;
- prompt count and repetitions;
- randomized order and seed;
- that results measure Gemini grounded API, not the consumer product;
- that only explicit citations are counted;
- that complete consulted-source coverage is unavailable.

---

## 17. Test plan

### Unit tests

1. Alias normalization:
   - `Best&Less`;
   - `Best & Less`;
   - `Best and Less`.
2. Domain normalization:
   - `www.bestandless.com.au` matches owned domain;
   - Zendesk and SAP-origin hosts match unintended domains only.
3. Gemini query extraction from multiple search calls.
4. Citation extraction with snake_case and camelCase offsets.
5. Invalid/out-of-range annotation offsets.
6. Search-not-used valid answer.
7. Thought/signature stripping.
8. Fanout feature classification.
9. Brand injection detection in queries.
10. Run randomization is deterministic for the stored seed.
11. Run aggregate calculations.
12. Retry classification.

### Component tests

1. Project ownership enforcement.
2. Run creation materializes the exact expected execution count.
3. Run creation does not dispatch before commit.
4. Provider not configured returns a clear 409/422 response.
5. Task persists every completed execution independently.
6. Mixed success/failure produces `degraded`.
7. Retry-failed does not rerun completed rows.
8. Cancellation stops new calls.
9. Export contains the persisted evidence.

### Regression tests

1. Worker restart does not duplicate completed calls.
2. Unique constraint prevents duplicate execution rows.
3. Stale running executions recover to pending.
4. Brand and competitor metadata never appears in the Gemini request snapshot unless it was explicitly part of the shopper prompt.
5. API keys never appear in serialized schemas, logs or exports.

### Frontend tests

1. Provider-not-configured state.
2. Prompt bulk edit/import.
3. Run progress polling.
4. Execution detail fanout and citations.
5. Failure display and retry.
6. CSV/Markdown download.

### Live smoke test

Run one non-sensitive prompt through the real key and verify:

```text
HTTP success
store=false in request snapshot
at least one model output block
queries captured when search is used
citation offsets render correctly
key absent from logs and response
```

Do not run live API tests in the default test suite.

---

## 18. Weekend delivery sequence

### Slice 1 — Provider probe and fixture

Before building the UI:

1. add the dedicated settings object;
2. create a small developer-only Gemini probe command or test script;
3. call `gemini-2.5-flash` with Google Search and `store=false`;
4. save a sanitized response as the parser fixture;
5. confirm the actual field casing and usage payload returned to this project.

**Gate:** do not design the parser from documentation alone.

### Slice 2 — Persistence and run planner

1. migration and models;
2. schemas;
3. project/prompt CRUD;
4. run materialization;
5. deterministic randomization;
6. provider status endpoint.

**Gate:** a run of 5 prompts × 3 repetitions creates exactly 15 pending executions with no duplicate key.

### Slice 3 — Gemini execution

1. shared client;
2. adapter and parser;
3. retry classifier;
4. scoring;
5. Celery task;
6. stale execution recovery;
7. run finalization.

**Gate:** a 15-execution run completes or degrades without duplicate calls and resumes safely after an intentional worker restart.

### Slice 4 — Minimal UI

1. route and navigation;
2. setup form;
3. prompt editor;
4. run progress;
5. results table;
6. execution drawer with answer/fanout/citations.

**Gate:** the complete benchmark can be launched and inspected without database or API tooling.

### Slice 5 — Presentation exports and hardening

1. CSV export;
2. Markdown report;
3. methodology/limitations block;
4. cancellation and retry-failed;
5. security/log review;
6. final 5-prompt validation run.

**Gate:** export content matches persisted execution rows and can be used directly as an evidence appendix.

---

## 19. First benchmark configuration

### Project

```text
Name: Best&Less Australia — AI Visibility Pilot
Brand: Best&Less
Aliases: Best&Less; Best & Less; Best and Less
Owned domain: bestandless.com.au
Unintended domains:
  bestlesscomau.zendesk.com
  jsapps.co6tqo-bestlesss1-p1-public.model-t.cc.commerce.ondemand.com
Competitors:
  Kmart — kmart.com.au
  Target — target.com.au
  BIG W — bigw.com.au
Country: AU
Language: en-AU
```

### Five-prompt pre-Monday subset

```text
cheapest place to buy school uniforms in Australia
where to buy Bluey clothes for kids Australia
best value baby bodysuit multipacks Australia
affordable women's basics Australia
budget men's underwear multipacks Australia
```

### Run

```text
Provider: Gemini grounded API — Google Search
Model: gemini-2.5-flash
Prompts: 5
Repetitions: 3
Executions: 15
Concurrency: 2
```

After validating the system, run the complete 25-prompt panel at three repetitions:

```text
25 prompts × 3 repetitions = 75 executions
```

---

## 20. MVP acceptance criteria

The MVP is accepted only when all of the following are true:

1. A user can create a project, brand aliases, domains, competitors and prompts from `/ai-visibility`.
2. The UI reports whether the Gemini key is configured without exposing it.
3. A run pre-materializes every execution and records its random seed/order.
4. Every execution is a new Interactions request with `store=false` and no previous interaction ID.
5. The Gemini request contains no scorer-only brand or competitor metadata.
6. Generated Google Search queries are visible as individual search events.
7. Explicit URL citation annotations are visible with cited answer spans.
8. The answer, search events, citations and deterministic score survive process restart.
9. Missing brand mentions and citations are stored as valid outcomes, not retried.
10. Completed executions are never duplicated by resume or retry.
11. The UI shows all repetitions rather than only an aggregate.
12. CSV and Markdown exports reproduce the stored evidence.
13. The methodology states that this is Gemini grounded API testing, not consumer Gemini or AI Overviews.
14. The system does not claim a complete consulted-source ledger.
15. No API key, thought summary, thought signature or hidden reasoning is stored or returned.

---

## 21. Post-MVP extension path

### Provider additions

Implement in this order:

```text
OpenAI Responses + web search
Anthropic Messages + web search
manual consumer-surface import
```

Each adapter maps to the existing execution/search-event/citation contract.

### Credential UI

Add encrypted provider configurations using the existing encryption and admin configuration patterns:

```text
provider
model
api_key_encrypted
is_active
monthly request cap
per-run request cap
```

Keep environment fallback for deployment portability.

### Analytical additions

Only after multi-provider evidence exists:

- provider comparison matrix;
- historical trend lines;
- monthly scheduled panels;
- source-domain categories;
- human/LLM citation relevance review;
- sentiment with evidence;
- cited-page technical audit handoff;
- alerting on meaningful movement beyond the measured volatility band.

---

## 22. Validated external assumptions

This plan is based on the current official Gemini documentation as of 11 July 2026:

1. The Interactions API is generally available and recommended for new projects.
2. Interactions are stored by default, but `store=false` enables stateless operation.
3. Google Search grounding returns observable `google_search_call` query steps and URL citation annotations.
4. `gemini-2.5-flash` supports Google Search grounding.
5. Its free tier currently provides up to 500 grounded requests per day, shared with Flash-Lite.
6. Free-tier content may be used by Google to improve its products; do not place confidential client information in prompts.

These assumptions should be checked again when the adapter is implemented because model availability, limits and pricing can change.
