Frontend rendering audit

I found no deterministic P0 infinite-render loop and no remaining active Next.js runtime dependency. The strongest code-level explanations for the reported delays and hangs are:

Product Intelligence can mount thousands of complex cards and images.
The live log terminal repeatedly processes and renders up to 2,000 logs.
Crawl table virtualization assumes 40px rows while image rows are at least 46px.
/crawl has a sequential, two-chunk lazy-loading waterfall.
“Load more” replaces the record query with a new growing-limit query instead of appending pages.

This was a symbol-level static audit. Runtime profiling would quantify their relative contribution, but the problems below are directly present in the code.

A. Rendering blockers and hangs
A1. Collapsed Product Intelligence groups still mount every card and image · P1

Location:
frontend/app/product-intelligence/product-intelligence-results.tsx:ResultsBody
frontend/app/product-intelligence/product-intelligence-candidate-card.tsx:CandidateGroupSection
frontend/app/product-intelligence/product-intelligence-candidate-card.tsx:CandidateCard
frontend/app/product-intelligence/product-intelligence-components.tsx:ExternalCandidateImage

Evidence: ResultsBody maps every candidate group. Each CandidateGroupSection renders a <details> element, but its candidate grid is always mounted:

{group.candidates.map((candidate) => (
  <CandidateCard ... />
))}

Collapsing a native <details> only hides its content; it does not avoid constructing or mounting the children. Every card also mounts an external <img> without loading="lazy" or decoding="async".

The configured UI limits allow up to 500 sources and 25 candidates per source, giving a theoretical upper bound of 12,500 cards.

Root cause: A server-rendered or paged mental model was carried into a client-only SPA. The complete result hierarchy is materialized in the browser, even when most groups are collapsed.

Fix: Only mount a group’s cards after that group is opened. Then add either pagination or windowing for groups/cards. Add loading="lazy" and decoding="async" to candidate images. A minimal first change is controlled expansion state:

{expanded ? <CandidateGrid candidates={group.candidates} /> : null}
A2. Live terminal does full-list processing on every log and every second · P1

Location:
frontend/components/crawl/use-run-log-stream.ts:useRunLogStream
frontend/components/crawl/shared.tsx:mergeLogs
frontend/components/crawl/use-log-terminal-state.ts:useLogTerminalState
frontend/components/crawl/log-terminal.tsx:LogTerminal
frontend/lib/constants/crawl-defaults.ts:CRAWL_DEFAULTS

Evidence:

The terminal retains up to MAX_LIVE_LOGS: 2000.
Every WebSocket message calls mergeLogs, which reconstructs a Map, sorts all logs, and slices the result.
The merged query/socket list is then merged and sorted again in a separate useMemo.
useLogTerminalState updates nowMs every second while live.
LogTerminal renders every group without virtualization.
During each group render, it recomputes payloads, field coverage, confidence, duration, reverse-searches logs and calls buildExpandedRows.
buildExpandedRows runs even for collapsed groups; only its eventual DOM rendering is conditional.

Root cause: Streaming data is treated as a replace-and-rederive collection. A one-second clock is also placed high enough to rerender the entire terminal.

Fix: Use an incremental append/deduplicate ring buffer rather than sorting the complete list per message. Memoize each group row, compute expanded rows only inside the expanded branch, isolate the live duration clock to the active row, and virtualize the outer group list.

A3. Virtual row size is inconsistent with thumbnail row size · P1

Location:
frontend/components/crawl/records-table.tsx:RecordsTable
frontend/components/crawl/record-thumbnail.tsx:RecordThumbnail
frontend/app/globals.css:--table-row-height

Evidence: RecordsTable performs fixed-height virtualization using:

const rowHeightPx = 40;

The global row height is also 40px, but RecordThumbnail renders a 46px × 46px container. A table row containing that thumbnail cannot remain 40px tall.

The virtualizer still calculates start indexes and top/bottom spacers using 40px.

Root cause: The image treatment changed without updating the manual virtualizer’s fixed-size contract.

Fix: Make the thumbnail no taller than the actual row height, or increase both the CSS and virtualizer height to the same value. A robust long-term fix is a virtualizer that measures rows rather than manually calculating spacers from a hard-coded height.

This mismatch can directly produce scroll drift, row jumps, premature row replacement and apparent missing rows.

A4. /crawl has a sequential nested lazy-loading waterfall · P1

Location:
frontend/src/app/route-registry.ts:appRoutes
frontend/src/app/app.tsx:routeObject
frontend/app/crawl/page-view.tsx:CrawlPage
frontend/app/crawl/page-view.tsx:CrawlConfigScreen
frontend/app/crawl/page-view.tsx:CrawlRunScreen

Evidence: React Router first lazy-loads app/crawl/page-view.tsx. Only after that module executes does React.lazy request either:

crawl-config-screen, or
crawl-run-screen.

The user can consequently see:

Router-level fallback.
Crawl-level 520px Suspense skeleton.
Actual screen.

Root cause: Route-level Vite code splitting was layered on top of a second feature-level lazy boundary. This resembles nested App Router loading boundaries but creates a network waterfall in a client SPA.

Fix: Keep only one asynchronous boundary. The smallest architectural change is to load the tiny crawl route wrapper eagerly and leave the two heavy screens lazy. Alternatively, create distinct lazy React Router routes for configuration and run detail.

A5. “Load more” creates a new query and refetches the complete prefix · P1

Location:
frontend/components/crawl/use-run-records.ts:useRunRecords
frontend/components/crawl/crawl-terminal-tab-content.tsx:CrawlTerminalTabContent
frontend/components/crawl/run-records-output.tsx:RunTableOutput
frontend/src/api/query-keys.ts:queryKeys.runs.tableRecords

Evidence: The table limit grows with tablePage:

const tableRecordsLimit = TABLE_PAGE_SIZE * 4 * tablePage;

That limit is embedded in the query key. Increasing the page therefore creates a new cache entry and fetches page 1 again with a larger limit. There is no placeholderData: keepPreviousData, so the new query can temporarily expose no rows and replace the table with loading UI.

The same growing-limit pattern is used for JSON records.

Root cause: Pagination is modeled as “refetch everything up to N” rather than append-only pages.

Fix: Use useInfiniteQuery with stable pages, or store each page independently and flatten them. As a minimal mitigation, use placeholderData: keepPreviousData so the current rows remain visible while the larger response loads.

A6. Data Enrichment repeatedly rerenders up to 500 sidebar records during polling · P1

Location:
frontend/app/data-enrichment/page-view.tsx:DataEnrichmentPage
frontend/app/data-enrichment/page-view.tsx:EnrichedProductSidebar

Evidence:

Job history polls every four seconds regardless of whether the drawer is open.
Running job details poll every 2.5 seconds.
Each render executes multiple some, find and filter passes over products.
EnrichedProductSidebar maps every product into a button.
Job creation allows max_source_records: 500.
Sidebar rows are neither memoized nor virtualized.

During an active job, both query updates can cause complete sidebar and detail rerenders.

Root cause: Polling updates are propagated through one large page component, with all derived list work and list rendering repeated each time.

Fix: Stop polling the jobs list unless history is visible or the list contains running jobs. Use query select or useMemo for product summaries, memoize sidebar rows, and virtualize the selector if hundreds of products are expected.

A7. Product Intelligence shows a false empty state during its serial initial queries · P2

Location:
frontend/app/product-intelligence/use-product-intelligence.ts:useProductIntelligence
frontend/app/product-intelligence/product-intelligence-results.tsx:ResultsBody

Evidence: Without a prefill, the feature must first fetch jobsData to determine defaultJobId. Only then is the detail query enabled. Neither jobs-loading nor detail-loading state is exposed to ResultsBody.

Until the second query completes, the UI can render “No discovery results yet.”

Root cause: A two-request client waterfall has no corresponding loading state.

Fix: Expose isJobsLoading, isDetailLoading and isDetailFetching in the controller. Render the table loading state until latest-job resolution and detail loading have settled. An API returning latest job plus detail would remove the serial dependency entirely.

A8. Selector preview can synchronously parse an unbounded HTML document · P2

Location:
frontend/app/selectors/use-selectors-workspace.ts:loadPageAndSuggestions
frontend/app/selectors/page-view.tsx:PagePreviewCard

Evidence: The complete result of api.getPreviewHtml() is stored in reducer state and immediately supplied to an iframe through srcDoc. There is no size cap, truncation or user-controlled mount boundary.

A large captured page can require substantial HTML parsing, styling and layout in the browser.

Root cause: Server-fetched page content is treated as a lightweight preview value, although srcDoc creates an additional full document.

Fix: Enforce a response-size limit, strip unnecessary scripts/styles server-side, and mount the iframe only after an explicit “Open preview” action or an idle/deferred transition.

B. Table ↔ drawer state synchronization
B1. Product Intelligence memoization is defeated by reconstructed server-derived objects · P1

Location:
frontend/app/product-intelligence/use-product-intelligence.ts:useProductIntelligence
frontend/app/product-intelligence/page-view.tsx:ProductIntelligenceContent
frontend/app/product-intelligence/product-intelligence-candidate-card.tsx:CandidateCard

Evidence:

const discovery =
  discoveryOverride ?? (detailData ? detailToDiscovery(detailData) : null);

detailToDiscovery constructs a new discovery object on every render. visibleSourceRecords also calls .map() during every detail-backed render.

The memos for filtered candidates, grouped candidates, confidence distribution and selected-domain summary depend on those unstable identities. The hook also returns a new monolithic controller object with newly created functions.

Every CandidateCard receives the complete controller.

Opening history, opening settings, changing a form field or opening the JSON modal can therefore invalidate the entire candidate tree.

Root cause: Server state and UI state share one broad controller, while server-derived data is reconstructed outside stable memo boundaries.

Fix: Memoize discovery and visibleSourceRecords from their actual query inputs. Use stable callbacks and pass cards only the fields they need: candidate, selected boolean, onToggle, and onOpenJson. Use a Set<string> for selected URL membership.

B2. Data Enrichment’s active job is derived continuously from a changing history list · P1

Location:
frontend/app/data-enrichment/page-view.tsx:DataEnrichmentPage
frontend/app/data-enrichment/page-view.tsx:dataEnrichmentReducer

Evidence:

const defaultJobId = sourceRecords.length ? null : (jobsData?.[0]?.id ?? null);
const resolvedJobId = activeJobId ?? defaultJobId;

While activeJobId is null, every jobs-list poll can change the selected detail if the first list item changes. Selection is therefore not an explicit user/workspace state.

Additionally, historyJobSelected updates activeJobId but leaves selectedProductId from the previous job intact.

Root cause: The history drawer and detail workspace do not have a durable active-job identity. A derived default is being used as live selection state.

Fix: Set the initial active job once when the first jobs response arrives, preferably in the route query string. When changing jobs, reset selectedProductId to null. The drawer and detail pane should both read the same explicit active job ID.

B3. Selector Tool mutations leave Crawl Studio’s selector query cache stale · P1

Location:
frontend/app/selectors/use-selectors-workspace.ts:saveAcceptedRows
frontend/components/crawl/use-crawl-domain-memory.ts
frontend/components/crawl/use-crawl-field-actions.ts
frontend/src/api/query-keys.ts:queryKeys.selectors

Evidence: The Selector Tool imperatively reads and saves selectors but never accesses QueryClient and never invalidates the selector query key.

Crawl Studio separately reads the same server resource with:

queryKeys.selectors.list({ domain, surface })

Selector changes made in the Selector Tool can consequently leave Crawl Studio displaying cached old selectors until that cache becomes stale or is otherwise invalidated.

Root cause: Two screens use different state-management models for the same server resource: local reducer state in one feature and TanStack Query in another.

Fix: After save/update/delete, invalidate the exact selector list key. Prefer moving Selector Tool reads and writes to TanStack Query so all selector consumers share the same cache.

B4. Domain Memory mirrors six server datasets into local component state · P1

Location:
frontend/components/selectors/domain-memory/use-domain-memory-workspace.ts:useDomainMemoryWorkspace
frontend/components/selectors/domain-memory/use-selector-record-actions.ts:useSelectorRecordActions
frontend/src/api/query-keys.ts:queryKeys.domainMemory

Evidence: The workspace stores separate local copies of:

selectors,
selector summaries,
profiles,
cookies,
feedback,
knowledge sites,
completed runs.

loadWorkspace performs six requests concurrently and then a seventh selector request sequentially. Mutations manually patch some local arrays. Saving a profile reloads the entire workspace.

A queryKeys.domainMemory family exists, but the Domain Memory feature does not use it.

Root cause: Server state is duplicated in local React state. This prevents cache reuse, targeted invalidation and cross-feature synchronization.

Fix: Move each server dataset to useQuery/useQueries. Build groupedWorkspaces as derived query data. Mutations should update or invalidate only the affected domain/surface keys rather than rerunning the complete seven-request load.

B5. Inline selection handlers defeat the memoized crawl table · P2

Location:
frontend/components/crawl/crawl-terminal-tab-content.tsx:CrawlTerminalTabContent
frontend/components/crawl/run-records-output.tsx:RunTableOutput
frontend/components/crawl/records-table.tsx:RecordsTable

Evidence: RecordsTable is wrapped in memo, but its parent creates new onSelectAll and onToggleRow functions during every render.

Changes unrelated to records—such as opening history or live workspace state updates—can therefore rerender the table despite unchanged records and columns.

Root cause: The component was memoized without stabilizing the callback props crossing its boundary.

Fix: Define selection operations as stable callbacks in useRunRecordSelection or CrawlRunWorkspace, and pass those callbacks through unchanged.

State flows that are already correctly aligned
frontend/components/crawl/use-run-history.ts:useRunHistory uses TanStack Query and seeds the same run-detail cache used by the active run.
Product Intelligence history items and active detail both originate from the jobs/detail queries; the main problem is render breadth and unstable derived identities, not a separate drawer-side server copy.
RecordsTable already performs row windowing. The issue is the incorrect fixed row size, not a complete absence of virtualization.
C. Migration leftovers
C1. Dead Next.js App Router loading file remains in the Vite source tree · P2

Location:
frontend/app/runs/[run_id]/loading.tsx:LoadingRunDetailPage

Evidence: The file’s own comment says it is a Next.js App Router loading UI invoked by filesystem routing. Serena found no references to the component.

The real SPA route is:

frontend/src/app/app.tsx:RunDetailRedirect

which handles /runs/:run_id and redirects to /crawl?run_id=....

Root cause: The [run_id] filesystem route survived the migration even though React Router no longer discovers route files.

Fix: Delete app/runs/[run_id]/loading.tsx and remove the empty [run_id] directory.

C2. Next-shaped route naming is harmless at runtime but obscures route ownership · P2

Location:
frontend/src/app/route-registry.ts:appRoutes

Evidence: React Router explicitly imports every page-view.tsx; Vite does not interpret app/, [run_id], page-view.tsx or loading.tsx specially.

This allowed the dead [run_id]/loading.tsx file to look active despite being unreachable.

Root cause: The migration changed the router but retained the filesystem vocabulary of the old router.

Fix: Gradually move route entry modules into a clearly SPA-owned directory such as src/routes/, or at minimum document that route-registry.ts is the sole route authority and add a policy check rejecting App Router filenames outside that registry.

C3. No active Next.js runtime imports or RSC directives were found

The audit found no remaining:

next/image
next/link
next/navigation
other next/* imports
"use client" or "use server"
getServerSideProps
getStaticProps
getInitialProps
next package dependency

The migration problem is therefore architectural residue, not an accidentally bundled Next runtime.

D. Toolchain and build debt
D1. Manual chunking collapses route-specific dependencies into large shared chunks · P1

Location:
frontend/vite.config.ts:build.rollupOptions.output.manualChunks

Evidence: Every unclassified dependency is forced into vendor-other. All Radix and Lucide modules are forced into one ui chunk.

This bypasses Rollup’s natural graph-based chunking. A route needing one otherwise isolated dependency can pull the shared catch-all chunk containing dependencies used throughout unrelated routes.

The chunkSizeWarningLimit is also raised to 500KB, making oversized shared chunks less visible.

Root cause: Manual chunk rules attempt to optimize a SPA before measuring its actual dependency graph. They work against the route-level dynamic imports.

Fix: Remove manualChunks and inspect the default production output first. Reintroduce only measured, stable splits—normally React/router/query—not a catch-all vendor-other, and do not force the complete icon layer into one chunk.

D2. Run History eagerly preloads both crawl route layers after its query completes · P2

Location:
frontend/app/runs/page-view.tsx:preloadCrawlRunRoute
frontend/app/runs/page-view.tsx:RunsPage

Evidence: Once any run rows arrive, the page imports both:

app/crawl/page-view
components/crawl/crawl-run-screen

This happens without hover, focus or navigation intent.

Root cause: Preloading was added to hide the nested lazy waterfall rather than removing the waterfall itself.

Fix: First remove the nested route split. Then prefetch the one remaining chunk on row/link hover or focus, or during requestIdleCallback when the network is idle.

D3. Architecture enforcement currently locks in the nested lazy design · P2

Location:
frontend/scripts/check-crawl-architecture.mjs:dynamicallyImportsHeavyCrawlScreens

Evidence: The policy explicitly fails unless app/crawl/page-view.tsx dynamically imports both crawl screens. It does not account for the wrapper already being a lazy React Router route.

Root cause: The policy checks that code splitting exists, but not where the split boundary belongs or whether it creates sequential requests.

Fix: Change the policy to enforce a single asynchronous boundary per route path and prevent heavy config/run screens from entering the initial application chunk.

D4. Vite plugin typing is suppressed instead of resolved · P2

Location:
frontend/vite.config.ts:plugins

Evidence:

plugins: react() as unknown as PluginOption[]

The double cast hides a configuration or package-type incompatibility between vite-plus and @vitejs/plugin-react.

Root cause: Migration compatibility was addressed through type suppression.

Fix: Use the exact plugin type expected by the installed vite-plus version or update compatible package versions. Avoid casting a single plugin object to an array through unknown.

Toolchain checks that are clean
All package scripts use vp.
packageManager is pnpm@11.9.0.
pnpm-lock.yaml exists.
No npm, npx or package-lock.json remnants were found.
There is no custom optimizeDeps configuration causing unnecessary eager dependency scanning.
components/ui/primitives.tsx is an ESM re-export barrel; the audit did not find evidence that this barrel alone is breaking tree-shaking.
E. Design and UX debt
E1. History, settings and JSON overlays bypass the existing accessible dialog system · P2

Location:
frontend/components/ui/history-drawer.tsx:HistoryDrawer
frontend/app/product-intelligence/product-intelligence-settings-drawer.tsx:SettingsDrawer
frontend/app/product-intelligence/product-intelligence-components.tsx:JsonModal

Evidence: These components use fixed <div> overlays and manually attach an Escape listener. They do not provide a complete dialog contract:

no role="dialog"
no aria-modal
no focus trap
no initial focus
no focus restoration
no consistent body scroll lock
no labelled dialog relationship

Other application dialogs already have focus trapping and restoration logic, and Radix Dialog is installed.

Root cause: Drawers and modals were implemented independently instead of through one shared overlay primitive.

Fix: Build one Radix-backed Drawer and one shared Dialog primitive, then migrate all three components.

E2. Records table has two independent column-layout systems · P2

Location:
frontend/components/crawl/records-table.tsx:RecordsTable
frontend/components/ui/table.tsx:TableHead

Evidence: The record header is a separate sticky flex row, while the body uses a native table and <colgroup>. Width and sticky-position calculations are duplicated through headerCellStyle, fixedColumnStyle and stickyBodyStyle.

Root cause: The custom sticky/virtualized implementation was layered around the shared table primitive instead of owning one unified grid layout.

Fix: Use one CSS grid definition for both header and virtual rows, or retain a native table with a real <thead>. Define column widths once and share the resulting grid template.

E3. Jobs table contains nested horizontal scroll containers · P3

Location:
frontend/app/jobs/page-view.tsx:JobsPage
frontend/components/ui/table.tsx:Table

Evidence: JobsPage wraps Table in an overflow-x-auto container. Table itself always creates a relative w-full overflow-auto wrapper.

Root cause: Page-specific table framing duplicates behavior already owned by the table primitive.

Fix: Remove the outer overflow container or add an explicit unwrapped mode to Table.

E4. Sticky blurred top bar adds repaint cost during data-heavy scrolling · P2

Location:
frontend/components/layout/app-shell.module.css:.app-topbar

Evidence: The sticky top bar applies:

backdrop-filter: blur(14px);

Sticky backdrop filters require recompositing the content moving underneath them. This is most noticeable on virtual tables, image grids and the live terminal.

Root cause: A decorative shell effect is applied globally, including performance-sensitive workspaces.

Fix: Use an opaque or near-opaque header background without backdrop blur on application/data screens. At minimum, disable the filter under reduced-motion/performance preferences.

E5. Top-bar synchronization produces an extra synchronous shell render · P2

Location:
frontend/components/ui/patterns/page-header.tsx:PageHeader
frontend/components/layout/top-bar-context.tsx:TopBarProvider

Evidence: PageHeader recursively computes a signature for its React-node actions, then runs a useLayoutEffect with both signature and the raw actions object as dependencies.

Most pages construct a new actions element every render. The effect calls setHeader, which notifies all top-bar listeners without checking whether the semantic header value changed.

On polling/live pages this can cause an additional shell render after every page render and before paint.

Root cause: Page-owned React nodes are synchronized into an external shell store by identity rather than stable data.

Fix: Compare the semantic signature against the previous stored signature before notifying. Remove raw actions identity from the effect dependency or require memoized/stable top-bar action definitions.

Fix-first ranking

Ranked by expected rendering improvement per unit of effort:

Mount Product Intelligence candidate grids only when expanded; lazy-load images.
Immediate reduction in DOM size, image requests and card rendering.
Stop live terminal full-list work.
Incrementally append logs, compute expanded rows only for the expanded group, then virtualize groups.
Align crawl virtual row height with the 46px thumbnail.
Small change that can eliminate scroll drift and incorrect window calculations.
Remove the /crawl nested lazy waterfall.
Make the route wrapper eager or define direct route-level lazy screens.
Replace growing-limit record queries with page append semantics.
At minimum add keepPreviousData; preferably use useInfiniteQuery.
Memoize Product Intelligence server-derived objects and narrow card props.
Prevent history/settings/modal state from rerendering the entire result set.
Reduce Data Enrichment polling breadth and virtualize/memoize its sidebar.
Poll history conditionally and isolate detail updates from the full page.
Unify selector and domain-memory server state under TanStack Query.
Add exact cache invalidation after Selector Tool mutations and remove broad local mirrors.
Remove the vendor-other and all-icons ui manual chunks.
Let Vite/Rollup produce route-aware chunks, then optimize from measured output.
Guard PageHeader store updates by semantic equality.
Prevent the extra synchronous shell render on every polling or live update.