---
version: "2.0"
name: "CrawlerAI Design System v2"
description: >
  Canonical frontend design system mirrored from frontend/app/globals.css.
  Warm stone light theme, warm charcoal dark theme, rust accent, 4px grid,
  retained font stack, shared component primitives, and WCAG-aware motion and
  contrast rules.
themes:
  light:
    background-base: "#f2f0ec"
    background-alt: "#e7e4de"
    background-panel: "#faf8f4"
    background-elevated: "#ffffff"
    background-well: "#dad6cf"
    border-subtle: "#e2dfd8"
    border: "#cdc8c0"
    border-strong: "#b0a89f"
    text-primary: "#1a1815"
    text-secondary: "#443d36"
    text-muted: "#68614f"
    text-subtle: "#948d7e"
    accent: "#c2410c"
    accent-hover: "#9a3412"
    accent-text: "#9a3412"
  dark:
    background-base: "#0d0c0a"
    background-alt: "#131110"
    background-panel: "#1a1714"
    background-elevated: "#222019"
    background-well: "#2b2822"
    border-subtle: "#201d18"
    border: "#2c2820"
    border-strong: "#413b32"
    text-primary: "#f0ebe0"
    text-secondary: "#c0b6ab"
    text-muted: "#a5998a"
    text-subtle: "#78706a"
    accent: "#c2410c"
    accent-hover: "#d9581e"
    accent-text: "#ffa875"
semantic:
  success:
    light: "#059669 on #ecfdf5"
    dark: "#34d399"
  warning:
    light: "#d97706 on #fffbeb"
    dark: "#fbbf24"
  danger:
    light: "#dc2626 on #fef2f2"
    dark: "#f87171"
  info:
    light: "#2563eb on #eff6ff"
    dark: "#60a5fa"
fonts:
  primary: "Public Sans"
  display: "Bricolage Grotesque"
  mono: "JetBrains Mono"
typography:
  scale:
    "2xs": "11px"
    xs: "12px"
    sm: "14px"
    base: "15px"
    lg: "18px"
    xl: "22px"
    "2xl": "30px"
  display:
    family: "display"
    size: "30px"
    weight: "700"
    line-height: "1"
    letter-spacing: "-0.03em"
  heading-1:
    family: "display"
    size: "30px"
    weight: "700"
    line-height: "1.1"
  heading-2:
    family: "display"
    size: "22px"
    weight: "600"
    line-height: "1.2"
  heading-3:
    family: "display"
    size: "18px"
    weight: "600"
    line-height: "1.3"
  body:
    family: "primary"
    size: "15px"
    weight: "400"
    line-height: "1.55"
  body-sm:
    family: "primary"
    size: "14px"
    weight: "400"
    line-height: "1.55"
  label:
    family: "primary"
    size: "11px"
    weight: "600"
    line-height: "1.35"
    letter-spacing: "0.06em"
    casing: "uppercase"
  metric:
    family: "mono"
    weight: "700"
    line-height: "1"
    letter-spacing: "-0.025em"
spacing:
  base: "4px"
  steps:
    1: "4px"
    2: "8px"
    3: "12px"
    4: "16px"
    5: "20px"
    6: "24px"
    7: "28px"
    8: "32px"
    10: "40px"
    12: "48px"
    14: "56px"
    16: "64px"
    20: "80px"
  content-gutter: "32px desktop, 16px at <=480px"
  card-padding: "20px"
  control-height-sm: "28px"
  control-height: "32px"
  control-height-lg: "36px"
  table-header-height: "38px"
  table-row-height: "44px"
radius:
  xs: "3px"
  sm: "5px"
  md: "7px"
  lg: "10px"
  xl: "14px"
  "2xl": "20px"
  full: "9999px"
components:
  buttons:
    base: "36px default shell, semibold 14px text, inset highlight, xs shadow"
    action: "solid rust fill"
    download: "elevated secondary surface with accent-text foreground"
    destructive: "panel/elevated surface with danger border"
    neutral: "stone neutral surface"
    quiet: "transparent ghost with accent-subtle hover"
    topbar: "transparent shell action"
    link: "inline accent text link"
  segmented:
    root: "sunken mixed background, 1px border, inset depth"
    workspace-tabs: "rounded segmented tabs with accent-tinted active state"
  alerts:
    base: "md radius, 12px x 16px padding, no shadow"
  code:
    block: "alt surface, bordered, mono, wrapped"
    terminal: "panel surface, mono, 320px max height"
    json-dark: "always dark VS Code style syntax palette"
  tables:
    compact: "38px headers, 44px rows, uppercase headers, light-mode outer border"
    commerce: "sticky header, 44px image rhythm, mono price/url values"
  metrics:
    pulse-strip: "4-column grid, 2-column on small screens, top accent reveal on hover"
  skeleton:
    shimmer: "2.2s linear sweep"
accessibility:
  focus: "2.5px accent focus outline and tokenized focus ring"
  reduced-motion: "collapse animation and transition duration to 1ms"
  forced-colors: "explicit focus outline and button border support"
  print: "remove decorative motion/skeleton treatments"
compatibility:
  tailwind: "Uses @theme inline token bridge for Tailwind v4 utilities"
  aliases: "Deprecated backward-compat token aliases still exist; prefer canonical names"
---

# Overview

`frontend/app/globals.css` is source of truth. This file defines CrawlerAI Design System v2. Old blue light-theme refresh spec is stale. Current system uses warm stone surfaces, rust accent, shared tokens, and same theme logic in both raw CSS and Tailwind utility bridge.

# Theme Model

Light theme is warm stone:

- `bg-base` `#f2f0ec`
- `bg-alt` `#e7e4de`
- `bg-panel` `#faf8f4`
- `bg-elevated` `#ffffff`
- `bg-well` `#dad6cf`

Dark theme is warm charcoal:

- `bg-base` `#0d0c0a`
- `bg-alt` `#131110`
- `bg-panel` `#1a1714`
- `bg-elevated` `#222019`
- `bg-well` `#2b2822`

Accent stays rust in both themes. Primary token is `--accent: #c2410c`. Use accent for active state, primary action, selected tabs, focus cues, and visual emphasis. Use semantic status tokens for success, warning, danger, and info. Do not hardcode alternate status colors in page code.

# Typography

Three font families are active and intentional:

- `Public Sans` for product UI and body copy
- `Bricolage Grotesque` for display and heading hierarchy
- `JetBrains Mono` for metrics, prices, ids, logs, URLs, and code

Type system has four tiers:

- `T1 Display`: bold display and KPI values
- `T2 Heading`: page and section titles in display face
- `T3 Body`: readable operator text and controls
- `T4 Label`: uppercase tracked labels, captions, column headers

Canonical scale:

- `11px`, `12px`, `14px`, `15px`, `18px`, `22px`, `30px`

Use mono with tabular numerals for technical values. Body copy stays in sans. Headings and subheadings use display font.

# Spacing And Shape

System runs on strict 4px grid. Canonical spacing tokens are `4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80`.

Core rhythm:

- Content gutter: `32px`, reduced to `16px` on very small screens
- Card padding: `20px`
- Control heights: `28px`, `32px`, `36px`
- Table header height: `38px`
- Table row height: `44px`

Canonical radii:

- `3px`, `5px`, `7px`, `10px`, `14px`, `20px`, `9999px`

# Component Primitives

Prefer shared primitives over page-local styling.

- Buttons: use `.ui-button` with surface modifiers. Default button shell is 36px high, semibold, lightly inset, and token-driven.
- Segmented controls: use `.segmented-root` or `.workspace-tabs`. Active tabs use accent-tinted fill and accent-border cues.
- Alerts: use `.alert-surface` plus semantic variant.
- Code blocks: use `.code-block`. Crawl terminal uses `.crawl-terminal` and keeps mono context. JSON dark blocks stay VS Code dark regardless of app theme.
- Tables: use `.compact-data-table` for shared data tables. Commerce table extends same rhythm with sticky headers and fixed image cell sizing.
- Metrics: use `.metric-pulse-*` strip for dashboard KPI cards.
- Skeletons: use shimmer loader token set, not ad hoc gray boxes.

# Motion And Accessibility

Motion is small and purposeful:

- `fade-in`
- `dropdown-in`
- `dropdown-in-up`
- `spin`
- stagger delays up to `250ms`

Accessibility rules are built into globals:

- keyboard focus uses accent outline and tokenized focus ring
- reduced motion collapses animation and transition timing to `1ms`
- forced-colors mode adds strong visible outlines and button borders
- print strips decorative animation and skeleton visuals

# Implementation Rules

- Treat `frontend/app/globals.css` as canonical design token source.
- Prefer canonical token names such as `--bg-panel`, `--btn-primary-bg`, `--table-row-height`.
- Backward-compat aliases still exist, but new code should not depend on deprecated names.
- Use Tailwind utilities only through bridged tokens when possible.
- Do not reintroduce old blue palette, old light-only spec, or "preserve old dark theme" assumptions. Both light and dark themes are now explicitly defined in the system.
