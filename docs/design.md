# CrawlerAI Design System

**`frontend/app/globals.css` is the only source of truth.** This document explains the
rules behind it; when the two disagree, the stylesheet wins and this file is the bug.

Two scripts enforce the parts that can be checked mechanically. Both run in
`npm run check:policy` and in CI:

| Script | Enforces |
|---|---|
| `frontend/scripts/check-typography-scale.mjs` | No off-ladder font sizes anywhere |
| `frontend/scripts/check-contrast.mjs` | The contrast contract, and that borders have not drifted |
| `frontend/scripts/check-token-escapes.mjs` | No raw `bg-[var(--…)]`-style token escapes |

Stack: React 19 + Vite, Tailwind CSS v4 (no config file — the theme lives in
`@theme inline` inside `globals.css`), Radix primitives, CVA, Geist / Geist Mono.
Dark mode is a `data-theme` attribute on `<html>`, set pre-paint by
`frontend/public/theme-init.js` and toggled by `components/ui/theme-toggle.tsx`.

---

## Typography

An even six-step ladder on a **14px baseline**. Every size and every leading sits on
the 4px grid. There is no 10px or 11px tier — `text-xs` and `text-2xs` were removed
from the theme outright, so referencing them produces no utility at all.

| Token | Size | Leading | Used for |
|---|---|---|---|
| `--text-sm` | 12px | 16px | Labels, captions, table text, secondary body |
| `--text-base` | 14px | 20px | **Baseline** — body, controls, nav |
| `--text-lg` | 16px | 24px | Section headings |
| `--text-xl` | 20px | 28px | Page headings |
| `--text-2xl` | 24px | 32px | Card and auth titles |
| `--text-3xl` | 32px | 40px | Hero metrics |

The leading companions are declared inside `@theme` as `--text-*--line-height`. This
matters: without them Tailwind keeps its own defaults, and the `.text-*` utilities and
the `.type-*` classes drift to different line-heights for the same size.

**Interactive text sits at the baseline, reading text may go below it.** Buttons,
inputs, dropdowns, nav, and field labels are 14px; captions, table cells, and secondary
body are 12px. Table header and body now share 12px, so the header is distinguished by
weight, tracking, and uppercase rather than by size.

Semantic classes (`.type-body`, `.type-caption`, `.type-label`, `.type-control`,
`.type-metric`, …) are defined once in `globals.css` and are preferred over raw
utilities in feature code.

---

## Colour

### The contract

- **Text tiers.** `--text-primary`, `--text-secondary`, and `--text-muted` clear
  **4.5:1 on every surface they appear on**. `--text-subtle` is
  **placeholder-and-disabled only** — WCAG-exempt, held to 3:1 for legibility. A
  visible label never uses `--text-subtle`; if you reach for it on real text, use
  `--text-muted`.
- **Borders are frozen.** No component gains a border it does not already have, and no
  existing border is strengthened. The contrast gate asserts the three border tokens
  still hold their exact values, so this is enforced rather than merely agreed.
- **Separation is fill first, shadow second.**
  - *Colour elevation* — a surface that must read as distinct gets a distinct fill.
    Form controls sit on the recessed `--bg-well`, so an input is identified by being
    inset in its card rather than by a hairline.
  - *Shadow elevation* — anything that floats (dialog, dropdown, tooltip) is separated
    by `--shadow-elevated` / `--shadow-modal`, never by an edge.

### Elevation ladder

```
--bg-well  (recessed: inputs, code, terminal)
   ↓
--bg-base  (page canvas)  →  --bg-alt  →  --bg-panel  (card)  →  --bg-elevated (floating)
```

Light theme keeps `--bg-panel` and `--bg-elevated` both white and separates them purely
with shadow. Dark theme separates them by fill, which is why its surface steps are wider.

### Values

| Token | Light | Dark |
|---|---|---|
| `--bg-base` | `#f7f7f8` | `#0d0e11` |
| `--bg-alt` | `#f1f1f3` | `#131519` |
| `--bg-panel` | `#ffffff` | `#17191f` |
| `--bg-elevated` | `#ffffff` | `#1d1f26` |
| `--bg-well` | `#e9e9ed` | `#24272f` |
| `--border-subtle` | `#f0f0f1` | `#1c1e24` |
| `--border` | `#e7e7e9` | `#23262d` |
| `--border-strong` | `#d9d9dc` | `#2f323b` |
| `--text-primary` | `#18181b` | `#ececf1` |
| `--text-secondary` | `#3f3f46` | `#b7b9c2` |
| `--text-muted` | `#5f6168` | `#8d919d` |
| `--text-subtle` | `#83848b` | `#7d818d` |
| `--accent` | `#5e6ad2` | `#5e6ad2` |

The accent is unchanged in both themes: white on `#5e6ad2` is **4.70:1**, which clears
AA for normal text. (An older comment in the stylesheet claimed 4.43:1 and was wrong.)

### Known gap

With borders frozen, control boundaries do not reach the WCAG 1.4.11 non-text threshold
of 3:1. Meeting it would take roughly a `#9c9ca6` hairline on white — exactly the
heavier border the constraint rules out. The recessed `--bg-well` fill carries the
boundary instead, well beyond the 1.19:1 a bare border gave. Every text contrast target
is met in full. This is a deliberate, documented trade-off, not an oversight.

---

## Spacing, radii, controls

- **Spacing** is a 4px grid: `--space-1` (4px) through `--space-20` (80px).
  `--content-gutter` is `--space-6`, dropping to `--space-4` under 480px.
- **Radii**: `--radius-xs` 4px, `sm` 6px, `md` 8px, `lg` 10px, `xl`/`2xl` 12px,
  `--radius-full` 9999px.
- **Control heights**: `--control-height-sm` 28px, `--control-height` 32px,
  `--control-height-lg` 36px.
- **Table**: 12px body and header, `--table-header-height` 32px,
  `--table-row-height` 38px. `records-table.tsx` mirrors these in TS constants and a
  unit test keeps the two in sync — change both together.

---

## Components

Shared primitives live in `frontend/components/ui/` (hand-rolled CVA + Radix, not
shadcn CLI scaffolding), composed patterns in `frontend/components/ui/patterns/`, and
the app shell in `frontend/components/layout/`.

Use the bridged semantic utilities — `bg-panel`, `text-muted`, `border-border`,
`shadow-card` — rather than `bg-[var(--bg-panel)]`. The token-escape gate rejects the
latter.
