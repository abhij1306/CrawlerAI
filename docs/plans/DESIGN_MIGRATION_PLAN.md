# Design Migration Plan: CrawlerAI/Invoro ───> Searchify Reference

This document outlines the comprehensive technical plan to migrate CrawlerAI's UI and component primitives to follow Searchify's design system structure and visual densities. It serves as a visual and structural blueprint, ensuring maximum design system cohesion while retaining CrawlerAI's existing brand identity.

> [!IMPORTANT]
> **Scope Boundaries — strictly retained from CrawlerAI:**
> - **Brand colors** (light theme and dark theme token values) are preserved verbatim. No hue/palette definitions are changed.
> - **Font family declarations** are retained: Public Sans as primary, Bricolage Grotesque as display, and JetBrains Mono as monospace. No typefaces are swapped.

---

## 1. Token Mapping Table

CrawlerAI current token values mapped to Searchify equivalents. Key brand values (colors and fonts) are marked **NO CHANGE** per the scope boundary constraints.

| Category | CrawlerAI Token | Searchify Equivalent | Migration Action / Value Change |
|---|---|---|---|
| **Fonts** | `--font-primary-family` | `--font-primary-family` | **NO CHANGE** (Public Sans Variable) |
| | `--font-display-family` | `--font-display-family` | **NO CHANGE** (Bricolage Grotesque Variable) |
| | `--font-mono-family` | `--font-mono-family` | **NO CHANGE** (JetBrains Mono Variable, tabular-nums active) |
| **Brand Colors (Light)** | `--bg-base` (`#f2f0ec`) | `--bg-base` | **NO CHANGE** |
| | `--bg-alt` (`#e7e4de`) | `--bg-alt` | **NO CHANGE** |
| | `--bg-panel` (`#faf8f4`) | `--bg-panel` | **NO CHANGE** |
| | `--bg-elevated` (`#ffffff`) | `--bg-elevated` | **NO CHANGE** |
| | `--bg-well` (`#dad6cf`) | `--bg-well` | **NO CHANGE** |
| | `--bg-sidebar` (`#f3f3f2`) | `--bg-sidebar` | **NO CHANGE** |
| | `--border-subtle` (`#e2dfd8`) | `--border-subtle` | **NO CHANGE** |
| | `--border` (`#cdc8c0`) | `--border` | **NO CHANGE** |
| | `--border-strong` (`#b0a89f`) | `--border-strong` | **NO CHANGE** |
| | `--text-primary` (`#1a1815`) | `--text-primary` | **NO CHANGE** |
| | `--text-secondary` (`#443d36`) | `--text-secondary` | **NO CHANGE** |
| | `--text-muted` (`#68614f`) | `--text-muted` | **NO CHANGE** |
| | `--text-subtle` (`#948d7e`) | `--text-subtle` | **NO CHANGE** |
| | `--accent` (`#c2410c`) | `--accent` | **NO CHANGE** (Rust Orange brand accent) |
| | `--accent-hover` (`#9a3412`) | `--accent-hover` | **NO CHANGE** |
| | `--accent-text` (`#9a3412`) | `--accent-text` | **NO CHANGE** |
| **Brand Colors (Dark)** | `--bg-base` (`#0d0c0a`) | `--bg-base` | **NO CHANGE** |
| | `--bg-alt` (`#131110`) | `--bg-alt` | **NO CHANGE** |
| | `--bg-panel` (`#1a1714`) | `--bg-panel` | **NO CHANGE** |
| | `--bg-elevated` (`#222019`) | `--bg-elevated` | **NO CHANGE** |
| | `--bg-well` (`#2b2822`) | `--bg-well` | **NO CHANGE** |
| | `--bg-sidebar` (`#141414`) | `--bg-sidebar` | **NO CHANGE** |
| | `--border-subtle` (`#201d18`) | `--border-subtle` | **NO CHANGE** |
| | `--border` (`#2c2820`) | `--border` | **NO CHANGE** |
| | `--border-strong` (`#413b32`) | `--border-strong` | **NO CHANGE** |
| | `--text-primary` (`#f0ebe0`) | `--text-primary` | **NO CHANGE** |
| | `--text-secondary` (`#c0b6ab`) | `--text-secondary` | **NO CHANGE** |
| | `--text-muted` (`#a5998a`) | `--text-muted` | **NO CHANGE** |
| | `--text-subtle` (`#78706a`) | `--text-subtle` | **NO CHANGE** |
| | `--accent` (`#c2410c`) | `--accent` | **NO CHANGE** (Rust Orange brand accent) |
| | `--accent-hover` (`#d9581e`) | `--accent-hover` | **NO CHANGE** |
| | `--accent-text` (`#ffa875`) | `--accent-text` | **NO CHANGE** |
| **Spacing Scale** | `--space-1` (4px) to `--space-20` (80px) | `--space-1` to `--space-20` | **NO CHANGE** (linear 4px base increments align) |
| | `--content-gutter` (32px) | `--content-gutter` | **NO CHANGE** |
| | `--card-padding` (20px) | `--card-padding` | **NO CHANGE** |
| **Control Heights** | `--control-height-sm` (28px) | `--control-height-sm` (30px) | **UPDATE**: Raised by +2px for touch accessibility. |
| | `--control-height` (32px) | `--control-height` (34px) | **UPDATE**: Raised by +2px for interactive density. |
| | `--control-height-lg` (36px) | `--control-height-lg` (38px) | **UPDATE**: Raised by +2px for larger forms. |
| **Table Metrics** | `--table-header-height` (38px) | `--table-header-height` (32px) | **UPDATE**: Shrunk by -6px for dense B2B alignment. |
| | `--table-row-height` (44px) | `--table-row-height` (40px) | **UPDATE**: Shrunk by -4px for dense B2B alignment. |
| **Border Radii** | `--radius-xs` (3px) to `--radius-2xl` (20px) | `--radius-xs` to `--radius-2xl` | **NO CHANGE** (scale mappings are identical) |
| **Elevation / Shadows**| `--shadow-xs-value` | `--shadow-xs` | **NO CHANGE** (retain warm-stone opacities) |
| | `--shadow-sm-value` | `--shadow-sm` | **NO CHANGE** |
| | `--shadow-card-value` | `--shadow-card` | **NO CHANGE** |
| | `--shadow-elevated-value` | `--shadow-elevated` | **NO CHANGE** |
| | `--shadow-lg-value` | `--shadow-lg` | **NO CHANGE** |
| | `--shadow-modal` | `--shadow-modal` | **NO CHANGE** |
| **Motion & Transition**| `--transition-fast` (100ms) | `--transition-fast` (100ms) | **NO CHANGE** (values align; keep cubic-bezier standard) |
| | `--transition-base` (180ms) | `--transition-base` (180ms) | **NO CHANGE** |
| | `--transition-slow` (280ms) | `--transition-slow` (280ms) | **NO CHANGE** |

---

## 2. Component Migration Matrix

This matrix categorizes how CrawlerAI's current component layer is adapted to follow Searchify's visual design system.

| Component | Current State (CrawlerAI) | Target State (Searchify pattern) | Debt Removed | Migration Complexity (S/M/L) | Breaking Change (Y/N) |
|---|---|---|---|---|---|
| **Button** | Maps variants to legacy custom class selectors defined in `globals.css` (e.g., `button-action-surface`). Custom layouts and paddings. | Port Searchify's utility-driven CVA button configuration (`button-variants.ts` + `button.tsx`) mapped directly to `@theme` bridged utility classes. | Deletes complex custom class structures from `globals.css`. Standardizes hover, focus, and disabled states. | **S** | **N** (Vast majority of props map 1:1; variant names like `primary` and `secondary` match) |
| **Badge** | Uses CVA only for base layout, then maps custom tones to javascript key dictionaries (`toneText`, `toneBox`). Hardcoded pulser dot. | Port Searchify's discriminated Badge component (`badge.tsx` + `badge-variants.ts`) supporting four clear badge groups (`status`, `sentiment`, `classification`, `run-status`). | Removes redundant JavaScript dictionary maps. Introduces type-safe categorizations for run-status, sentiment, and classification badges. | **S** | **Y** (Requires updating imports and changing `tone` to `variant="status" value="..."` across pages) |
| **Card** | Simple styled `<section>` with padding. No sub-components for header, title, description, content, or footer. Pages copy-paste HTML nested div layouts. | Port Searchify's compound Card system (`card.tsx` with nested `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, and `CardFooter` sub-components) using `bg-panel` and standard padding variables. | Eliminates ad-hoc page-level div styling and copy-pasted section layouts. Deletes `card-variants.ts`. Establishes consistent visual rhythm. | **M** | **Y** (Pages using custom `<Card>` nesting need to be refactored to use compound child tags) |
| **Table** | Has sub-components but lacks robust layout alignment parameters. Hardcoded table paddings (`px-5`) and row-specific margins. | Port Searchify's dense analytics Table (`table.tsx`) with condensed padding (`px-3`), customizable `numeric` alignments on head and cell, and height tokens (`--table-row-height` 40px, `--table-header-height` 32px). | Removes arbitrary page-level formatting for numbers. Standardizes headers and row spacing. | **M** | **Y** (Slight change in prop behavior and structure, specifically adding `numeric` prop to relevant headers/cells) |
| **Input / Textarea** | Split across `input.tsx` and `input-variants.ts`. Textarea min-height and height variables are separate. Focus styling maps to custom `.focus-ring` classes. | Port Searchify's consolidated `input.tsx` file (which contains both `Input` and `Textarea` and their class strings inline), utilizing the new height variables (34px instead of 32px). | Deletes `input-variants.ts` completely. Standardizes input disabled and cursor-not-allowed states. | **S** | **N** (Drop-in replacement, but heights change to 34px) |
| **Field** | Standard wrapper nesting control. No ARIA attributes, error boundaries, or label matching. | Port Searchify's render-prop based Field primitive (`field.tsx`) which auto-generates accessible IDs and manages `aria-invalid`, `aria-describedby` hint, and alert errors. | Removes manual form-level error elements. Drastically improves accessibility (WCAG compliance) for form validations. | **M** | **Y** (Requires refactoring form fields to use the render-prop child mapping pattern) |
| **Dropdown / Select**| Custom Radix Menu wrapper. Uses warm-stone border variables. | Port Searchify's Dropdown using `bg-elevated`, `border`, `shadow-elevated`. | Standardizes floating menu borders, text sizes, and shadows. | **S** | **N** |
| **Dialog / Modal** | Custom Radix Modal wrapper. Some styling overrides. | Port Searchify's Dialog supporting `--overlay-scrim`, `bg-elevated`, `shadow-modal`, and `--radius-xl`. | Fixes modal overlay color inconsistencies and background flashing. | **S** | **N** |
| **Tooltip** | Large custom Tooltip. | Port Searchify's Tooltip with `bg-well` and `--text-xs`. | Standardizes tooltip styling and prevents clipping on boundaries. | **S** | **N** |
| **Sidebar / Shell** | Highly customized collapsible layout driven by `app-shell.module.css`. | Port Searchify's simple flexbox-based AppShell (`components/layout/app-shell.tsx`) with sidebar width of 240px and top-bar height of 52px. Sidebar active states use `accent-subtle` bg and `accent-text`. | Replaces high-overhead custom grid styles with clean flex properties. Removes custom media queries for collapses. | **M** | **Y** (Requires adapting CrawlerAI's left nav items to Searchify's flat list and group mappings) |
| **ThemeToggle** | Custom dual-mode toggle with custom animations. | Port Searchify's simplified, performance-optimized ThemeToggle. | Resolves redundant code and initial render theme flashes. | **S** | **N** |
| **Skeleton** | Basic shimmer wrapper. | Port Searchify's skeleton with `--skeleton-base` and `--skeleton-highlight` shimmer. | Removes ad-hoc skeleton animations in page-views. | **S** | **N** |

---

## 3. Phased Rollout Plan

A step-by-step phased approach to manage complexity, preserve build stability, and isolate breaking changes.

### Phase 1: Token Engine and CSS Reset Alignment
- **Activities:** 
  1. Modify `frontend/app/globals.css` to align spacing, control heights (`30px` / `34px` / `38px`), and table row/header metrics (`40px` / `32px`) to Searchify's specifications.
  2. Map all variables to the Tailwind CSS v4 `@theme inline` bridge.
  3. Ensure brand-specific palette variables (`--accent`, `--bg-base`, etc.) and font stacks are left untouched.
- **Entry Criteria:** Design migration plan approved by user.
- **Exit Criteria:** Tailind v4 compiler builds without errors. Verified no broken token reference warnings in build logs.

### Phase 2: Atoms and Primitives Migration
- **Activities:** 
  1. Port Searchify's clean, utility-driven `Button`, `Badge`, `Input`, and `Table` primitives into `frontend/components/ui/`.
  2. Implement Searchify's compound `Card` component and delete local pages' custom wrapper divs.
  3. Re-export all migrated primitives from `frontend/components/ui/primitives.tsx` to prevent broken paths.
- **Entry Criteria:** Phase 1 complete.
- **Exit Criteria:** Common atomic components compile and pass local vitest scripts (`vp test components/ui`).

### Phase 3: Molecules and Layout Integration
- **Activities:** 
  1. Migrate the global shell (`AppShell` and `AuthShell`) to follow Searchify's simple flexbox layout.
  2. Implement Searchify's sidebar nav configuration (`SidebarNav`) and pinned user-menu.
  3. Wire the TopBar with Searchify's exact dimensions (52px) and search placeholders, while maintaining CrawlerAI's dynamic `PageHeader` context action-button portal.
  4. Delete the custom stylesheets `app-shell.module.css` and `auth-shell.module.css`.
- **Entry Criteria:** Phase 2 complete.
- **Exit Criteria:** App layout functions flawlessly on both desktop and mobile screens. Collapsible sidebar transition compiles cleanly without styling jank.

### Phase 4: Page-Level Refactoring & Debt Sweep
- **Activities:** 
  1. Convert forms inside CrawlerAI `/setup`, `/login`, `/register`, and `/crawl` to utilize the new render-prop based `Field` wrapper.
  2. Remove inline styling overrides (`style={{ ... }}`) from files highlighted in the Technical Debt inventory.
  3. Consolidate and rewrite table layouts in pages (e.g. `jobs/page-view`, `data-enrichment`) to utilize the new type-safe `Table` component with the `numeric` prop.
- **Entry Criteria:** Phase 3 complete.
- **Exit Criteria:** Core end-to-end user flows validated. VitePlus full codebase audit runs cleanly (`vp check` and `vp build`).

---

## 4. Technical Debt Removal List

The technical debt and "AI slop" identified in the target audit will be eliminated during the migration rollout:

1. **Delete redundant variant files:**
   - [DELETE] [card-variants.ts](file:///c:/Projects/CrawlerAI/frontend/components/ui/card-variants.ts) — logic consolidated inside `card.tsx`.
   - [DELETE] [input-variants.ts](file:///c:/Projects/CrawlerAI/frontend/components/ui/input-variants.ts) — styles merged as inline classes in `input.tsx`.
   - [DELETE] [badge-variants.ts](file:///c:/Projects/CrawlerAI/frontend/components/ui/badge-variants.ts) — replaced by type-safe variants of Searchify's system.
2. **Delete legacy layout module styles:**
   - [DELETE] [app-shell.module.css](file:///c:/Projects/CrawlerAI/frontend/components/layout/app-shell.module.css) — layout fully replaced by pure Tailwind utility styles.
   - [DELETE] [auth-shell.module.css](file:///c:/Projects/CrawlerAI/frontend/components/layout/auth-shell.module.css) — auth page card replaces manual styles.
3. **Consolidate forms and field blocks:**
   - Refactor nested accessible field structures inside [form-fields.tsx](file:///c:/Projects/CrawlerAI/frontend/components/crawl/form-fields.tsx).
   - Standardize all text inputs, textareas, and search elements to utilize native ref-forwarding controls in [input.tsx](file:///c:/Projects/CrawlerAI/frontend/components/ui/input.tsx).
4. **Purge hardcoded inline styles:**
   - Remove inline colors and widths in [dashboard/page-view.tsx](file:///c:/Projects/CrawlerAI/frontend/app/dashboard/page-view.tsx#L45-L65).
   - Remove table head arbitrary pixel widths and styles inside [jobs/page-view.tsx](file:///c:/Projects/CrawlerAI/frontend/app/jobs/page-view.tsx#L105-L138).
   - Standardize size metrics and inline cell font declarations in [records-table.tsx](file:///c:/Projects/CrawlerAI/frontend/components/crawl/records-table.tsx#L85-L129).

---

## 5. New Design System File Structure

Following the migration, the design system directory architecture will be structured as a single, scalable source of truth:

```
frontend/
├── app/
│   └── globals.css                    <── Single token source of truth (CSS vars + @theme inline bridges)
├── components/
│   ├── layout/
│   │   ├── app-shell.tsx              <── Pure flex layout framework
│   │   ├── sidebar-nav.tsx            <── Grouped sidebar nav items
│   │   ├── top-bar.tsx                <── Header area shell + action buttons
│   │   └── top-bar-context.tsx        <── Dynamic action-button context bridge
│   └── ui/
│       ├── button.tsx                 <── Direct tailwind utility variations
│       ├── button-variants.ts         <── CVA button variants (no raw CSS selectors)
│       ├── badge.tsx                  <── Type-safe badge element
│       ├── badge-variants.ts          <── Type-safe mappings (status, sentiment, classification)
│       ├── card.tsx                   <── Compound Card, CardHeader, CardTitle, CardContent, CardFooter
│       ├── table.tsx                  <── Dense analytics table with numerical right-alignment
│       ├── input.tsx                  <── Ref-forwarding input and textareas
│       ├── field.tsx                  <── Fully accessible render-prop form field wrapper
│       ├── dropdown.tsx               <── Radix-backed dropdown primitives
│       ├── dialog.tsx                 <── Radix-backed overlay modals
│       ├── tooltip.tsx                <── Accessible hover details
│       ├── skeleton.tsx               <── Standard shimmer loading placeholder
│       └── primitives.tsx             <── Single entry point for clean re-exports
```

---

## 6. Risk Register

| Risk Event | Impact Severity | Probability | Mitigation Strategy |
|---|---|---|---|
| **Vite/React Router v7 vs Next.js 15 routing mismatch** | High | High | Searchify components use Next.js routing patterns (e.g. `next/link` or `next/navigation`). During migration, all links and router hook calls must be adapted to use `react-router-dom`'s `<Link>` and standard SPA routing properties. |
| **Breaking changes in Form Registration** | Medium | Medium | Changing `Field` to a render-prop pattern is a breaking change for form fields currently wrapped inside standard components. We will carefully map the registration inputs inside `form-fields.tsx` to receive fields from child hook parameters correctly. |
| **Table Spacing changes breaking Virtual Scroll containers** | High | Low | Shrunk table row heights (-4px) and table header heights (-6px) will break inline virtual list item spacers in `app/data-enrichment` and `records-table.tsx`. Spacers must be dynamically calculated or retargeted with Searchify's strict `--table-row-height` variable. |
| **Grid layout refactoring breaking dynamic viewports** | Medium | Medium | CrawlerAI relies on sticky container heights inside `/crawl` to keep scrollbars fixed. Swapping layout modules to a flexbox AppShell might collapse scrolling regions. We will verify viewport sizing on high-definition layouts using Tailwind's `min-h-0 flex-1` overrides. |

---

## 7. Open Questions

Before implementation begins, we require feedback and sign-off on the following items:

> [!WARNING]
> ### 1. Handling Soft Accent Tints for Brand Palette
> Searchify relies extensively on soft accents (e.g., `bg-accent-soft` or `bg-accent-subtle` mapped to `rgba(15, 157, 118, 0.06)`). Since we are retaining CrawlerAI's rust orange brand accent (`#c2410c`), we must calculate matching soft and subtle RGB transparencies.
> **Proposed Values:**
> - `var(--accent-subtle)`: `rgba(194, 65, 12, 0.12)`
> - `var(--accent-soft)`: `rgba(194, 65, 12, 0.06)`
> - `var(--accent-border)`: `rgba(194, 65, 12, 0.28)`
> *Please confirm if these calculated values meet your brand aesthetics.*

> [!WARNING]
> ### 2. PageHeader Dynamic Action Button Placement
> Searchify's TopBar is static for MVP and does not host page-level buttons (like CrawlerAI's dynamic "Launch Audit" or "Reset Workspace"). CrawlerAI uses a PageHeader store to inject action button elements.
> **Proposed Solution:** Retain CrawlerAI's dynamic action portal logic, but style the target TopBar container and injected buttons using Searchify's exact layout variables (`h-13` or `52px` container height, matching borders, and Searchify-style buttons).
> *Please confirm if you approve of keeping the dynamic PageHeader portal.*
