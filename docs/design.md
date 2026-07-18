---
version: "3.0"
name: "CrawlerAI Design System v3"
description: >
  Canonical frontend design system aligned with the Searchify Reference model.
  Warm stone light theme, warm charcoal dark theme, blue-violet brand accent,
  dense spacing scale, CVA-driven atoms, slot-based layouts, and fully
  accessible input fields.
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
    accent: "#3557f6"
    accent-hover: "#5575ff"
    accent-subtle: "rgba(53, 87, 246, 0.08)"
    accent-text: "#3557f6"
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
    accent: "#5575ff"
    accent-hover: "#3557f6"
    accent-subtle: "rgba(85, 117, 255, 0.12)"
    accent-text: "#5575ff"
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
  control-height-sm: "30px"
  control-height: "34px"
  control-height-lg: "38px"
  table-header-height: "32px"
  table-row-height: "40px"
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
    base: "CVA-driven inline-flex, 1.5px gap, rounded-md, control height scaling, focus-ring"
    primary: "Solid accent fill with accent-fg text and hover state adjustments"
    secondary: "Strong border with panel bg and background-alt hover"
    neutral: "Standard border with background-alt bg and well hover"
    ghost: "Transparent background with background-alt hover and text-secondary foreground"
    destructive: "Solid danger fill with accent-fg text"
    underline: "Inline accent-text link with active underline highlight"
  badges:
    base: "Type-safe discriminated union styling on status, sentiment, run-status, and citations"
    status: "Mapped to success, warning, danger, and info semantic border sets"
    sentiment: "Border-free chip mapped to positive, neutral, and negative metrics"
    classification: "Citation classification chips mapped to owned, competitor, and third-party sources"
    run-status: "Draft, queued, running, analyzing, completed, partial, failed, or cancelled runs"
  cards:
    base: "Compounded slots utilizing header, title, description, content, and footer parts"
    styling: "10px rounded borders, border-border base, bg-panel container, shadow-card"
  inputs:
    base: "Consolidated input and textarea structures utilizing self-contained styles"
    paddings: "34px control height for input, min-96px for resizable textarea"
  fields:
    base: "Dual layout architecture resolving implicit vs explicit form associations"
    render-prop: "Provides accessible ID links and ARIA attributes for inputs"
    nested: "Implicit label element wrapping, enabling backward compatibility and test queries"
  tables:
    dense: "32px sticky header heights, 40px row heights, and right-aligned numeric column support"
  tooltips:
    base: "Custom portal-based coordinate placement formatted onto dense bg-well and text-xs metrics"
  skeletons:
    base: "Animate-pulse with bg-background-alt shimmer mapping"
accessibility:
  focus: "2.5px focus outline and tokenized .focus-ring utility"
  reduced-motion: "Collapses transition and animation timings to 1ms"
  forced-colors: "Enforces strong outlines and explicit border visibility in high contrast modes"
compatibility:
  tailwind: "Bridged via CSS variables mapping directly to Tailwind v4 @theme declarations"
  react-router: "Navigation layouts utilize react-router-dom Link primitives rather than Next.js imports"
---

# Overview

`frontend/app/globals.css` is the canonical design system source of truth. Version 3.0 aligns CrawlerAI directly with the modern **Searchify Reference design model**. All components, spacing metrics, density parameters, and typography sizes conform to a highly optimized, high-density dashboard system while fully preserving CrawlerAI's specific warm-stone/charcoal branding and blue-violet accent values.

# Theme Model

Light theme is warm stone:

- `bg-base`: `#f2f0ec`
- `bg-alt`: `#e7e4de`
- `bg-panel`: `#faf8f4`
- `bg-elevated`: `#ffffff`
- `bg-well`: `#dad6cf`

Dark theme is warm charcoal:

- `bg-base`: `#0d0c0a`
- `bg-alt`: `#131110`
- `bg-panel`: `#1a1714`
- `bg-elevated`: `#222019`
- `bg-well`: `#2b2822`

The brand accent is blue-violet:

- Light theme accent: `#3557f6` (hover: `#5575ff`)
- Dark theme accent: `#5575ff` (hover: `#3557f6`)

Use the accent for active statuses, primary button actions, active nav states, selections, and primary focus indicators. Do not hardcode raw hex values in individual page files; always refer to the semantic bridged variable names.

# Typography

The font system utilizes three active families:

- `Public Sans` for standard operator controls, layouts, and body copy.
- `Bricolage Grotesque` for display and heading hierarchies.
- `JetBrains Mono` for metrics, table figures, crawl run identifiers, log files, URLs, and code blocks.

Use mono with tabular numerals for numeric data. Headings and subheadings use the display face.

# Spacing And Shape

The layout aligns on a strict 4px grid. Standard space steps are `4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80`.

Core dimensions:

- Content gutter: `32px` desktop, shrinking dynamically on smaller viewports.
- Card padding: `20px` (`--card-padding`).
- Control heights: Small `30px`, Standard `34px`, Large `38px`.
- Table header height: `32px` (`--table-header-height`).
- Table row height: `40px` (`--table-row-height`).

Borders and Radii:

- Standard Card: `10px` (`--radius-lg`).
- Standard Button / Input: `6px` (`--radius-md`).

# Component Primitives

Component primitives are self-contained, type-safe structures built inside `components/ui`:

- **Button**: Powered by CVA in `button-variants.ts` and exported in `button.tsx`. Provides aliases for deprecated variants (`accent`, `action`, `download`, `quiet`) to prevent breaks during layout refactors.
- **Badge**: Uses discriminated unions matching specific metadata contexts (status, sentiment, classification, run-status) with fallbacks for legacy `tone` and `flat` parameters.
- **Card**: Slot-based compound elements (`CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`) with `animate` parameters.
- **Input**: Consolidated, self-contained elements with direct ref-forwarding.
- **Field**: Multi-style wrapper supporting modern render props (passing IDs and ARIA tags to children) and implicit nested label fallback structures.
- **Table**: Dense analytical table featuring sticky headers and built-in numerical right-alignments.
- **Tooltip**: Stable custom SPA portals styled using dense `bg-well` and `text-xs` parameters.
- **Skeleton**: Simple, high-performance Tailwind-pulse divs.

# Motion And Accessibility

Motion transitions are optimized for snappy desktop feedback:

- Focus states utilize the unified `.focus-ring` utility.
- Reduced-motion flags scale transition durations down to `1ms` dynamically.
- Print media rules completely bypass skeletons and loading animations to ensure clear output.
