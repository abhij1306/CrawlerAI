---
version: "3.0"
name: CrawlerAI Console
description: >
  Precision data-extraction workspace. Graphite surfaces, chromatic restraint,
  and operator-first ergonomics. Inspired by Linear's exactness, Vercel's
  black/white discipline, and IBM Carbon's enterprise grid — adapted for a
  real-time crawl and extraction console.
category: Developer Tools

# ─── MACHINE-READABLE DESIGN TOKENS ────────────────────────────────────────
# Format follows google-labs-code/design.md spec (alpha).
# Reference syntax: {token.path}

colors:

  # ── Light mode ─────────────────────────────────────────────────
  canvas:          "#f2f2f0"        # Page floor — slightly warm off-white
  canvas-alt:      "#e8e8e8"        # Secondary zones, stripe rows
  panel:           "#ffffff"        # Card, dialog, popover surface
  panel-raised:    "#fafafa"        # Elevated within a panel (nested inputs, toolbars)
  panel-strong:    "#e4e4e4"        # Strong panel variant
  sidebar:         "#f2f2f0"        # Left rail — matches canvas
  border:          "#d4d4d4"        # Default border — cool grey
  border-strong:   "#bcbcbc"        # Emphasized border, focused control edge

  text:            "#2a2a2a"        # Near-black — 12:1 contrast on canvas
  text-secondary:  "#5a5a5a"        # Supporting copy, secondary labels
  text-muted:      "#9a9a9a"        # Placeholder, helper text, disabled label
  text-on-accent:  "#ffffff"        # Text on accent-fill surfaces

  accent:          "#0F172A"        # Primary interactive — deep slate navy
  accent-hover:    "#1E2A45"        # Hover state on primary
  accent-subtle:   "rgba(15, 23, 42, 0.06)"  # Tinted wash for row hover, selected state
  accent-dim:      "rgba(15, 23, 42, 0.10)"  # Slightly stronger accent wash
  accent-fg:       "#ffffff"        # Foreground on accent surfaces

  success:         "#00b07a"        # Emerald — completed, healthy
  success-bg:      "#e6f7f2"        # Success background wash
  warning:         "#cc8800"        # Amber — degraded, slow
  warning-bg:      "#fff6e5"        # Warning background wash
  danger:          "#d32f2f"        # Red — failed, blocked, critical
  danger-bg:       "#faeaea"        # Danger background wash
  info:            "#0288d1"        # Blue — running, informational
  info-bg:         "#e1f5fe"        # Info background wash

  # ── Dark mode ───────────────────────────────────────────────────
  dark-canvas:         "#141414"        # Deep base
  dark-canvas-alt:     "#1a1a1a"        # Stripe rows, zone demarcation
  dark-panel:          "#1e1e1e"        # Card, dialog — first step up
  dark-panel-raised:   "#252526"        # Toolbar, elevated input areas
  dark-panel-strong:   "#2d2d2d"        # Strong panel variant
  dark-sidebar:        "#141414"        # Left rail — matches canvas
  dark-border:         "rgba(255,255,255,0.07)"   # Default edge
  dark-border-strong:  "rgba(255,255,255,0.13)"   # Focused, emphasized edge

  dark-text:           "#9a9a9a"        # Primary text
  dark-text-secondary: "#999999"        # Supporting, secondary labels
  dark-text-muted:     "#666666"        # Placeholder, disabled, helper
  dark-text-on-accent: "#020617"        # Text on sky-blue accent fill

  dark-accent:         "#38BDF8"        # Sky blue — primary interactive signal
  dark-accent-hover:   "#7DD3FC"        # Hover: lightened sky
  dark-accent-subtle:  "rgba(56, 189, 248, 0.10)"   # Wash for row hover / selected bg
  dark-accent-dim:     "rgba(56, 189, 248, 0.20)"   # Stronger accent wash
  dark-accent-fg:      "#020617"        # Foreground on accent-fill buttons

  dark-success:        "#00e6a8"        # Emerald — saturated, readable on dark
  dark-success-bg:     "rgba(0, 230, 168, 0.1)"
  dark-warning:        "#ffb74d"        # Amber — clear on dark
  dark-warning-bg:     "rgba(255, 183, 77, 0.1)"
  dark-danger:         "#ef5350"        # Red — visible on dark
  dark-danger-bg:      "rgba(239, 83, 80, 0.1)"
  dark-info:           "#4fc3f7"        # Blue — informational
  dark-info-bg:        "rgba(79, 195, 247, 0.1)"

typography:

  # ── Type Scale ─────────────────────────────────
  # Body = text-base. Metric ceiling = text-2xl.
  scale:
    text-xs:   "0.75rem"     # 12px — badges, timestamps, micro-labels
    text-sm:   "0.8125rem"   # 13px — table data, secondary UI chrome
    text-base: "0.9375rem"   # 15px — primary body, form fields, buttons
    text-lg:   "1.0625rem"   # 17px — card titles, section headings
    text-xl:   "1.375rem"    # 22px — page titles ONLY (one per view)
    text-2xl:  "1.75rem"     # 28px — KPI display numbers

  # ── Type Roles ──────────────────────────────────────────────────
  page-title:
    fontFamily: "Outfit"
    fontSize:   "{typography.scale.text-xl}"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.015em
    note: "One per page. Never more."

  section-heading:
    fontFamily: "Outfit"
    fontSize:   "{typography.scale.text-lg}"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: 0

  body:
    fontFamily: "Outfit"
    fontSize:   "{typography.scale.text-base}"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0

  control:
    fontFamily: "Outfit"
    fontSize:   "{typography.scale.text-base}"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: 0
    note: "Buttons, nav links, tabs"

  label:
    fontFamily: "JetBrains Mono"
    fontSize:   "{typography.scale.text-sm}"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: 0.12em
    textTransform: uppercase
    note: "Column headers, field labels"

  meta:
    fontFamily: "Outfit"
    fontSize:   "{typography.scale.text-xs}"
    fontWeight: 400
    lineHeight: 1.35
    note: "Timestamps, badges, hints"

  mono-data:
    fontFamily: "JetBrains Mono"
    fontSize:   "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0

  mono-sm:
    fontFamily: "JetBrains Mono"
    fontSize:   "0.8125rem"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0

  metric:
    fontFamily: "JetBrains Mono"
    fontSize:   "{typography.scale.text-2xl}"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -0.025em
    note: "KPI display numbers. text-2xl (28px) is the ceiling."

rounded:
  xs:   2px
  sm:   3px
  md:   5px
  lg:   7px
  xl:   9px
  2xl:  12px
  full: 9999px

spacing:
  space-1:            4px
  space-2:            8px
  space-3:            12px
  space-4:            16px
  space-5:            20px
  space-6:            24px
  space-7:            28px
  space-8:            32px
  space-10:           40px
  space-12:           48px
  space-16:           64px
  content-gutter:     24px       # var(--space-6) — all page containers
  content-max:        1440px
  control-height:     36px

  # ── Spacing conventions ─────────────────────────────────────────
  # Inner component padding:  space-3 (12px) to space-4 (16px)
  # Between fields/rows:      space-3 (12px)
  # Between sections/cards:   space-6 (24px)
  # Page-level gutters:       content-gutter (24px) on desktop

components:

  # ── Buttons ──────────────────────────────────────────────────────
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor:       "{colors.accent-fg}"
    typography:      "{typography.control}"
    rounded:         "{rounded.md}"
    padding:         "5px 14px"
    height:          36px

  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"

  button-primary-active:
    backgroundColor: "{colors.accent-hover}"
    transform:       "scale(0.98)"

  button-secondary:
    backgroundColor: "{colors.panel-raised}"
    textColor:       "{colors.text}"
    typography:      "{typography.control}"
    rounded:         "{rounded.md}"
    padding:         "5px 14px"
    height:          36px
    border:          "1px solid {colors.border}"

  button-secondary-hover:
    backgroundColor: "{colors.canvas-alt}"
    borderColor:     "{colors.border-strong}"

  button-ghost:
    backgroundColor: "transparent"
    textColor:       "{colors.text-secondary}"
    typography:      "{typography.control}"
    rounded:         "{rounded.md}"
    padding:         "5px 10px"
    height:          36px

  button-ghost-hover:
    backgroundColor: "{colors.accent-subtle}"
    textColor:       "{colors.text}"

  button-danger:
    backgroundColor: "{colors.danger-bg}"
    textColor:       "{colors.danger}"
    typography:      "{typography.control}"
    rounded:         "{rounded.md}"
    padding:         "5px 14px"
    height:          36px

  # ── Inputs & Controls ───────────────────────────────────────────
  input:
    backgroundColor: "{colors.panel}"
    textColor:       "{colors.text}"
    typography:      "{typography.body}"
    rounded:         "{rounded.md}"
    padding:         "7px 12px"
    height:          36px
    border:          "1px solid {colors.border}"

  input-hover:
    borderColor: "{colors.border-strong}"

  input-focus:
    borderColor: "{colors.accent}"
    outline:     "2px solid {colors.accent-subtle}"

  input-placeholder:
    textColor: "{colors.text-muted}"

  toggle-on:
    backgroundColor: "{colors.accent}"
  toggle-off:
    backgroundColor: "{colors.border-strong}"

  # ── Toggle Selected State ───────────────────────────────────────
  # Distinguishes "I am here" (selected toggle) from "this is active" (nav badge).
  # Nav/mode badges: accent bg + accent-fg text.
  # Selected toggles: accent border + subtle tint + primary text.
  toggle-selected:
    border:          "1px solid {colors.accent}"
    backgroundColor: "{colors.accent-subtle}"
    textColor:       "{colors.text}"

  # ── Table ───────────────────────────────────────────────────────
  table-header:
    backgroundColor: "{colors.canvas-alt}"
    textColor:       "{colors.text-muted}"
    typography:      "{typography.label}"
    height:          34px
    borderBottom:    "1px solid {colors.border}"

  table-row:
    backgroundColor: "{colors.panel}"
    textColor:       "{colors.text}"
    height:          40px
    borderBottom:    "1px solid {colors.border}"

  table-row-stripe:
    backgroundColor: "{colors.canvas-alt}"

  table-row-hover:
    backgroundColor: "{colors.accent-subtle}"

  table-row-selected:
    backgroundColor: "{colors.accent-subtle}"
    borderLeft:      "2px solid {colors.accent}"

  # ── Badges / Status Pills ────────────────────────────────────────
  badge-success:
    backgroundColor: "{colors.success-bg}"
    textColor:       "{colors.success}"
    typography:      "{typography.label}"
    rounded:         "{rounded.sm}"
    padding:         "2px 8px"

  badge-danger:
    backgroundColor: "{colors.danger-bg}"
    textColor:       "{colors.danger}"
    typography:      "{typography.label}"
    rounded:         "{rounded.sm}"
    padding:         "2px 8px"

  badge-warning:
    backgroundColor: "{colors.warning-bg}"
    textColor:       "{colors.warning}"
    typography:      "{typography.label}"
    rounded:         "{rounded.sm}"
    padding:         "2px 8px"

  badge-info:
    backgroundColor: "{colors.info-bg}"
    textColor:       "{colors.info}"
    typography:      "{typography.label}"
    rounded:         "{rounded.sm}"
    padding:         "2px 8px"

  badge-neutral:
    backgroundColor: "{colors.canvas-alt}"
    textColor:       "{colors.text-secondary}"
    typography:      "{typography.label}"
    rounded:         "{rounded.sm}"
    padding:         "2px 8px"

  # ── Status Dot ──────────────────────────────────────────────────
  status-dot:
    size:   6px
    rounded: "{rounded.full}"
  status-dot-success: { color: "{colors.success}" }
  status-dot-running: { color: "{colors.info}" }
  status-dot-warning: { color: "{colors.warning}" }
  status-dot-failed:  { color: "{colors.danger}" }
  status-dot-idle:    { color: "{colors.text-muted}" }

  # ── Navigation ──────────────────────────────────────────────────
  nav-item:
    backgroundColor: "transparent"
    textColor:       "{colors.text-secondary}"
    typography:      "{typography.control}"
    rounded:         "{rounded.md}"
    padding:         "6px 10px"
    height:          36px

  nav-item-hover:
    backgroundColor: "{colors.accent-subtle}"
    textColor:       "{colors.text}"

  nav-item-active:
    backgroundColor: "{colors.accent-subtle}"
    textColor:       "{colors.text}"
    fontWeight:      600
    borderLeft:      "2px solid {colors.accent}"

  nav-group-label:
    textColor:   "{colors.text-muted}"
    typography:  "{typography.label}"
    paddingLeft: "10px"
    marginTop:   "20px"
    marginBottom: "4px"

  # ── Cards & Panels ──────────────────────────────────────────────
  card:
    backgroundColor: "{colors.panel}"
    rounded:         "{rounded.xl}"
    border:          "1px solid {colors.border}"
    padding:         "20px"

  card-header:
    backgroundColor: "{colors.canvas-alt}"
    borderBottom:    "1px solid {colors.border}"
    padding:         "10px 16px"

  metric-card:
    backgroundColor: "{colors.panel}"
    rounded:         "{rounded.xl}"
    border:          "1px solid {colors.border}"
    padding:         "16px 20px"

shadows:
  note: >
    No glow shadows. No colored elevation. No accent-tinted drop shadows.
    Elevation is expressed through surface color steps + border containment only.
    All shadow values are set to 'none' in the implementation.

---

## Overview

CrawlerAI Console is an operator-first data workspace: dense, precise, and
undecorated. Its visual language is derived from three reference systems:

**Linear** supplies the dark-mode DNA — deep canvas, cool-neutral text,
luminance-stepped surfaces, and a single precisely-placed accent color. Every
pixel earns its place; decoration is disqualified by default.

**Vercel** supplies the black-and-white discipline — confident dark primary
buttons, hairline borders, and the conviction that negative space is a feature,
not a failure.

**IBM Carbon** supplies the grid rigor — 4px unit spacing, sticky table headers,
functional label formatting, and the enterprise-grade structural clarity
required by a tool processing thousands of crawl records.

The result is a workspace where crawl operators can watch runs, scan extractions,
compare selector output, and diagnose failures at a glance — without the visual
noise of a dashboard optimized for demos rather than daily use.

---

## Colors

### Light Mode — Warm Graphite

Light mode uses a slightly warm off-white canvas (`#f2f2f0`) that distinguishes
the UI from generic cold-white apps while remaining neutral enough for long
sessions.

**Text hierarchy uses three clearly differentiated tiers:**
- Primary (`#2a2a2a`): 12:1 contrast on canvas. All body copy, headings, values.
- Secondary (`#5a5a5a`): Supporting copy, descriptions, secondary labels.
- Muted (`#9a9a9a`): Placeholders, hints, timestamps, decorative labels.

**Accent is deep slate navy (`#0F172A`).** Primary buttons are confident and dark.
This is not a playful brand accent — it is the on/off signal of an industrial control.

Use the accent for: primary buttons, active navigation, focus rings, selected row
indicators, and run state markers. Nowhere else.

Semantic colors carry literal meaning. `success (#00b07a)` means a crawl
completed cleanly. `danger (#d32f2f)` means a block or failure. `warning (#cc8800)`
means degraded throughput or a soft error. `info (#0288d1)` means a run is in
progress. Do not repurpose semantic colors for decoration.

### Dark Mode — Deep Console

Dark mode uses `#141414` as the base canvas. Surfaces step up through `#1a1a1a`
→ `#1e1e1e` → `#252526` for depth.

**Accent is sky blue (`#38BDF8`).** This evokes networks, data pipelines, and web
infrastructure without feeling artificial or consumer-playful. It provides a clear
interactive signal with high legibility on the deep canvas.

Use the sky-blue accent for: interactive highlights, active states, running
indicators, focus rings, selected rows, and progress fills. Nowhere else.

### Semantic Color Rules

- **Success** = crawl completed, record saved, selector resolved
- **Danger** = crawl failed, bot block, extraction error, critical threshold
- **Warning** = degraded mode, fallback triggered, slow response, soft limit
- **Info** = run in progress, loading, pending job
- Status must always include text. Color is a redundancy layer, not the primary signal.

---

## Typography

Two typefaces. No exceptions.

**Outfit** handles all UI text: navigation, labels, body copy, controls,
headings, and status messages. It is geometric and clean, making long sessions
less fatiguing while reading as a modern developer tool.

**JetBrains Mono** handles all data: run IDs, timestamps, URLs, domain names,
log output, JSON, record counts, metric values, table body cells containing
identifiers or numbers. Any value that must align vertically or scan as a unit
gets monospace treatment.

### Type Scale — 5 Tokens

The scale uses exactly 5 size tokens. No duplicates, no extras:

| Token       | Size     | px  | Usage                              |
|-------------|----------|-----|------------------------------------|
| `text-xs`   | 0.75rem  | 12  | Badges, timestamps, micro-labels   |
| `text-sm`   | 0.8125rem| 13  | Table data, secondary UI chrome    |
| `text-base` | 0.9375rem| 15  | Primary body, form fields, buttons |
| `text-lg`   | 1.0625rem| 17  | Card titles, section headings      |
| `text-xl`   | 1.375rem | 22  | Page titles ONLY (one per view)    |
| `text-2xl`  | 1.75rem  | 28  | KPI display numbers                |

Body `font-size` is set to `text-base` (15px). This is the actual base.

### Type Roles

| Role             | Token      | Font           | Weight | Usage                    |
|------------------|------------|----------------|--------|--------------------------|
| page-title       | text-xl    | Outfit         | 600    | One `<h1>` per page      |
| section-heading  | text-lg    | Outfit         | 600    | Card/panel headers        |
| body             | text-base  | Outfit         | 400    | All copy, form fields     |
| control          | text-base  | Outfit         | 500    | Buttons, nav links, tabs  |
| label            | text-sm    | JetBrains Mono | 700 + uppercase | Column headers, field labels |
| meta             | text-xs    | Outfit         | 400    | Timestamps, badges, hints |

### Typography Rules

- Metric/KPI display numbers use JetBrains Mono at `text-2xl` (28px) maximum.
- Use positive letter-spacing only for uppercase label text. All other text: 0 or
  slightly negative tracking on display sizes.
- Do not use italic in UI. Italic is reserved for prose within log/result content.
- Do not scale monospace metrics above `text-2xl`. 28px is the ceiling.

---

## Spacing & Layout

### Grid

All spacing derives from a **4px base unit**. The scale:
`4 → 8 → 12 → 16 → 20 → 24 → 28 → 32 → 40 → 48 → 64`

### Spacing Conventions

- Inner component padding: `space-3` (12px) to `space-4` (16px)
- Between fields/rows: `space-3` (12px)
- Between sections/cards: `space-6` (24px)
- Page-level gutters: `content-gutter` (24px) on desktop

Use `--content-gutter` token on all page containers. Do not mix arbitrary
Tailwind padding values across components.

### Shell

```
Sidebar:   224px width, fixed left
Canvas:    flex-1, max-width 1440px content with content-gutter on both sides
```

### Page Anatomy

Prefer these layouts (in order of priority):

1. **Full-width table** with sticky column headers, filter toolbar above, pagination below
2. **Split pane**: config/form left (40%) + live preview or result right (60%)
3. **Two-column detail**: form fields left, context panel right
4. **Metric row + table** (dashboard): KPI strip at top spanning full width, table below

Do not create dashboard mosaics with 4+ card grids. Do not use hero sections. Do
not use full-bleed imagery. Do not use decorative dividers.

---

## Components

### Buttons

Three tiers:

**Primary** — deep slate navy fill (`#0F172A` light / `#38BDF8` dark), 36px height,
5px radius. Used once per major context. This is the "do the thing" button:
Start Crawl, Save to Memory, Export. Not every panel needs one.

**Secondary** — panel-raised fill with 1px border. Same height and radius as
primary. Used for supporting actions: Reset, Cancel, Download, Copy.

**Ghost** — transparent fill, text-secondary color. Used inside toolbars, filter
rows, and table actions. Compact horizontal padding (10px). Never use for
destructive actions.

**Danger** — danger-bg fill with danger text. Used for Delete, Clear History,
Reset Workspace. Always placed last in action groups.

Button rules:
- No glow shadows on any button state
- Active/pressed: `scale(0.98)` transform, 80ms duration
- Height is always 36px. Do not use tall "hero" buttons inside the app shell
- Never use accent-color fill for secondary or ghost buttons

### Toggle / Tab Selected State

Active nav/mode badges use accent background with accent-fg text (existing pattern).
Selected toggle buttons use a different treatment to distinguish "I am here" from
"this is active":
- `border: 1px solid accent`
- `background: accent-subtle`
- `color: text-primary`

This is available as the `.toggle-selected` utility class.

### Tables

Tables are the core component of this system.

**Header row**: canvas-alt fill, label typography (uppercase, JetBrains Mono 700,
0.12em tracking), 34px height, sticky on scroll.

**Body rows**: 40px height. Row hover applies accent-subtle wash. Selected row
applies accent-subtle fill + 2px solid accent left border.

**URL / domain cells**: Always mono-data type. Truncate with ellipsis.

**Status cells**: Status dot (6px circle) + badge text side by side.

### Badges

Compact, `rounded-sm` (3px) not pill-shaped. Badge text is label typography
(uppercase, JetBrains Mono 700, 0.12em tracking, text-sm size).

### KPI / Metric Cards

Metric values use JetBrains Mono 700 at `text-2xl` (28px) maximum. No sparklines
or decorative micro-charts unless they reflect real interactive data.

---

## Motion

Motion is functional. It communicates state change, not personality.

**Easing:** `cubic-bezier(0, 0, 0.2, 1)` — single fast curve for all transitions.

**Duration:** 100ms (`--transition-fast`) for all component-level transitions.

**Properties allowed:** `background-color`, `color`, `border-color`, `opacity`,
`transform` (scale only, never translate-y for hover float effects).

**No bounce easing.** No spring physics. No hover float (`translateY`). Pressed
state only: `scale(0.98)` at 80ms ease-in.

---

## Anti-Patterns

These are disqualifying:

### Color Anti-Patterns

- ❌ Gradient fills on any interactive element, surface, or background
- ❌ Radial gradients used as ambient background lighting
- ❌ Orange, amber, or warm accent colors for interactive elements
- ❌ Colored box-shadow "glow" on buttons or cards
- ❌ Accent-tinted elevation shadows
- ❌ Using semantic colors (success, danger, warning) as decoration
- ❌ Semi-transparent accent fills on non-interactive structural elements

### Typography Anti-Patterns

- ❌ Using removed tokens: `text-2xs`, `text-md`, `text-3xl`, `text-4xl`
- ❌ Negative letter-spacing on labels or uppercase text
- ❌ Italic type in UI navigation or table content
- ❌ Displaying monospace metric values above `text-2xl` (28px)
- ❌ Using sans-serif for URLs, record counts, IDs, or timestamps
- ❌ Mixed font families beyond Outfit + JetBrains Mono
- ❌ Setting body font-size to anything other than `text-base`

### Layout Anti-Patterns

- ❌ Hero sections inside the app shell
- ❌ Dashboard card mosaics (4+ equal-weight cards in a grid)
- ❌ Nested cards (card inside card)
- ❌ Content wider than 1440px or without content-gutter
- ❌ Mixing arbitrary Tailwind padding instead of using spacing tokens

### Motion Anti-Patterns

- ❌ `translateY` hover float effects on buttons or cards
- ❌ Bounce or spring easing
- ❌ box-shadow transitions
- ❌ Animation duration above 220ms for component-level transitions

### Component Anti-Patterns

- ❌ Pill-heavy badges with `rounded-full` (use `rounded-sm` instead)
- ❌ Buttons taller than 36px inside the app shell
- ❌ Accent-colored secondary or ghost buttons
- ❌ Status communicated by color alone (must include text)
- ❌ KPI cards with decorative sparklines on placeholder data
- ❌ More than one primary button visible per panel at the same time

### The Root Rule

> **If it would look at home in a SaaS marketing landing page, it does not
> belong inside the CrawlerAI operator console.**
