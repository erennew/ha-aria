# Changelog

All notable changes to ARIA will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- SVG pixel-art ARIA logo component matching README ASCII block letters
- Interactive Guide page — onboarding with learning timeline, key concepts, page guide, FAQ
- Dashboard screenshots in README (Home, Guide, Intelligence, Shadow Mode)

### Changed
- Sidebar reorganized by pipeline stage: Data Collection → Learning → Actions (with section headers)
- Sidebar footer now includes About section (version, description) and "How to Use ARIA" link
- Dashboard page count: 11 → 12 (added Guide)
- Page title updated to "ARIA — Adaptive Residence Intelligence Architecture"

### Removed
- Legacy Jinja2/htmx dashboard (routes.py, templates/, static/) — superseded by Preact SPA

## [1.0.0] - 2026-02-13

### Added
- Unified project combining ha-intelligence engine and ha-intelligence-hub dashboard
- Single `aria` CLI with subcommand dispatch
- 15 entity collectors for Home Assistant data
- ML prediction engine (GradientBoosting, RandomForest, IsolationForest, Prophet)
- Real-time WebSocket activity monitoring
- Shadow mode: predict-compare-score validation loop
- Interactive Preact + Tailwind dashboard
- Entity correlation analysis
- Markov chain sequence anomaly detection
- Bayesian occupancy estimation
- Power consumption profiling
- LLM-powered insights via Ollama
- CI/CD with GitHub Actions
- 578 tests (177 engine + 396 hub + 5 integration)
