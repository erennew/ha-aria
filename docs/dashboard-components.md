# ARIA Dashboard Components

## In Plain English

This is the parts catalog for ARIA's web interface. Each piece listed here is a reusable building block -- like LEGO bricks that snap together to form the pages you see in your browser. Some show charts, some show numbers, some handle navigation.

## Why This Exists

The dashboard has 5 primary OODA destinations and 6 system pages, built from dozens of shared components. Without a single reference listing what each component does, where it lives, and what data it needs, anyone modifying the UI risks duplicating work or breaking an existing page. This document is the source of truth for the dashboard's visual vocabulary, so every page stays consistent and new features reuse what already exists.

**Stack:** Preact 10 + @preact/signals + Tailwind CSS v4 + uPlot, bundled with esbuild
**Location:** `aria/dashboard/spa/`
**Design language:** `docs/design-language.md` — MUST READ before creating or modifying UI components
**Design doc:** `docs/plans/2026-02-13-aria-ui-redesign-design.md`

## Pages

**Primary OODA destinations (5):** Home (anomaly/accuracy/recommendation summary + OODA cards + Sankey), Observe (live presence + activity + current metrics), Understand (anomalies, drift, patterns, baselines, correlations, forecasts), Decide (automation recommendations with approve/reject/defer), System (nav entry into system pages)

**System pages (6):** Discovery, Capabilities, ML Engine, Data Curation, Validation (on-demand test suite), Settings

**Legacy pages (accessible via redirects):** Intelligence → Observe or Understand, Predictions → Understand, Patterns → Understand, Shadow Mode → Understand, Automations → Decide, Presence → Observe

## Sidebar

3 responsive variants — phone bottom tab bar (<640px), tablet icon rail (640-1023px), desktop full sidebar (1024px+). Primary tabs: Home, Observe, Understand, Decide. System pages collapsible under a "System" section header. Phone "More" sheet exposes system pages.

## Reusable Components

| Component | File | Purpose |
|-----------|------|---------|
| `PageBanner` | `components/PageBanner.jsx` | ASCII pixel-art "ARIA ✦ PAGE_NAME" SVG header with optional subtitle — first element on every page. `.page-banner-sh` class applies piOS terminal styling: dark bg, left accent border, CRT scanline stripes (::before), horizontal scan beam sweep (::after), phosphor glow animation on SVG text. Stronger glow in dark mode. |
| `CollapsibleSection` | `components/CollapsibleSection.jsx` | Expand/collapse with cursor-as-affordance (cursor-active/working/idle) |
| `HeroCard` | `components/HeroCard.jsx` | Large monospace KPI with optional sparkline (`sparkData`/`sparkColor` props). SUPERHOT freshness states (`data-sh-freshness`) applied for stale/live data. |
| `TimeChart` | `components/TimeChart.jsx` | uPlot wrapper — full mode (`<figure>`) or `compact` sparkline mode (no axes) |
| `StatsGrid` | `components/StatsGrid.jsx` | Grid of labeled values with `.t-bracket` labels |
| `AriaLogo` | `components/AriaLogo.jsx` | SVG pixel-art logo |
| `UsefulnessBar` | `components/UsefulnessBar.jsx` | Horizontal percentage bar with color thresholds (green/orange/red) |
| `CapabilityDetail` | `components/CapabilityDetail.jsx` | Expanded capability view: 5 usefulness bars, metadata, temporal patterns, entity list |
| `DiscoverySettings` | `components/DiscoverySettings.jsx` | Settings panel: autonomy mode, naming backend, thresholds, Save/Run Now |
| `InlineSettings` | `components/InlineSettings.jsx` | Contextual settings panel embedded on OODA pages. Accepts `categories` prop (array of config category strings). Loads only matching params from `/api/config`, renders sliders/toggles/selects with debounced save + reset. Hidden when no matching configs load. |
| `PipelineStatusBar` | `components/PipelineStatusBar.jsx` | Compact one-line bar on Home showing pipeline stage, shadow stage, and WebSocket status. Applies `data-sh-effect="glitch"` on module failure, `data-sh-mantra="OFFLINE"` when WS is down. |
| `OodaSummaryCard` | `components/OodaSummaryCard.jsx` | Clickable summary card linking to each OODA destination. Props: `title`, `subtitle`, `metric`, `metricLabel`, `href`, `accentColor`. On click, plays pure CSS shatter animation (`.sh-card-shatter` — brightness flash → desaturate → scale down → red glow → fade out, 500ms) then navigates via hash. Used in the 3-card grid on Home. |

## Home Page Layout

3 HeroCards (anomalies, recommendations, 7-day prediction accuracy) → PipelineStatusBar → 3 OodaSummaryCards (Observe/Understand/Decide) → PipelineSankey

Data sources (4 fetched in parallel + 4 from cache): `/health`, `/api/ml/anomalies`, `/api/shadow/accuracy`, `/api/pipeline` + cache keys `intelligence`, `activity_summary`, `entities`, `automation_suggestions`

## OODA Page Content

| Page | What's on it |
|------|-------------|
| Observe | PresenceCard, HomeRightNow, ActivitySection, InlineSettings (category: 'Activity Monitor') |
| Understand | AnomalyAlerts, PredictionsVsActuals, DriftStatus, ShapAttributions, Baselines, TrendsOverTime, Correlations, PatternsList, InlineSettings (categories: 'Anomaly Detection', 'Shadow Mode', 'Drift Detection', 'Forecaster') |
| Decide | HeroCards (pending/approved/rejected counts), RecommendationCard list with approve/reject/defer actions |

## Intelligence Sub-Components

Located in `aria/dashboard/spa/src/pages/intelligence/`:

| Component | What it shows |
|-----------|---------------|
| `LearningProgress` | Data maturity bar (collecting → baselines → ML training → ML active) |
| `HomeRightNow` | Current intraday metrics vs baselines with color-coded deltas |
| `ActivitySection` | Activity monitor: swim-lane timeline, occupancy, event rates, patterns, anomalies, WS health |
| `TrendsOverTime` | 30-day small multiples (one chart per metric) + intraday charts |
| `PredictionsVsActuals` | Predicted vs actual metric comparison |
| `Baselines` | Day × metric heatmap grid with color intensity = value |
| `DailyInsight` | LLM-generated daily insight text |
| `Correlations` | Diverging-color correlation matrix heatmap (positive=accent, negative=purple) |
| `SystemStatus` | Run log, ML model scores (R2/MAE), meta-learning applied suggestions |
| `Configuration` | Current intelligence engine config (deprecated — replaced by Settings page) |
| `DriftStatus` | Per-metric drift detection status (Page-Hinkley + ADWIN scores) |
| `AnomalyAlerts` | IsolationForest + autoencoder anomaly alerts |
| `ShapAttributions` | SHAP feature attribution horizontal bar chart |
| `utils.jsx` | Shared helpers: Section, Callout, durationSince, describeEvent, EVENT_ICONS, DOMAIN_LABELS |
