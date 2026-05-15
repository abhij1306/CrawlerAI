---
inclusion: fileMatch
fileMatchPattern: "frontend/**"
---

# Design System Steering

When editing frontend files, follow the design system defined in `docs/design.md`.

## Key constraints

- **No orange, amber, or warm accent colors.** The accent is near-black (`#111111`) in light mode and muted indigo (`#7C8AFF`) in dark mode.
- **No glows, colored shadows, or radial gradients.** Elevation uses borders and surface color shifts only.
- **No hover translate-y effects on buttons.** Use opacity/scale for pressed states.
- **No card gradients.** Cards use flat `var(--bg-panel)` backgrounds.
- **Buttons are unified.** Primary = dark surface, secondary = sage border, accent = navy fill. All use `shadow-xs` max.
- **Shadows are whisper-level.** 5-7% opacity, structural only.

Reference: #[[file:docs/design.md]]
