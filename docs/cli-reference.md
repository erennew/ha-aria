# ARIA CLI Reference

Reference doc for CLAUDE.md. All commands route through the unified `aria` entry point (`aria/cli.py`).

| Command | What it does |
|---------|-------------|
| `aria serve` | Start real-time hub + dashboard (replaces `bin/ha-hub.py`) |
| `aria full` | Full daily pipeline: snapshot → predict → report |
| `aria snapshot` | Collect current HA state snapshot |
| `aria predict` | Generate predictions from latest snapshot |
| `aria score` | Score yesterday's predictions against actuals |
| `aria retrain` | Retrain ML models from accumulated data |
| `aria meta-learn` | LLM meta-learning to tune feature config |
| `aria check-drift` | Detect concept drift in predictions |
| `aria correlations` | Compute entity co-occurrence correlations |
| `aria suggest-automations` | Generate HA automation YAML via LLM |
| `aria prophet` | Train Prophet seasonal forecasters |
| `aria occupancy` | Bayesian occupancy estimation |
| `aria power-profiles` | Analyze per-outlet power consumption |
| `aria sequences train` | Train Markov chain model from logbook sequences |
| `aria sequences detect` | Detect anomalous event sequences |
| `aria snapshot-intraday` | Collect intraday snapshot (used internally by hub) |
| `aria sync-logs` | Sync HA logbook to local JSON |
| `aria discover-organic` | Run organic capability discovery (Layer 1 + Layer 2) |
| `aria capabilities list` | List all registered capabilities (--layer, --status, --verbose) |
| `aria capabilities verify` | Validate all capabilities against tests/config/deps |
| `aria capabilities export` | Export capability registry as JSON |

## Support Scripts

| Script | What it does |
|--------|-------------|
| `bin/check-ha-health.sh` | Validates HA connectivity + core stats before batch timers run (used by all snapshot/training systemd timers) |

Engine commands delegate to `aria.engine.cli` with old-style flags internally.
