# Dashboard Build & CSS Reference

Reference doc for CLAUDE.md.

## Dashboard (Preact SPA)

**Stack:** Preact 10 + @preact/signals + Tailwind CSS v4 + uPlot, bundled with esbuild
**Location:** `aria/dashboard/spa/`
**Design language:** `docs/design-language.md` — MUST READ before creating or modifying UI components
**Full component reference:** `docs/dashboard-components.md`
**Pages (13):** Home, Discovery, Capabilities, Data Curation, Intelligence, Predictions, Patterns, Shadow Mode, ML Engine, Automations, Settings, Guide

## Build & CSS

```bash
# Rebuild SPA after JSX changes (REQUIRED — dist/bundle.js is gitignored)
cd aria/dashboard/spa && npm run build
```

**CSS rules:**
- All colors via CSS custom properties in `index.css` — NEVER hardcode hex values in JSX
- Use `.t-frame` with `data-label` for content cards (NOT `.t-card` — legacy)
- Use `class` attribute (Preact), NOT `className`
- Tailwind via pre-built `bundle.css` — arbitrary values may not exist. Use inline `style` for non-standard values.
- uPlot renders on `<canvas>` — CSS variables must be resolved via `getComputedStyle()` before passing to uPlot
