---
version: "1.1"
name: "CrawlerAI Belize/Horizon Console"
description: >
  High-density data-extraction workspace. Merges Gmail's structural efficiency,
  split-pane utility, and keyboard-first accessibility with SAP Fiori Horizon's
  neutral grey-blue light palette, charcoal dark palette, and clean typography.
colors:
  primary: "#32363a"
  secondary: "#55616b"
  tertiary: "#354a5f"
  neutral: "#eff3f6"
  surface: "#ffffff"
  on-surface: "#32363a"
  error: "#bb0000"

  light-canvas: "#eff3f6"
  light-panel: "#ffffff"
  light-border: "#d9d9d9"
  light-text-primary: "#32363a"
  light-text-secondary: "#55616b"
  light-accent: "#354a5f"

  dark-canvas: "#141414"
  dark-panel: "#1e1e1e"
  dark-border: "#333333"
  dark-text-primary: "#f3f4f6"
  dark-text-secondary: "#a1a1aa"
  dark-accent: "#38bdf8"

typography:
  headline-display:
    fontFamily: "Inconsolata"
    fontSize: "28px"
    fontWeight: "700"
    lineHeight: "1.0"
  headline-lg:
    fontFamily: "Source Sans 3"
    fontSize: "22px"
    fontWeight: "600"
    lineHeight: "1.2"
  headline-md:
    fontFamily: "Source Sans 3"
    fontSize: "17px"
    fontWeight: "600"
    lineHeight: "1.3"
  body-lg:
    fontFamily: "Source Sans 3"
    fontSize: "15px"
    fontWeight: "400"
    lineHeight: "1.45"
  body-md:
    fontFamily: "Source Sans 3"
    fontSize: "14px"
    fontWeight: "400"
    lineHeight: "1.45"
  body-sm:
    fontFamily: "Source Sans 3"
    fontSize: "13px"
    fontWeight: "400"
    lineHeight: "1.35"
  label-lg:
    fontFamily: "Inconsolata"
    fontSize: "13px"
    fontWeight: "700"
    lineHeight: "1.35"
    letterSpacing: "0.08em"
  label-md:
    fontFamily: "Inconsolata"
    fontSize: "11px"
    fontWeight: "700"
    lineHeight: "1.35"
    letterSpacing: "0.1em"
  label-sm:
    fontFamily: "Inconsolata"
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
  space-7: "28px"
  space-8: "32px"
  space-10: "40px"
  space-12: "48px"
  space-16: "64px"
  gutter: "20px"

rounded:
  none: "0px"
  xs: "2px"
  sm: "3px"
  md: "4px"
  lg: "4px"
  xl: "6px"
  "2xl": "8px"
  full: "9999px"

components:
  button-primary:
    backgroundColor: "{colors.light-accent}"
    textColor: "#ffffff"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "#2c3e53"

  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.light-text-primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    border: "1px solid {colors.light-border}"
    padding: "0 12px"
    height: "32px"
  button-secondary-hover:
    backgroundColor: "{colors.neutral}"

  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.light-text-primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
---

# Overview

CrawlerAI Console is an operator-first data workspace designed for high-density navigation, real-time extraction metrics, and rapid diagnostics. The design fuses the keyboard-first utility and data density of Gmail with clean, structured corporate control panel aesthetics.

It features three key pillars:
1. **Gmail-Style Layout Density**: Hairline borders, high row density (36px-40px rows), collapsible list sidebars, split-pane detail views, and multi-select actions.
2. **SAP Fiori-Style Colors**: Clean grey-blue layouts in light mode with navy accents, and charcoal-dark layout with sky-blue accents in dark mode.
3. **Keyboard & Search Focus**: Clean focus rings, command bar hints, and monospace data typography.

---

# Colors

### Light Mode (Horizon Morning Canvas & Shellbar Navy Accent)
*   **Canvas** (`#eff3f6`): A cool, grey-blue tinted canvas that reducing glare and frames interactive areas.
*   **Panel** (`#ffffff`): Pristine white background for cards, tables, panels, and detail sheets.
*   **Accent** (`#354a5f`): Solid shellbar navy for primary actions, active navigation states, and key interactive status cues.
*   **Borders** (`#d9d9d9`): 1px hairline dividers that map table rows and separate structural layout zones.

### Dark Mode (Neutral Graphite Canvas & Sky Blue Accent)
*   **Canvas** (`#141414`): Deep dark grey base representing the terminal environment.
*   **Panel** (`#1e1e1e`): Slate-charcoal elevated cards and panels.
*   **Accent** (`#38bdf8`): Sky blue for focus rings, running/healthy pipeline states, and active items.
*   **Borders** (`#333333`): Subdued border edges that prevent visual fatigue during long operator sessions.

---

# Typography

We use two typefaces:
*   **Source Sans 3** (Google Fonts — SAP Fiori open-source typeface) for all UI controls, navigation elements, headings, and instructional copy. It provides clean, geometric readability.
*   **Inconsolata** for data cells, status badges, URLs, JSON payloads, record counts, and run identifiers. Any item requiring vertical alignment or technical precision is rendered in monospace.

### Typography Scale
*   `headline-display` (`type-display`): 28px, bold, monospace. Used only for dashboard overview totals.
*   `headline-lg` (`type-heading-1`): 22px, semibold. Used for primary page titles.
*   `headline-md` (`type-heading-2`): 17px, semibold. Used for card titles and section headings.
*   `body-lg` (`type-body` / `type-heading-3`): 15px, regular (semibold for headings). Standard UI copy, form field input, buttons.
*   `body-md` (`type-body-sm`): 14px, regular. Table data, secondary UI chrome, sidebar navigation.
*   `body-sm` (`type-caption` / `type-caption-mono`): 13px, regular (bold for column headers / badges). Column headers, badge text, metadata hints, timestamps.

---

# Layout

The layout system is built on a **4px spacing grid** to maximize information density while maintaining clean grouping.

### Spacing Conventions
*   **Grid Base**: 4px (`--space-1`), 8px (`--space-2`), 12px (`--space-3`), 16px (`--space-4`), 20px (`--space-5`), 24px (`--space-6`), 28px (`--space-7`), 32px (`--space-8`).
*   **Content Gutter**: 20px (`--space-5`), used for layout padding page-wide.
*   **Gmail Row Height**: All table rows are strictly capped at `36px` to `40px` to fit 20+ records above the fold.
*   **Split Pane Design**: Detail views use a 40/60 split pane layout (sidebar list on the left, configuration and live execution preview on the right) rather than navigating away from the table.
*   **Max Containment**: Dashboard sections are contained within a maximum width of `1440px`.

---

# Elevation & Depth

*   **Flat Elevation**: We minimize drop shadows to avoid consumer-SaaS clutter.
*   **Border Separation**: Depth is achieved entirely through 1px border lines and alternating panel backgrounds.
*   **Atmospheric Shadow**: Modals and dropdowns use a single, highly diffused atmosphere shadow to lift them cleanly above the page canvas.

---

# Shapes

*   **Corner Radii**: We use sharp, technical shapes to communicate engineering precision.
    *   `xs` (2px): Checkboxes.
    *   `sm` (3px): Badges, mini status pills.
    *   `md` (4px): Standard buttons, input fields, dropdown triggers.
    *   `lg` (4px): Control panels, cards, table wraps.
    *   `xl` (6px): Dialog boxes, overlay popovers.
    *   `2xl` (8px): Container workspace widgets.
    *   `full` (9999px): Toggle switches, status dots only.

---

# Components

### Buttons
*   **Primary Button**: Filled with the active accent color (`#354a5f` light / `#38bdf8` dark). Standard height is 32px.
*   **Secondary Button**: Flat panel background with a 1px border.
*   **Ghost Button**: Transparent background. Hover state shows a subtle background tint (`accent-subtle`). Used for tab selectors, action toolbars, and search filters.

### Input Fields
*   **Text Inputs**: 1px border with a `md` (4px) corner radius. On focus, applies the theme's active accent color as the border.
*   **Checkboxes**: Crisp, custom checkboxes for multi-select table actions.

### Data Tables
*   **Table Header**: Light gray/dark slate background with Inconsolata uppercase tracking headers.
*   **Selected Row State**: Highlights with `accent-subtle` background wash.
*   **Interactive Row Actions**: Inline action buttons appear on row hover to minimize screen clutter.

---

# Do's and Don'ts

### Do's
*   **Do** display data-dense tables with sticky headers.
*   **Do** use Inconsolata for all numeric values, UUIDs, dates, and JSON keys.
*   **Do** keep interactive toolbars immediately above the data table they control.
*   **Do** support key shortcuts and display keyboard shortcuts inline.

### Don'ts
*   **Don't** use emojis in data tables, labels, or navigation headers.
*   **Don't** apply neon glowing shadows or bright gradient text.
*   **Don't** make table rows taller than 44px.
*   **Don't** hide essential metrics in accordion folders; place them in structural split columns.
