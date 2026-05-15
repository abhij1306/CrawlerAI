---
version: beta
name: CrawlerAI Console
description: Operator-first crawl and extraction workspace using PostHog warmth, HashiCorp rigor, and Airtable-style data ergonomics across light and dark themes.
inspiration:
  primary: PostHog (warm surfaces, olive text, flat depth)
  structural: HashiCorp (enterprise grid, whisper shadows, tight headings)
  dataModel: Airtable (dense tables, field filters, record ergonomics)
colors:
  light:
    canvas: "#FAFAFA"
    canvasAlt: "#F5F5F5"
    panel: "#FFFFFF"
    panelStrong: "#F0F0F0"
    sidebar: "#FAFAFA"
    border: "#E5E5E5"
    borderStrong: "#D4D4D4"
    text: "#111111"
    textSecondary: "#4E4E4E"
    textMuted: "#888888"
    accent: "#111111"
    accentHover: "#333333"
    accentSubtle: "#F0F0F0"
    accentFg: "#FFFFFF"
    controlDark: "#111111"
    controlDarkHover: "#333333"
    success: "#16A34A"
    warning: "#CA8A04"
    danger: "#DC2626"
    info: "#4F46E5"
  dark:
    canvas: "#0C0D0E"
    canvasAlt: "#131416"
    panel: "#191A1C"
    panelStrong: "#1F2023"
    sidebar: "#111214"
    border: "rgba(255, 255, 255, 0.08)"
    borderStrong: "rgba(255, 255, 255, 0.14)"
    text: "#F0F1F3"
    textSecondary: "#B0B4BC"
    textMuted: "#6B7080"
    accent: "#7C8AFF"
    accentHover: "#9BA5FF"
    accentSubtle: "rgba(124, 138, 255, 0.12)"
    accentFg: "#0C0D0E"
    controlDark: "#F0F1F3"
    controlDarkHover: "#FFFFFF"
    success: "#34D058"
    warning: "#E0A63A"
    danger: "#F97066"
    info: "#7C8AFF"
typography:
  sans: IBM Plex Sans
  mono: JetBrains Mono
  pageTitle:
    size: 1.5rem
    weight: 700
    lineHeight: 1.15
    letterSpacing: 0
  sectionTitle:
    size: 1rem
    weight: 700
    lineHeight: 1.3
    letterSpacing: 0
  body:
    size: 0.875rem
    weight: 400
    lineHeight: 1.5
    letterSpacing: 0
  control:
    size: 0.875rem
    weight: 600
    lineHeight: 1.25
    letterSpacing: 0
  label:
    size: 0.75rem
    weight: 700
    lineHeight: 1.35
    letterSpacing: 0.06em
  metric:
    family: JetBrains Mono
    size: 1.875rem
    weight: 700
    lineHeight: 1
    letterSpacing: 0
radii:
  sm: 2px
  md: 4px
  lg: 6px
  xl: 8px
spacing:
  unit: 8px
  control: 32px
  topbar: 48px
  sidebar: 224px
  sidebarCollapsed: 72px
shadows:
  none: "none"
  xs: "0 1px 2px rgba(35, 37, 29, 0.05)"
  sm: "0 3px 8px rgba(35, 37, 29, 0.07)"
  note: "Shadows are structural, not decorative. No glows, no colored shadows, no accent-tinted elevation."
---

## Visual Thesis

CrawlerAI is a serious internal data console with refined, minimal aesthetics. ElevenLabs supplies the clean white canvas, subtle multi-layer shadows, and near-black accent. Linear supplies the dark mode: near-black canvas, luminance-stepped surfaces, and cool-neutral palette. Both modes share dense table ergonomics and compact, functional components.

This is not a marketing system. It is a workspace for operators watching crawls, comparing extraction output, reviewing selectors, and fixing bad data fast.

## Theme Model

Light mode is ElevenLabs-inspired: clean white surfaces (`#FAFAFA` base, `#FFFFFF` panels), near-black text, subtle neutral borders (`#E5E5E5`), and refined multi-layer shadows at sub-0.1 opacity. The accent is near-black (`#111111`) — buttons are dark, confident, minimal.

Dark mode is Linear-inspired: near-black canvas (`#0C0D0E`), cool-neutral text, semi-transparent white borders, and luminance-stepped surfaces. Accent is a muted indigo-violet (`#7C8AFF`) that provides clear interactive signal without warmth.

## Palette Rules

The accent color is dark navy in light mode and steel-blue in dark mode. It is used for: primary buttons, active navigation, focused fields, selected rows, and important state indicators.

Use sage and olive neutrals for most structure: borders, inactive nav, table headers, input backgrounds, toolbars, and passive metadata.

Use semantic colors only for runtime state. Success, warning, danger, and info must not become decoration.

No orange. No amber. No warm accent colors for interactive elements.

## Typography Rules

Use IBM Plex Sans for UI. Technical enough for developer tools, warmer than Inter. Use 700 weight for section titles, 600 for controls, 400 for body.

Use JetBrains Mono for run IDs, timestamps, URLs, logs, JSON, counts, table headers, and KPI values. Numeric data must align and scan.

Do not use negative tracking. This app is dense; letter spacing should stay calm and legible.

## Layout Rules

Keep the existing app shell: left sidebar, compact top bar, scrollable main workspace. Main content max width is `1440px`, with `24px` page padding.

Prefer record-list layouts, split panes, filter rows, compact toolbars, and table-first pages. Avoid hero sections, marketing banners, and decorative dashboard mosaics.

Cards are allowed only when they contain a real tool, repeated record, metric group, or workflow step. Do not nest cards inside cards.

## Component Rules

Buttons are compact. Primary buttons are dark (`#1E1F23`) in light mode. Secondary buttons use sage surfaces. Accent-variant buttons use the navy accent fill. No glow shadows on any button.

Inputs use sage-tinted fill, 1px border, 4px radius, and a clear accent focus ring. Labels stay literal.

Tables are core. Headers are compact, mono or bold sans, sticky where useful, and separated by warm borders. Row hover uses a faint accent wash. Selected rows use a left accent edge.

Badges are square-ish, not pill-heavy. Status copy must include text, not color alone.

## Depth & Elevation Rules

No glows. No colored shadows. No radial gradients on backgrounds.

Elevation is communicated through:
- Border containment (1px sage borders)
- Surface color shifts (canvas → panel → elevated)
- Whisper-level shadows at 5-7% opacity maximum

Cards use flat panel backgrounds. No `card-gradient`, no inset highlights, no decorative top-edge lines.

## Motion Rules

Motion is small and functional: 150-200ms transitions, pressed state on active, no decorative bouncing. Use transform and opacity only. No hover translate-y effects.

## Do

- Use warm parchment and sage surfaces in light mode.
- Use matte charcoal and olive-sage borders in dark mode.
- Keep accent scarce and meaningful (dark navy / steel-blue).
- Make data tables, filters, and logs first-class.
- Preserve keyboard-visible focus.
- Keep components compact and repeatable.
- Use flat backgrounds everywhere.

## Don't

- Do not use orange, amber, or warm accent colors.
- Do not add glows, colored shadows, or radial gradients.
- Do not add large rounded cards.
- Do not build a landing page inside the app shell.
- Do not use gradients as the main identity.
- Do not make every button accent-colored.
- Do not hide state in color alone.
- Do not add hover translate-y ("float up") effects on buttons.
