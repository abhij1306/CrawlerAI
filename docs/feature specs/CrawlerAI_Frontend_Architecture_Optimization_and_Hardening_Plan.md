# CrawlerAI Frontend Architecture Optimization and Hardening Plan

**Audit source:** latest `main` branch of `abhij1306/CrawlerAI` and `docs/feature specs/frontend-audit.md`  
**Objective:** simplify the frontend into a production-ready operator application by removing duplicate ownership, stale compatibility layers, contract drift, and oversized workflow components—without deleting useful capabilities.  
**Architecture style:** React + Vite modular frontend, feature-oriented, API-driven  
**Status:** CLOSED for the 2026-06-20 productionization scope. Strategic follow-ups are recorded in `frontend-architecture-productionization-closure.md`.

---

# 1. Executive decision

Keep the current frontend stack.

```text
React 19
Vite
React Router
TanStack Query
React Hook Form
Zod
Tailwind CSS
Radix Dialog
Lucide
Vitest
MSW
Playwright
```

Do not migrate to Next.js.

CrawlerAI is an authenticated operator application. It does not currently need:

```text
server-side rendering
SEO-first page rendering
React Server Components
Next.js route conventions
Next.js image optimization
Next.js server actions
```

The frontend problem is not the framework. The main debt is:

```text
multiple owners of the same state
manual API and backend-contract drift
feature logic inside giant render components
legacy backend semantics recomputed in the browser
duplicated polling/WebSocket synchronization
stale selector capabilities
Next.js compatibility residue inside a Vite app
large shared barrels that hide ownership
CSS and design patterns without strict domain boundaries
```

The target is:

```text
Router and route metadata
    |
    v
Feature screen
    |
    +-- TanStack Query: server state
    +-- React Hook Form: editable form state
    +-- route/search params: navigable UI state
    +-- local reducer/state: temporary view state only
    |
    v
Feature API module
    |
    v
Typed backend contract
```

The frontend should render canonical backend results. It should not infer crawl semantics, repair records, recompute verdicts, or reconstruct quality from raw artifacts.

---

# 2. Review of the agent report

The report in `docs/feature specs/frontend-audit.md` is useful but incomplete.

## Correct recommendations

Retain these recommendations:

- delete confirmed dead files and exports;
- remove confirmed unused npm dependencies;
- consolidate duplicated formatting/profile helpers;
- split the largest workflow components;
- split `log-terminal.tsx`;
- split selector, admin LLM, enrichment, app shell, and form-field owners;
- reduce oversized shared barrels;
- reduce global CSS ownership;
- lower cognitive load and improve testability.

## Recommendations that need revision

### File splitting is not the first priority

A 1,400-line file is a symptom. Splitting it into ten files does not fix architecture when the same feature still has:

```text
route state
form state
server state
action state
browser storage
query cache
WebSocket state
polling state
backend semantic derivation
```

mixed together.

Ownership must be corrected before JSX is extracted.

### Do not create generic “effects” and “actions” dumping grounds

Avoid files such as:

```text
crawl-config-effects.ts
crawl-config-actions.ts
use-run-effects.ts
crawl-run-actions.ts
```

when they merely relocate unrelated logic.

Prefer named owners:

```text
useCrawlRouteState
useDomainProfile
useSelectorMemory
useLaunchCrawl
useRunResource
useRunLogStream
useRunRecords
useRunMutations
```

### Do not split global CSS into arbitrary category files

The correct split is ownership-based:

```text
tokens and themes
base browser styles
small cross-feature utilities
co-located feature/component styles
```

Do not create a second monolithic global styling framework across nine CSS files.

### Do not replace the existing table without evidence

`RecordsTable` already implements manual virtualization and sticky columns. Remove the unused `@tanstack/react-table` dependency, but do not rewrite the table merely because that package is removed.

Refactor the table only where the data contract and accessibility require it.

---

# 3. Current architecture findings

## 3.1 Strong foundations to preserve

The frontend already has useful architectural foundations:

- route-level code splitting;
- one React Query provider;
- centralized API transport;
- strict TypeScript;
- runtime Zod checks for selected APIs;
- React Hook Form for crawl configuration;
- Zustand isolated to one run-workspace store;
- WebSocket logs with polling fallback;
- custom virtualized records table;
- typed UI primitives;
- semantic design tokens;
- frontend telemetry;
- Vitest, MSW, and Playwright;
- architecture and styling scripts;
- selector preview sandboxing;
- explicit four-surface crawl dispatch.

The plan strengthens these rather than replacing them indiscriminately.

## 3.2 Main architectural problems

### A. API retry ownership is unsafe

The transport retries all HTTP operations up to three times, including:

```text
POST
PUT
PATCH
DELETE
```

TanStack Query also owns retry policy.

This can duplicate non-idempotent operations such as:

```text
create crawl
create intelligence job
create enrichment job
save selector
reset workspace data
```

### B. API contracts are manually duplicated and partially validated

The backend owns FastAPI schemas, while the frontend manually maintains:

```text
lib/api/types.ts
lib/api/schemas.ts
lib/api/index.ts
```

Some responses are runtime validated and others are trusted blindly.

Known stale contracts include:

```text
selector XPath and regex fields
review selector_memory and selector_suggestions
string surface where an exact CrawlSurface exists
legacy record raw/discovered/source-trace ownership
```

### C. Crawl configuration has too many state owners

`crawl-config-screen.tsx` combines:

```text
React Hook Form
local reducer
route state reducer
multiple refs used as synchronization guards
TanStack Query
sessionStorage
manual browser history updates
mutation state
selector/domain memory state
```

It also changes local state during render.

### D. Run workspace duplicates server resources

The run screen has separate server queries for:

```text
table records
JSON records
run
logs
domain recipe
history
```

Table and JSON records are the same backend resource with different fetch limits and independent caches.

It also combines:

```text
TanStack Query polling
manual WebSocket lifecycle
local log buffer
terminal-state refetch effects
terminal record synchronization retries
Zustand UI state
local reducer state
client-side quality/verdict calculations
```

### E. Browser recomputes backend truth

The UI derives or reinterprets:

```text
extraction verdict
quality
confidence
LLM involvement
record fields
visible columns
variant completeness
run summary
```

from combinations of:

```text
data
raw_data
discovered_data
source_trace
log strings
settings
```

The backend architecture is moving toward canonical `UrlResult`, `ExtractionResult`, metrics, and lineage. The frontend must consume those values directly.

### F. The Vite app retains Next.js compatibility residue

The frontend has wrappers emulating:

```text
next/link
next/navigation
next/dynamic
next/image
```

Examples include:

```text
routing/link
routing/navigation
routing/dynamic
routing/image
Route = string
ssr: false ignored by Vite
router.refresh() performing a full reload
```

These wrappers obscure React Router and browser behavior.

### G. Selector UI contradicts the new extraction direction

The new backend direction is CSS-only explicit recipes, while the frontend still supports:

```text
XPath
CSS
regex
automatic surface inference
LLM XPath source labels
```

The selector tool also defaults new rows to XPath.

### H. Shared barrels obscure ownership

`components/crawl/shared.tsx` exports:

```text
components
types
formatters
quality scoring
record utilities
surface logic
log utilities
table utilities
form fields
```

This makes dependencies difficult to trace and allows unrelated pages to import crawl-specific UI.

### I. The design system has mixed concerns

`patterns.tsx` contains:

```text
top-bar synchronization
ReactNode serialization
tabs
page headers
sections
metrics
loading states
navigation patterns
run workspace patterns
```

A shared UI file should not own page routing/header synchronization.

### J. Architecture enforcement is too weak

The current script allows:

```text
crawl-run-screen.tsx <= 1,400 lines
crawl-config-screen.tsx <= 1,500 lines
```

and checks only a few historical patterns.

It does not protect module ownership or backend/frontend contract integrity.

---

# 4. Final target frontend structure

Consolidate the application under `src/`.

```text
frontend/
  src/
    app/
      app.tsx
      router.tsx
      route-registry.ts
      providers.tsx
      error-boundary.tsx

    api/
      client.ts
      errors.ts
      generated/
        schema.d.ts
      contracts/
        runtime-schemas.ts
      query-client.ts
      query-keys.ts

    features/
      auth/
      crawl-config/
      run-workspace/
      run-history/
      selectors/
      domain-memory/
      product-intelligence/
      data-enrichment/
      run-trace/
      dashboard/
      jobs/
      admin-users/
      admin-llm/

    shared/
      ui/
      layout/
      hooks/
      format/
      telemetry/
      utils/
      constants/

    styles/
      tokens.css
      themes.css
      base.css
      utilities.css

    main.tsx
```

## Dependency direction

```text
app
  -> features
      -> api
      -> shared
  -> shared

shared must not import features
api must not import features
one feature must not deep-import another feature
```

Feature-to-feature navigation happens through:

```text
routes
typed prefill contracts
shared backend records
```

not through direct internal component imports.

---

# 5. State ownership contract

Use this decision table consistently.

| State type | Owner |
|---|---|
| Backend/server data | TanStack Query |
| Create/update/delete action | TanStack `useMutation` |
| Editable form fields | React Hook Form |
| Navigable filters/tabs/selected run | URL/search params |
| Temporary modal/hover/expanded row | local `useState`/reducer |
| Cross-page durable prefill | explicit versioned session-storage adapter |
| Auth session | one auth query |
| Design theme/sidebar preference | local storage through focused hooks |
| Backend verdict/quality/metrics | backend response, never recomputed |
| Global application state | avoid unless multiple routes truly share mutable client-only state |

## Zustand decision

Remove Zustand after the run workspace migration.

It is currently used only for page-local run UI state:

```text
selected record IDs
active output tab
table page
JSON visible count
history drawer
```

These do not justify a global store.

Use:

```text
search params for active tab/run navigation
local reducer/context for row selection and drawer state
query state for server resources
```

---

# 6. API and contract architecture

## 6.1 Split transport from feature APIs

Target:

```text
src/api/client.ts
src/features/crawl-config/api.ts
src/features/run-workspace/api.ts
src/features/selectors/api.ts
src/features/product-intelligence/api.ts
...
```

`client.ts` only owns:

```text
base URL
credentials
headers
response parsing
typed API errors
AbortSignal
request ID
transport telemetry
```

It does not own feature endpoint paths.

## 6.2 Correct retry semantics

### Transport layer

Do not automatically retry mutations.

```text
GET/HEAD:
  retry network errors and selected 5xx responses

POST/PUT/PATCH/DELETE:
  no automatic transport retry
  unless the caller supplies a backend-supported idempotency key
```

### TanStack Query

TanStack Query is the UI retry owner.

Query retry policy:

```text
401/403/404/validation errors -> no retry
408/429/5xx/network errors     -> bounded retry
```

Mutation retry:

```text
false by default
```

## 6.3 Abort stale requests

All query functions accept TanStack Query’s `signal`.

Example:

```ts
queryFn: ({ signal }) => runsApi.getRun(runId, { signal })
```

Cancel:

```text
stale domain-profile lookup
stale selector lookup
route-transition requests
superseded search requests
unmounted page requests
```

## 6.4 Generate backend contract types

Use FastAPI’s OpenAPI document as the source of truth.

Recommended lightweight approach:

```text
openapi-typescript as a dev dependency
generated TypeScript declarations committed or generated in CI
thin handwritten feature adapters
```

Do not add a large generated SDK or generated query hooks initially.

CI must fail when:

```text
backend OpenAPI changes
and generated frontend types are stale
```

## 6.5 Runtime validation policy

Retain Zod for:

```text
authentication/session
crawl run
crawl records
domain profile
observability payloads
high-risk admin/config payloads
```

Do not maintain a second complete handwritten model tree for every endpoint.

## 6.6 Typed enums

Frontend contracts must use exact backend values for:

```text
Surface
RunStatus
UrlVerdict
AcquisitionOutcome
BrowserEngine
JobStatus
ReviewStatus
```

Remove permissive types such as:

```ts
surface: string
status: string
```

where the backend contract is closed.

## 6.7 Query key factories

Create one query-key owner.

```ts
queryKeys.auth.me()
queryKeys.runs.list(filters)
queryKeys.runs.detail(runId)
queryKeys.runs.records(runId, filters)
queryKeys.runs.logs(runId)
queryKeys.selectors.list(domain, surface)
queryKeys.intelligence.jobs()
```

No feature should construct ad hoc string arrays directly.

---

# 7. Routing, authentication, and source layout

## 7.1 Keep Vite and React Router

Use React Router directly.

Delete the Next-style compatibility wrappers after call-site migration:

```text
src/routing/navigation.ts
src/routing/dynamic.tsx
src/routing/image.tsx
Route = string compatibility type
```

`AppLink` may remain only if renamed and intentionally provides:

```text
internal React Router navigation
external URL handling
mailto/tel handling
```

Otherwise use React Router `Link` directly.

## 7.2 One route registry

Create:

```ts
type AppRoute = {
  path: string;
  lazy: () => Promise<RouteModule>;
  nav?: {
    group: string;
    label: string;
    icon: LucideIcon;
    exact?: boolean;
  };
  auth: 'public' | 'authenticated' | 'admin';
};
```

The registry owns:

```text
route paths
lazy modules
navigation labels/icons
role requirements
page metadata
```

This removes router/sidebar drift.

## 7.3 Authentication guard

Move session gating out of the visual shell.

```text
PublicRoutes
RequireSession
RequireAdmin
AppShellLayout
```

The app shell should render layout, not own auth redirects.

## 7.4 Error boundaries

Add:

```text
root application error boundary
route-level error elements
QueryErrorResetBoundary
feature retry action
```

A rendering error in logs, records, or intelligence should not blank the entire application.

---

# 8. Crawl configuration redesign

## 8.1 Final ownership

### URL/search params

Own:

```text
domain
surface tab
crawl mode
prefilled URL
```

Use React Router setters, not direct `window.history.replaceState`.

### React Hook Form

Own all editable configuration:

```text
target URL
bulk URLs
CSV
max records
proxy settings
additional fields
run profile
diagnostics
advanced acquisition settings
selector rows
```

Use:

```text
useFieldArray for selector/additional-field rows
dirtyFields for profile overrides
reset(savedProfile, { keepDirtyValues: true })
```

### TanStack Query

Own:

```text
saved domain profile
domain selectors
selector suggestions
preview/test responses
```

### Mutations

Own:

```text
launch crawl
launch CSV crawl
save domain profile
save selectors
generate selector suggestions
test selector
```

## 8.2 Eliminate render-time state changes

Remove ref-guarded dispatches during render.

Profile/domain changes should be handled by:

```text
query key changes
form reset rules
explicit route state transitions
```

## 8.3 Target feature structure

```text
features/crawl-config/
  page.tsx
  controller.ts
  schema.ts
  route-state.ts
  dispatch.ts
  api.ts
  query-options.ts
  mutations.ts
  components/
    target-card.tsx
    mode-picker.tsx
    crawl-settings-card.tsx
    field-config-card.tsx
    advanced-settings-panel.tsx
    launch-actions.tsx
```

`page.tsx` target:

```text
<= 250 lines
```

The controller target:

```text
<= 250 lines
```

Do not replace one god component with one god hook.

## 8.4 Preserve useful capabilities

Keep:

```text
four explicit surfaces
single/sitemap/bulk/batch/CSV workflows
domain profile lookup
domain selector memory
advanced browser/acquisition settings
proxy inputs
diagnostic capture settings
field selector testing
crawl prefill
```

---

# 9. Run workspace redesign

## 9.1 One run resource model

Create:

```text
useRun(runId)
useRunRecords(runId)
useRunLogStream(runId)
useRunRecipe(runId)
useRunActions(runId)
```

## 9.2 One records cache

Table and JSON views consume the same records query.

Recommended contract:

```text
useInfiniteQuery or page-based query
canonical page size
shared normalized cache
```

Table view renders current pages.

JSON view renders loaded records and offers an explicit “load more” action.

Do not fetch the same records independently under:

```text
crawl-records-table
crawl-records-json
```

## 9.3 Log stream architecture

Create one `useRunLogStream` hook.

Responsibilities:

```text
open WebSocket
send cursor
validate incoming events
append to TanStack Query cache
reconnect with bounded exponential backoff
fall back to polling
stop at terminal run status
perform one terminal reconciliation fetch
```

The component must not own WebSocket handlers.

## 9.4 Remove terminal synchronization hacks

The backend should expose a canonical completion state such as:

```text
records_ready
result_version
finalized_at
record_count
```

Until that backend contract lands, isolate the current synchronization workaround in one hook with tests.

Do not keep a Query interval whose only purpose is repeatedly invoking other query refetch functions.

## 9.5 Stop reconstructing backend semantics

Remove browser-side calculation of:

```text
extraction verdict
canonical quality level
variant completeness
LLM repair usage
confidence
record count from competing sources
```

Display backend-provided:

```text
verdict
quality summary
metrics
lineage coverage
variant metrics
LLM/enrichment attribution
record count
processed URL count
duration
```

Client-only visual estimates may exist only when clearly labeled:

```text
“display estimate”
```

They may never replace persisted backend values.

## 9.6 Final run workspace structure

```text
features/run-workspace/
  page.tsx
  controller.ts
  api.ts
  queries.ts
  mutations.ts
  log-stream.ts
  record-columns.ts
  components/
    workspace-header.tsx
    summary.tsx
    output-tabs.tsx
    records-panel.tsx
    json-panel.tsx
    logs-panel.tsx
    learning-panel.tsx
    history-drawer.tsx
```

## 9.7 Remove Zustand

After the page is migrated:

```text
delete crawl-run-store.ts
remove zustand dependency
```

---

# 10. Records and variants UI

## 10.1 Render public records only

The default table and JSON panels use:

```text
record.data or the new canonical public record payload
```

They do not merge `raw_data` into public columns.

Raw evidence/provenance belongs in:

```text
record detail drawer
provenance panel
run trace
debug mode
```

## 10.2 Surface column descriptors

Create typed display descriptors:

```ts
type ColumnDescriptor = {
  key: string;
  label: string;
  kind: 'text' | 'url' | 'money' | 'image' | 'status' | 'list' | 'variants' | 'json';
  width?: number;
  priority: number;
};
```

Each surface has defaults:

```text
ecommerce listing
ecommerce detail
job listing
job detail
```

Unknown requested fields append after canonical columns.

Avoid heuristics spread across components such as many price/title/image aliases.

## 10.3 Variant presentation

Do not flatten variants into unreadable table cells.

Provide:

```text
variant count badge
selected variant summary
expandable variant panel
variant table with identity/options/offer/availability/image
lineage link where available
```

Large variant arrays must be virtualized or paged.

## 10.4 Table decision

Keep the custom virtualized table initially.

Remove unused `@tanstack/react-table`.

Consider `@tanstack/react-virtual` only if measurement shows the current windowing implementation is difficult to maintain or performs poorly.

---

# 11. Selector and domain-memory architecture

## 11.1 Align with backend CSS-only recipes

After backend endpoint migration:

```text
remove XPath from frontend types
remove regex selector editing
remove selector type dropdown
remove XPath/regex tests and source labels
remove client surface inference
default all new recipes to CSS
```

Preserve:

```text
manual CSS editing
test selector
preview extracted value
save to domain memory
enable/disable recipe
source-run provenance
LLM-assisted CSS suggestion
```

## 11.2 Explicit surface selection

The selector workflow should require one of the four surfaces.

Do not infer surface from:

```text
URL
expected field names
returned HTML
```

## 11.3 Preview security

Keep iframe scripts disabled.

Harden preview rendering:

```text
sanitize or rewrite script/form/base/meta-refresh content server-side
inject restrictive CSP into srcDoc
block navigation and form submission
keep referrerPolicy=no-referrer
do not add allow-scripts
consider a separate preview origin if active content is ever required
```

Review whether `allow-same-origin` is required for selector inspection. Remove it if the parent does not need DOM access.

## 11.4 Feature structure

```text
features/selectors/
  page.tsx
  schema.ts
  state.ts
  api.ts
  mutations.ts
  preview.tsx
  components/
    selector-request-card.tsx
    preview-card.tsx
    selector-rows.tsx
    selector-row-editor.tsx
```

---

# 12. Product intelligence, enrichment, and admin pages

Apply the same ownership rules.

## Product intelligence

Replace the mega-controller with:

```text
RHF/Zod configuration form
jobs query
job detail query
discover mutation
review mutation
local selection/filter reducer
pure grouping/scoring display helpers
```

Keep:

```text
SerpAPI/Google provider selection
allowed/excluded domains
candidate filters
history
selected URL batch crawl
JSON candidate detail
human review
```

Do not recompute backend match scores or confidence labels beyond pure display mapping.

## Data enrichment

Use:

```text
jobs query
job detail query
create mutation
typed enriched-product display
source record selection
```

Delete the orphaned `enrichment-utils.ts` after moving any uniquely useful price formatter to shared formatting.

## Admin LLM

Separate:

```text
provider catalog query
config list query
config form
connection-test mutation
cost-log query
```

Sensitive secret inputs must never be written to:

```text
URL
localStorage
telemetry
console logs
```

## Admin users

Use query/mutation modules and invalidate exact query keys after create/update/deactivate operations.

---

# 13. Design system and component ownership

## 13.1 Preserve useful primitives

Keep:

```text
Button
Input
Textarea
Card
Badge
Alert
Dialog
Dropdown
Toggle
Tooltip
Skeleton
Table primitives
```

Keep Radix Dialog.

Remove unused Radix Label and Select packages after verification.

## 13.2 Retire compatibility barrels

Gradually retire:

```text
components/ui/primitives.tsx
components/crawl/shared.tsx
```

Call sites import from real owners.

Barrels may exist only at feature/public boundaries and must not aggregate unrelated utilities.

## 13.3 Split `patterns.tsx` by cohesive responsibility

Target:

```text
shared/ui/layout/
  page-header.tsx
  section.tsx
  workspace-shell.tsx

shared/ui/navigation/
  tabs.tsx
  segmented-control.tsx

shared/ui/feedback/
  data-region.tsx
  empty-state.tsx
  loading-state.tsx

shared/ui/metrics/
  metric.tsx
  summary-chips.tsx
```

Do not create one file per ten-line component when components naturally belong together.

## 13.4 Replace top-bar ReactNode serialization

`PageHeader` currently serializes React nodes to detect changes before writing to top-bar state.

Replace it with one of:

```text
route metadata for static title/description
simple serializable PageHeaderConfig for dynamic actions
page-owned visible header instead of shell injection
```

Do not serialize arbitrary React elements as state signatures.

## 13.5 Tabs accessibility

Split two concepts:

### Tabs

For content panels:

```text
role=tablist
role=tab
role=tabpanel
aria-selected
keyboard Left/Right/Home/End
```

### Segmented control

For setting choices:

```text
button group
aria-pressed
```

The current `TabBar` should not represent both semantics.

---

# 14. CSS architecture

## 14.1 Global CSS ownership

Target:

```text
styles/tokens.css
styles/themes.css
styles/base.css
styles/utilities.css
```

`main.tsx` imports a small `styles/index.css`.

## 14.2 Co-locate feature styles

Feature-specific styles stay with:

```text
app shell
crawl config
run workspace/log terminal
records table
selector preview
```

Do not move every style into global CSS.

## 14.3 Tailwind policy

Retain Tailwind v4 and semantic tokens.

Continue blocking arbitrary raw token escapes where a semantic utility exists.

Permit documented exceptions for calculated CSS that cannot be represented cleanly.

## 14.4 Remove dead CSS safely

Delete reported unused classes only after:

```text
static search
render tests
Playwright smoke
visual comparison for main routes
```

Dynamic class composition must be considered before deletion.

---

# 15. Accessibility hardening

## Required changes

- re-enable `jsx-a11y/label-has-associated-control`;
- fix form primitives rather than suppressing the rule globally;
- implement correct Tabs keyboard behavior;
- use semantic `fieldset`/`legend` for option groups;
- ensure all icon buttons have accessible names;
- preserve focus when dialogs/drawers close;
- announce asynchronous form and mutation results;
- add `aria-live` to crawl progress and relevant error regions;
- ensure virtualized table rows remain understandable to screen readers;
- provide non-color status text;
- respect `prefers-reduced-motion`;
- verify contrast in both themes.

## Automated checks

Add axe-based Playwright checks for:

```text
login/register
dashboard
crawl configuration
run workspace
selectors
product intelligence
admin LLM
```

---

# 16. Performance architecture

## 16.1 Measure before changing chunk strategy

The Vite config manually groups:

```text
query
router
ui
vendor
vendor-other
```

Generate a build manifest and inspect compressed route chunks before changing this.

Manual chunking may reduce or increase initial cost depending on route use.

## 16.2 Bundle budgets

Recommended initial budgets:

```text
initial JS gzip                <= 220 KB
largest lazy route JS gzip     <= 180 KB
initial CSS gzip               <= 55 KB
single dependency contribution <= 80 KB gzip unless approved
```

Record the current baseline before enforcement.

## 16.3 Route loading

Keep route-level lazy loading.

Use native React `lazy`/React Router lazy modules.

Optionally prefetch a route module on navigation hover/focus after measuring benefit.

## 16.4 Expensive rendering

Optimize:

```text
large JSON output
variant lists
record tables
log groups
candidate groups
```

Rules:

```text
do not stringify large JSON unless JSON tab is active
do not derive columns by repeatedly scanning raw and public records
memoize pure transformed view models
paginate or virtualize large arrays
do not hold duplicate record copies in multiple caches
```

## 16.5 Images

Replace the fake Next image wrapper with:

```text
native img for bundled/static assets
RemoteImage component for extracted external images
```

`RemoteImage` may own:

```text
lazy loading
fallback
decoding=async
referrer policy
safe URL checks
object-fit
```

---

# 17. Frontend observability

## 17.1 Typed telemetry

Replace arbitrary telemetry names with a typed event map.

```ts
type FrontendEventMap = {
  crawl_launch_succeeded: {...};
  crawl_launch_failed: {...};
  run_socket_connected: {...};
  run_socket_fallback_started: {...};
  api_request_failed: {...};
  route_render_failed: {...};
};
```

## 17.2 Redaction

Never send:

```text
passwords
tokens
cookies
proxy credentials
LLM API keys
raw HTML
complete extracted records
full query strings containing user data
```

## 17.3 Operational metrics

Capture:

```text
route load duration
API latency/error by endpoint family
query retry count
mutation failure
WebSocket connect/reconnect/fallback
run terminal-sync mismatch
large JSON render time
records table row count/render cost
frontend exceptions
Core Web Vitals where meaningful
```

## 17.4 Error reporting

Add a production error reporter or backend telemetry endpoint supporting:

```text
message
stack fingerprint
route
release/version
user role, not PII
correlation/request ID
```

Frontend observability remains read-only and cannot change backend results.

---

# 18. Testing architecture

## 18.1 Test layers

### Unit

Pure functions:

```text
route parsing
surface mapping
dispatch building
record column descriptors
formatters
selector row transforms
query-key factories
```

### Component

```text
forms
dialogs
tabs
record variants
error/loading/empty states
```

### Feature integration with MSW

```text
crawl launch
domain profile application
run polling and terminal state
WebSocket fallback
selector save/test
product discovery
enrichment creation
admin mutations
```

### Playwright

Critical workflows:

```text
login
create commerce listing crawl
create ecommerce detail crawl
open active run
receive logs or polling fallback
inspect records and variants
export
selector CSS workflow
product intelligence prefill
data enrichment prefill
admin LLM configuration
```

## 18.2 API contract tests

CI generates OpenAPI TypeScript types and fails on drift.

Add representative runtime fixtures for:

```text
CrawlRun
canonical record
run observability
selector recipe
Product Intelligence job
Data Enrichment job
```

## 18.3 Visual and accessibility checks

Use targeted screenshot tests for:

```text
app shell
crawl setup
run table
log terminal
selector editor
dark theme
```

Use axe on critical routes.

## 18.4 Avoid implementation-coupled tests

Tests should assert behavior and public contracts, not internal hook arrangement.

Large tests should be split by user scenario rather than by private component.

---

# 19. Dead code and dependency plan

## Delete immediately after verification

```text
app/data-enrichment/enrichment-utils.ts
confirmed unused exports
confirmed unused global CSS classes
@radix-ui/react-label
@radix-ui/react-select
@tanstack/react-table
recharts
```

## Delete after architecture migration

```text
zustand
Next-style routing/dynamic/image compatibility modules
XPath and regex selector frontend types/UI
stale ReviewPayload selector fields
legacy client-side quality/verdict helpers
crawl shared barrel
UI primitives compatibility barrel
```

## Add development tooling

Recommended:

```text
openapi-typescript
knip
bundle analyzer/report tool
axe Playwright integration
```

`knip` should report dead files/exports/dependencies in CI, with explicit exceptions for:

```text
Vite entries
Playwright configuration
generated files
script entry points
```

---

# 20. Architecture enforcement

Replace the current limited line-count script with AST/import-boundary checks.

CI must fail if:

```text
a feature deep-imports another feature
shared imports a feature
a component calls fetch directly
an API path is declared outside feature API modules
a query key is constructed outside query-key factories
a mutation relies on automatic retry
a Next.js compatibility import is introduced
a global store contains page-local state
frontend recomputes canonical backend verdict/quality
XPath or regex selector fields return after migration
raw_data becomes a default public-table source
a form uses multiple competing state owners
a route lacks defined access policy
a dialog uses browser alert/confirm
a page component exceeds 350 LOC without an approved exception
a controller/hook exceeds 250 LOC without an approved exception
```

File-size gates are secondary to ownership gates.

---

# 21. Exact implementation sequence

Execute in this order.

## PR 0 — Freeze baselines

- record current LOC/file metrics;
- save Vite build manifest and gzip sizes;
- run and save critical Playwright screenshots;
- inventory current API endpoints and query keys;
- add the revised frontend architecture plan;
- create feature-boundary architecture tests in warning mode.

**Gate:** current critical user flows are reproducible before refactoring.

---

## PR 1 — Verified dead-code cleanup

- delete orphaned enrichment utility;
- remove unused exports;
- remove unused CSS;
- remove four confirmed unused production dependencies;
- add Knip with reviewed exceptions.

**Gate:** typecheck, lint, Vitest, build, and Playwright smoke pass.

---

## PR 2 — Safe API transport

- split transport errors and request helpers;
- add AbortSignal support;
- disable automatic mutation retries;
- make GET retry policy explicit;
- add request/correlation ID support;
- remove redundant base-URL fallback loops;
- add transport tests for 401/404/429/5xx/network failures.

**Gate:** a failed create/update request is never automatically repeated.

---

## PR 3 — Backend-generated contracts and feature APIs

- generate OpenAPI TypeScript declarations;
- introduce exact enums;
- split monolithic API object into feature API modules;
- create query-key factories;
- migrate one feature at a time;
- remove stale review and selector contract fields.

**Gate:** CI detects backend/frontend contract drift.

---

## PR 4 — Native Vite/React Router architecture

- create route registry;
- derive sidebar navigation and role policy from it;
- add `RequireSession` and `RequireAdmin`;
- add root and route error boundaries;
- migrate navigation to React Router;
- remove fake dynamic/navigation/image wrappers;
- consolidate code under `src/`.

**Gate:** all routes, redirects, lazy loading, auth and admin access pass.

---

## PR 5 — Crawl configuration state ownership

- move all editable config into RHF;
- use field arrays for manual fields;
- use React Router search params;
- introduce domain-profile and selector-memory query hooks;
- introduce mutation hooks;
- remove render-time dispatch/ref synchronization;
- extract presentation sections.

**Gate:** saved profile application preserves explicit dirty edits and no render-time state mutation remains.

---

## PR 6 — Run workspace resource model

- create run query and records query owners;
- merge table/JSON records caches;
- create log-stream hook with WS/reconnect/poll fallback;
- isolate temporary backend reconciliation;
- add mutation hooks for run actions and recipe actions;
- move view state local;
- remove Zustand.

**Gate:** one records resource and one logs resource exist per run.

---

## PR 7 — Canonical run and record rendering

- consume backend verdict, quality and metrics;
- remove client semantic recomputation;
- create surface column descriptors;
- public records only in table/JSON;
- add provenance/debug drawer;
- add structured variant viewer;
- refactor log terminal around canonical run events with raw-log fallback.

**Gate:** browser display agrees with canonical backend result and variants are inspectable.

---

## PR 8 — CSS-only selector workflow

- require explicit surface;
- remove XPath/regex UI and contracts after backend compatibility;
- harden iframe preview;
- split selector state/actions/components;
- preserve CSS suggestion/test/save/domain-memory workflows.

**Gate:** selector tool creates and saves only valid CSS recipes.

---

## PR 9 — Operator feature refactors

Migrate:

```text
Product Intelligence
Data Enrichment
Admin LLM
Admin Users
Runs
Jobs
Dashboard
Run Trace
Domain Memory
```

to:

```text
feature API
query options
mutation hooks
local form/view state
small presentation components
```

**Gate:** no feature page owns raw endpoint paths or duplicate query logic.

---

## PR 10 — Design system and CSS ownership

- split UI patterns by semantic group;
- remove compatibility barrels;
- replace top-bar ReactNode serialization;
- split Tabs and SegmentedControl;
- move global CSS into tokens/themes/base/utilities;
- co-locate feature styles;
- re-enable label accessibility rule.

**Gate:** component behavior and visual snapshots remain stable.

---

## PR 11 — Performance and observability

- establish bundle budgets;
- review manual chunking using measured output;
- add typed telemetry and redaction;
- add route/API/WS/render metrics;
- optimize large JSON, records, logs and variants;
- add accessible reduced-motion behavior.

**Gate:** bundle budgets and route performance tests pass.

---

## PR 12 — Final hardening and deletion

- enable architecture checks as errors;
- remove remaining wrappers/barrels/stale types;
- remove temporary compatibility aliases;
- update frontend architecture, codebase map and invariants;
- run full Vitest, MSW, Playwright, axe, bundle and contract gates.

---

# 22. Quantitative guardrails

The goal is not maximum file count or minimum LOC. The goal is clear ownership.

Recommended final gates:

```text
page-view component       <= 300 LOC
workflow controller/hook  <= 250 LOC
shared UI module          <= 300 LOC
API feature module        <= 250 LOC
no file                   > 500 LOC without explicit exception
```

Expected structural outcomes:

```text
0 page-local Zustand stores
0 fake Next.js wrappers
0 automatic mutation retries
0 XPath/regex selector UI
0 ad hoc query keys
0 default public rendering from raw_data
0 client-owned canonical verdict or quality
0 feature-to-feature deep imports
```

Dependency outcome:

```text
remove 4 currently unused dependencies immediately
remove Zustand after run-workspace migration
add only focused development tooling
```

Performance outcome:

```text
one records cache per run
one log stream owner per run
stale queries abortable
route-level code splitting retained
large data views paged or virtualized
bundle budgets enforced
```

---

# 23. Definition of done

The frontend optimization is complete only when:

- the backend OpenAPI contract is the frontend type source;
- mutation requests are not retried automatically;
- every server resource has one TanStack Query owner;
- every editable workflow has one form-state owner;
- navigable UI state lives in the URL;
- page-local UI state is not global;
- all routes and navigation come from one registry;
- the Vite app no longer carries fake Next.js abstractions;
- run table and JSON use one records resource;
- WebSocket and polling are owned by one log-stream hook;
- the UI displays canonical backend verdict, quality, metrics and lineage;
- records and variants render from public typed payloads;
- selector recipes are explicit-surface and CSS-only;
- feature pages use feature API/query/mutation modules;
- design-system components have semantic ownership;
- accessibility and bundle budgets are enforced;
- dead files, exports, CSS, dependencies and compatibility layers are removed;
- critical operator workflows pass Playwright and accessibility tests.

---

# 24. Agent execution directive

> Implement this frontend plan in the stated PR order. Preserve React, Vite, React Router, TanStack Query, React Hook Form, Zod, Tailwind, Radix Dialog, the WebSocket-plus-polling fallback capability, custom virtualized records table, selector preview/testing, domain memory, Product Intelligence, Data Enrichment, Run Trace and admin workflows. Fix ownership before splitting JSX. Make TanStack Query the sole server-state owner, React Hook Form the sole editable-form owner, URL params the owner of navigable state, and local state the owner of temporary view state. Remove unsafe mutation retries, generate types from FastAPI OpenAPI, split API access by feature, remove fake Next.js wrappers, consolidate run records and logs, stop recomputing backend verdict and quality, migrate selectors to explicit-surface CSS-only recipes, remove page-local Zustand, retire broad compatibility barrels, and enforce feature boundaries, accessibility, contract, bundle and end-to-end gates.
