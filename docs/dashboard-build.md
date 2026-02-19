# Dashboard Build & CSS Reference

Reference doc for CLAUDE.md.

## Dashboard (Preact SPA)

**Stack:** Preact 10 + @preact/signals + Tailwind CSS v4 + uPlot, bundled with esbuild
**Location:** `aria/dashboard/spa/`
**Design language:** `docs/design-language.md` — MUST READ before creating or modifying UI components
**Full component reference:** `docs/dashboard-components.md`
**Pages (5 primary OODA + 6 system):** Home, Observe, Understand, Decide — plus System group: Discovery, Capabilities, ML Engine, Data Curation, Validation, Settings
**Bundle size:** ~260kb (down from ~299kb pre-Phase 5)

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
