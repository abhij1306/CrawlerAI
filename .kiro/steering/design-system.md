---
inclusion: fileMatch
fileMatchPattern: "frontend/**"
---

# Design System Steering

When editing frontend files, follow the design system defined in `docs/design.md`.

## Key constraints

- **No orange, amber, or warm accent colors.** The accent is deep slate navy (`#0F172A`) in light mode and sky blue (`#38BDF8`) in dark mode.
- **No glows, colored shadows, or radial gradients.** Elevation uses borders and surface color shifts only. All shadow tokens are `none`.
- **No hover translate-y effects on buttons.** Use opacity/scale for pressed states.
- **No card gradients.** Cards use flat `var(--bg-panel)` backgrounds.
- **Buttons are unified.** Primary = navy fill, secondary = border, ghost = transparent. Height = 36px.
- **Type scale is 5 tokens only:** `text-xs`, `text-sm`, `text-base`, `text-lg`, `text-xl`. Do not use removed tokens (`text-2xs`, `text-md`, `text-2xl`, `text-3xl`, `text-4xl`).
- **Body font-size is `var(--text-base)` (15px).** Do not change it.
- **Fonts: Outfit + JetBrains Mono.** No other font families.
- **Metric/KPI numbers max at `text-xl` (22px).** Never larger.
- **Use `--content-gutter` for page container padding.** Do not mix arbitrary Tailwind padding values.

Reference: #[[file:docs/design.md]]
