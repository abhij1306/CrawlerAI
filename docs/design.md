---
version: "1.0"
name: "CrawlerAI Gmail/Linear Console"
description: >
  High-density data-extraction workspace. Merges Gmail's structural efficiency,
  split-pane utility, and keyboard-first accessibility with Linear's clean technical
  aesthetics, sharp typography, and graphite surfaces.
colors:
  primary: "#0f172a"
  secondary: "#475569"
  tertiary: "#4f46e5"
  neutral: "#f8fafc"
  surface: "#ffffff"
  on-surface: "#0f172a"
  error: "#ef4444"

  light-canvas: "#f8fafc"
  light-panel: "#ffffff"
  light-border: "#e2e8f0"
  light-text-primary: "#0f172a"
  light-text-secondary: "#475569"
  light-accent: "#4f46e5"

  dark-canvas: "#141414"
  dark-panel: "#1e1e1e"
  dark-border: "#333333"
  dark-text-primary: "#f3f4f6"
  dark-text-secondary: "#a1a1aa"
  dark-accent: "#38bdf8"

typography:
  headline-display:
    fontFamily: "Geist"
    fontSize: "24px"
    fontWeight: "600"
    lineHeight: "1.2"
  headline-lg:
    fontFamily: "Geist"
    fontSize: "20px"
    fontWeight: "600"
    lineHeight: "1.2"
  headline-md:
    fontFamily: "Geist"
    fontSize: "16px"
    fontWeight: "600"
    lineHeight: "1.3"
  body-lg:
    fontFamily: "Geist"
    fontSize: "15px"
    fontWeight: "400"
    lineHeight: "1.55"
  body-md:
    fontFamily: "Geist"
    fontSize: "14px"
    fontWeight: "400"
    lineHeight: "1.5"
  body-sm:
    fontFamily: "Geist"
    fontSize: "13px"
    fontWeight: "400"
    lineHeight: "1.4"
  label-lg:
    fontFamily: "JetBrains Mono"
    fontSize: "13px"
    fontWeight: "700"
    lineHeight: "1.35"
    letterSpacing: "0.08em"
  label-md:
    fontFamily: "JetBrains Mono"
    fontSize: "11px"
    fontWeight: "700"
    lineHeight: "1.35"
    letterSpacing: "0.1em"
  label-sm:
    fontFamily: "JetBrains Mono"
    fontSize: "10px"
    fontWeight: "700"
    lineHeight: "1.35"
    letterSpacing: "0.12em"

spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "20px"
  space-6: "24px"
  space-8: "32px"
  space-12: "48px"
  gutter: "24px"

rounded:
  none: "0px"
  sm: "3px"
  md: "4px"
  lg: "8px"
  xl: "12px"
  full: "9999px"

components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.surface}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "#4338ca"

  button-secondary:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "#e2e8f0"

  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
    height: "36px"
---

# Overview

CrawlerAI Console is an operator-first data workspace designed for high-density navigation, real-time extraction metrics, and rapid diagnostics. The design fuses the keyboard-first utility and data density of Gmail with the sleek, developer-oriented aesthetics of Linear.

It features three key pillars:
1. **Gmail-Style Layout Density**: Hairline borders, high row density (36px-40px rows), collapsible list sidebars, split-pane detail views, and multi-select actions.
2. **Linear-Style Dark Mode & Accents**: Rich charcoal backgrounds, tight borders, sky-blue status markers in dark mode, and a signature violet/indigo accent in light mode.
3. **Keyboard & Search Focus**: Clean focus rings, command bar hints, and monospace data typography.

---

# Colors

### Light Mode (Warm Canvas & Rich Indigo Accent)
*   **Canvas** (`#f8fafc`): A soft, slate-tinted canvas that reduces glare and frames interactive areas.
*   **Panel** (`#ffffff`): Pristine white background for cards, tables, panels, and detail sheets.
*   **Accent** (`#4f46e5`): Rich indigo for primary actions, active navigation states, and key interactive status cues.
*   **Borders** (`#e2e8f0`): 1px hairline dividers that map table rows and separate structural layout zones.

### Dark Mode (Graphite Canvas & Sky Blue Accent)
*   **Canvas** (`#141414`): Deep dark grey base representing the terminal environment.
*   **Panel** (`#1e1e1e`): Slate-charcoal elevated cards and panels.
*   **Accent** (`#38bdf8`): Sky blue for focus rings, running/healthy pipeline states, and active items.
*   **Borders** (`#333333`): Subdued border edges that prevent visual fatigue during long operator sessions.

---

# Typography

We use two typefaces:
*   **Geist** (or system fallback sans-serif) for all UI controls, navigation elements, headings, and instructional copy. It provides clean, geometric readability without calling attention to itself.
*   **JetBrains Mono** for data cells, status badges, URLs, JSON payloads, record counts, and run identifiers. Any item requiring vertical alignment or technical precision is rendered in monospace.

### Typography Scale
*   `headline-display`: 24px, semibold. Used only for dashboard overview totals.
*   `headline-lg`: 20px, semibold. Used for primary page titles.
*   `headline-md`: 16px, semibold. Used for section headings and card titles.
*   `body-lg`: 15px, regular. Used for instructional text and documentation.
*   `body-md`: 14px, regular. Standard UI copy and form field text.
*   `body-sm`: 13px, regular. Used for details, secondary labels, and meta captions.
*   `label-lg`: 13px, bold, monospace uppercase. Column headers.
*   `label-md`: 11px, bold, monospace uppercase. Badge text and settings groups.
*   `label-sm`: 10px, bold, monospace uppercase. Tiny settings metadata labels.

---

# Layout

The layout system is built on a **4px spacing grid** to maximize information density while maintaining clean grouping.

### Spacing Conventions
*   **Grid Base**: 4px (`--space-1`), 8px (`--space-2`), 12px (`--space-3`), 16px (`--space-4`), 24px (`--space-6`), 32px (`--space-8`).
*   **Gmail Row Height**: All table rows are strictly capped at `36px` to `40px` to fit 20+ records above the fold.
*   **Split Pane Design**: Detail views use a 40/60 split pane layout (sidebar list on the left, configuration and live execution preview on the right) rather than navigating away from the table.
*   **Max Containment**: Dashboard sections are contained within a maximum width of `1440px`.

---

# Elevation & Depth

*   **Flat Elevation**: We minimize drop shadows to avoid consumer-SaaS clutter.
*   **Border Separation**: Depth is achieved entirely through 1px border lines and alternating panel backgrounds.
*   **Atmospheric Shadow**: Modals and dropdowns use a single, highly diffused atmosphere shadow (`0 10px 15px -3px rgba(0, 0, 0, 0.04)`) to lift them cleanly above the page canvas.

---

# Shapes

*   **Corner Radii**: We use sharp, technical shapes to communicate engineering precision.
    *   `sm` (3px): Badges, mini status pills.
    *   `md` (4px): Standard buttons, input fields, and checkboxes.
    *   `lg` (8px): Control panels, filter headers, and table wraps.
    *   `xl` (12px): Main screen cards and dialog boxes.
    *   `full` (9999px): Toggle switches only.

---

# Components

### Buttons
*   **Primary Button**: Filled with the active accent color (`#4f46e5` light / `#38bdf8` dark). Standard height is 36px. Employs a tactile `-1px translateY` hover transition.
*   **Secondary Button**: Flat panel background with a 1px border.
*   **Ghost Button**: Transparent background. Hover state shows a subtle background tint (`accent-subtle`). Used for tab selectors, action toolbars, and search filters.

### Input Fields
*   **Text Inputs**: 1px border with a `md` (4px) corner radius. On focus, applies the theme's active accent color as the border with a 2px offset ring.
*   **Checkboxes**: Crisp, custom checkboxes for multi-select table actions.

### Data Tables
*   **Table Header**: Light gray/dark slate background with JetBrains Mono uppercase tracking headers.
*   **Selected Row State**: Highlights with `accent-subtle` background wash and a 2px solid left accent border indicator.
*   **Interactive Row Actions**: Inline action buttons appear on row hover to minimize screen clutter.

---

# Do's and Don'ts

### Do's
*   **Do** display data-dense tables with sticky headers.
*   **Do** use JetBrains Mono for all numeric values, UUIDs, dates, and JSON keys.
*   **Do** keep interactive toolbars immediately above the data table they control.
*   **Do** support key shortcuts and display keyboard shortcuts inline (e.g. `⌘K`).

### Don'ts
*   **Don't** use emojis in data tables, labels, or navigation headers.
*   **Don't** apply neon glowing shadows or bright gradient text.
*   **Don't** make table rows taller than 44px.
*   **Don't** hide essential metrics in accordion folders; place them in structural split columns.
