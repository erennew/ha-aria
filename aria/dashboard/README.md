# Dashboard — ARIA

Preact SPA for visualizing hub data, managing automations, and monitoring shadow mode.

## Stack

- **Framework**: Preact + Tailwind CSS
- **Bundler**: esbuild
- **State**: Preact signals (`store.js`)
- **Routing**: Client-side hash router (`app.jsx`)
- **Served by**: FastAPI `StaticFiles` mount at `/ui` (see `aria/hub/api.py`)

## Structure

```
dashboard/
├── __init__.py
├── README.md
└── spa/
    ├── package.json
    ├── package-lock.json
    ├── dist/               # esbuild output (gitignored)
    │   ├── index.html
    │   └── bundle.js
    └── src/
        ├── index.jsx       # Entry point
        ├── app.jsx         # Router + layout
        ├── store.js        # Preact signals state
        ├── api.js          # API client
        ├── index.css       # Global styles
        ├── preact-shim.js  # JSX pragma shim
        ├── components/     # Shared components (Sidebar, etc.)
        ├── hooks/          # Custom hooks
        └── pages/          # Page components
            └── intelligence/  # Split intelligence sub-components
```

## Build

```bash
cd aria/dashboard/spa
npx esbuild src/index.jsx --bundle --outfile=dist/bundle.js \
  --jsx-factory=h --jsx-fragment=Fragment --inject:src/preact-shim.js \
  --loader:.jsx=jsx --minify
```

## Access

- **Dashboard**: http://127.0.0.1:8001/ui/
- **WebSocket**: ws://127.0.0.1:8001/ws (live cache updates)

## Pages (12)

Sidebar organized by pipeline stage:

- **Home** — Pipeline flowchart with live status
- **Data Collection:** Discovery, Capabilities, Data Curation
- **Learning:** Intelligence, Predictions, Patterns
- **Actions:** Shadow Mode, Automations, Settings
- **Guide** — Interactive onboarding (linked from sidebar footer)

## Key Components

- `AriaLogo.jsx` — SVG pixel-art logo (used in Sidebar + Home + Guide)
- `Sidebar.jsx` — Nav with section headers, About section, WS status indicator

## CSS Note

Tailwind is pre-built into `bundle.css`. New utility classes (gradients, blurs, etc.) won't be available unless already in the bundle. Use inline `style` attributes for new visual effects.
