# CrawlerAI Frontend — Optimization Opportunities

**Current state:** 26,204 LOC across 147 files. The 13 largest files (500+ lines) account for 11,822 lines — **45% of the total**.

Three parallel analyses were conducted: large file bloat, code duplication, and dead code.

---

## Phase 1 — Quick Wins (Low effort, immediate impact)

### 1.1 Delete dead code (~300+ lines + 4 npm packages)

**Unused file (delete entirely):**
- `app/data-enrichment/enrichment-utils.ts` (111 lines) — orphaned, never imported, contains duplicate `formatPrice`

**Unused exports (remove from source):**
- `formatNowHms`, `formatNextRun`, `formatSeconds` — in `lib/format/`
- `syntaxHighlightJson` — in `lib/ui/syntax.ts`
- `cellDisplayForRecord`, `recordHasValue` — in `lib/crawl/`
- `runsStatusDot`, `dashboardStatusDotColor`, `runExecutionDot` — in `lib/ui/status.ts`
- `isThenable` — in `lib/utils.ts`
- `StatCard`, `MetricGrid`, `MetricSkeleton` — in `components/ui/patterns.tsx`

**Unused CSS classes (remove from `app/globals.css`):**
- `.code-block`, `.field-error`, `.field-label-required`, `.filter-toolbar`
- `.log-entry-animate`, `.metric-icon-tile`, `.metric-pulse-accent`, `.metric-stripe`
- `.pulse-dot`, `.ring-glow`, `.segmented-root`, `.table-surface-flat`
- `.tooltip-surface`, `.workspace-tab`, `.type-display`, `.type-heading-2`

**Unused npm dependencies (remove from `package.json`):**
- `@radix-ui/react-label`, `@radix-ui/react-select`
- `@tanstack/react-table`, `recharts`

### 1.2 De-duplicate copy-pasted functions

| What | Location A | Location B | Action |
|------|-----------|-----------|--------|
| `defaultRunProfile()` / `cloneRunProfile()` (~50 lines, identical) | `crawl-config-logic.ts:79` | `domain-memory/utils.ts:54` | Extract to shared module |
| `formatJobType()` / `formatRunType()` (~16 lines, identical) | `jobs/page-view.tsx:214` | `runs/page-view.tsx:401` | Extract to `lib/format/` |
| `surfaceLabel()` | `crawl-config-logic.ts` | `domain-memory/utils.ts` | Extract to shared module |
| `parseOptionalClampedNumber()` | `crawl-config-logic.ts` | `domain-memory/utils.ts` | Extract to shared module |
| `ActionButton` component | `components/crawl/shared.tsx` | `jobs/page-view.tsx` | Import from shared.tsx |

---

## Phase 2 — High-Impact Refactors (Medium effort)

### 2.1 Break up `crawl-config-screen.tsx` (1,428 → ~300 lines)
The biggest "god component." Extract:
- `TargetUrlCard.tsx`, `CrawlSettingsCard.tsx`, `FieldConfigCard.tsx`, `AdvancedSettingsPanel.tsx` (sub-components)
- `crawl-config-effects.ts` (URL sync, prefill, profile loading hooks)
- `crawl-config-actions.ts` (startCrawl, generateFieldSelectors, saveToDomainMemory)
- **~1,100 lines extractable**

### 2.2 Break up `crawl-run-screen.tsx` (1,298 → ~500 lines)
Extract:
- `use-run-websocket.ts` (WebSocket lifecycle hook)
- `use-run-effects.ts` (polling, scroll tracking)
- `crawl-run-actions.ts` (downloadExport, batch crawl, run control)
- `RunWorkspaceHeader`, `RunOutputTable`, `RunOutputJson`, `RunOutputLogs`, `RunLearningPanel` (sub-components)
- **~800 lines extractable**

### 2.3 Split `app/globals.css` (1,677 → ~900 lines)
Extract ~750 lines into:
- `styles/typography.css`, `styles/buttons.css`, `styles/forms.css`
- `styles/layout.css`, `styles/alerts.css`, `styles/terminal.css`
- `styles/tables.css`, `styles/skeleton.css`, `styles/animations.css`

### 2.4 Slim down `log-terminal.tsx` (1,089 → ~500 lines)
- Move ~370 lines of inline utility functions to `log-terminal-utils.ts`
- Consolidate `getLogIcon` + `getLogIconStyle` (near-duplicate keyword matching)
- Extract `LogTerminalHeader`, `LogGroupRow`, `LogExpandedRow`, `LogPeekPanel` sub-components

---

## Phase 3 — Structural Improvements (Higher effort, longer term)

### 3.1 Split `app/selectors/page-view.tsx` (888 → ~250 lines)
- Extract reducer/state to `selector-page-state.ts`
- Move factories/helpers to `selector-page-utils.ts` (partially exists)
- Extract `SelectorInputsCard`, `PagePreviewCard`, `FieldRowsCard`, `SelectorRowEditor` sub-components

### 3.2 Split `components/ui/patterns.tsx` (689 → ~250 lines barrel)
- Extract larger components into `patterns/` directory: `page-header.tsx`, `tab-bar.tsx`, `run-workspace-shell.tsx`, `run-summary-chips.tsx`, `data-region.tsx`, `nav-list.tsx`, `metric-pulse.tsx`

### 3.3 Split `components/crawl/form-fields.tsx` (596 → ~50 lines barrel)
- Extract each field component into `form-fields/` directory
- Move validation functions to `lib/crawl/validation.ts`

### 3.4 Split `components/layout/app-shell.tsx` (526 → ~250 lines)
- Extract `Sidebar`, `LogoMark`, `AuthShell`, `ShellContent` into separate files
- Extract `navGroups` + `isNavItemActive` to `navigation-config.ts`

### 3.5 Split remaining page views
- `app/admin/llm/page-view.tsx` (600 → ~300): extract state, form, config list, cost log
- `app/data-enrichment/page-view.tsx` (588 → ~200): extract product list, detail view

### 3.6 Split `crawl-config-logic.ts` (526 → ~275 lines)
- Extract types → `crawl-config-types.ts`
- Extract profile functions → `crawl-config-profile.ts`
- Extract dispatch builder → `crawl-config-dispatch.ts`
- Extract selector functions → `crawl-config-selectors.ts`

---

## Estimated Total Impact

| Metric | Current | After |
|--------|---------|-------|
| Total LOC | 26,204 | ~25,900 (after dead code removal) |
| Largest file | 1,677 lines (CSS) | ~900 lines (CSS) |
| Largest component | 1,428 lines | ~300 lines |
| Files > 500 lines | 13 | ~3-4 |
| Dead code removed | — | ~300+ lines TS, 16 CSS classes, 4 npm deps |
| Duplicated code eliminated | — | ~120 lines consolidated |

**Note:** Total LOC won't drop dramatically since most refactoring is *extraction* (splitting into more files), not *deletion*. The real wins are:
- Reduced cognitive load per file
- Better testability (smaller units)
- Easier maintenance and onboarding
- Dead code + dependency cleanup reduces bundle size and security surface
