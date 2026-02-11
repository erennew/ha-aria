# HA Intelligence Hub

> **Adaptive intelligence layer for Home Assistant — Phase 2**
>
> Dynamic capability discovery + ML predictions + pattern recognition + automation generation

## Overview

The HA Intelligence Hub is a modular, hub-and-spoke architecture that extends Home Assistant with adaptive intelligence. It discovers capabilities dynamically, trains ML models for predictions, recognizes behavioral patterns using LLMs, and generates automation proposals.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Intelligence Hub                        │
│  ┌─────────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │   Cache     │  │   API    │  │  Event Broadcasting  │  │
│  │  (SQLite)   │  │ (FastAPI)│  │     (WebSocket)      │  │
│  └─────────────┘  └──────────┘  └──────────────────────┘  │
│                          │                                  │
│  ┌───────────────────────┴──────────────────────────────┐  │
│  │                    Modules                           │  │
│  │  ┌──────────────┐  ┌──────────┐  ┌────────────────┐ │  │
│  │  │  Discovery   │  │   ML     │  │   Patterns     │ │  │
│  │  └──────────────┘  │  Engine  │  └────────────────┘ │  │
│  │  ┌──────────────┐  └──────────┘  ┌────────────────┐ │  │
│  │  │ Orchestrator │                │   Dashboard    │ │  │
│  │  └──────────────┘                └────────────────┘ │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                ┌─────────┴─────────┐
                │  Home Assistant   │
                │  (via REST + WS)  │
                └───────────────────┘
```

### Modules

1. **Discovery** - Scans HA for entities, devices, capabilities (runs every 24h)
2. **ML Engine** - Trains models for state prediction using scikit-learn (weekly retraining)
3. **Pattern Recognition** - Detects behavioral patterns via LLM (Ollama qwen2.5:7b)
4. **Orchestrator** - Generates and manages automation proposals
5. **Dashboard** - Web UI for viewing predictions, patterns, and approving automations

## Quick Start

### Prerequisites

- Python 3.12+
- Home Assistant instance (accessible via network)
- Environment variables: `HA_URL`, `HA_TOKEN` (in `~/.env`)

### Installation

```bash
# Clone repo
cd ~/Documents/projects/ha-intelligence-hub-phase2

# Create virtualenv
python3 -m venv venv
. venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run Hub

```bash
# Source environment
. ~/.env

# Start hub (default: http://localhost:8000)
./venv/bin/python bin/ha-hub.py

# Or specify port and log level
./venv/bin/python bin/ha-hub.py --port 8001 --log-level DEBUG
```

### Access Dashboard

Navigate to: `http://localhost:8000/ui`

Dashboard pages:
- `/ui` - Home (system health, recent events)
- `/ui/discovery` - Discovered capabilities and entities
- `/ui/capabilities` - Capability details and statistics
- `/ui/predictions` - ML predictions and confidence scores
- `/ui/patterns` - Detected behavioral patterns
- `/ui/automations` - Automation proposals (approve/reject)
- `/ui/insights` - Cross-module insights and correlations

## API Reference

### Health Check

```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "hub": {
    "running": true,
    "modules_count": 5,
    "tasks_count": 2
  },
  "modules": {
    "discovery": { "registered": true },
    "ml_engine": { "registered": true },
    "patterns": { "registered": true },
    "orchestrator": { "registered": true }
  },
  "cache": {
    "categories": ["capabilities", "entities", "ml_predictions", "patterns"]
  },
  "timestamp": "2026-02-11T..."
}
```

### Cache API

```bash
# Get capabilities
curl http://localhost:8000/api/cache/capabilities

# Get ML predictions
curl http://localhost:8000/api/cache/ml_predictions

# Get detected patterns
curl http://localhost:8000/api/cache/detected_patterns

# Get automation proposals
curl http://localhost:8000/api/cache/automation_proposals
```

### WebSocket Events

Connect to `ws://localhost:8000/ws` to receive real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'cache_updated') {
    console.log('Cache updated:', data.data);
  }
};
```

## Configuration

### Cache Location

Default: `~/ha-logs/intelligence/cache/hub.db`

Override with `--cache-dir`:
```bash
./venv/bin/python bin/ha-hub.py --cache-dir /custom/path
```

### Module Schedules

- **Discovery**: Every 24 hours (configurable in `bin/ha-hub.py`)
- **ML Training**: Every 7 days (configurable in `bin/ha-hub.py`)
- **Pattern Detection**: On-demand via dashboard or API

### Environment Variables

Required in `~/.env`:
```bash
HA_URL=http://192.168.1.35:8123
HA_TOKEN=your_long_lived_access_token
```

## Development

### Run Tests

```bash
# All tests
./venv/bin/pytest tests/ -v

# Integration tests only
./venv/bin/pytest tests/test_integration.py -v

# Specific test
./venv/bin/pytest tests/test_discover.py::test_capability_detection -v
```

### Project Structure

```
ha-intelligence-hub-phase2/
├── bin/
│   ├── discover.py         # Standalone discovery script
│   └── ha-hub.py          # Main hub entry point
├── hub/
│   ├── core.py            # Hub orchestration
│   ├── cache.py           # SQLite cache manager
│   └── api.py             # FastAPI routes
├── modules/
│   ├── discovery.py       # Discovery module
│   ├── ml_engine.py       # ML training/prediction
│   ├── patterns.py        # Pattern recognition
│   └── orchestrator.py    # Automation management
├── dashboard/
│   ├── routes.py          # Dashboard HTTP routes
│   ├── templates/         # Jinja2 templates
│   └── static/            # CSS/JS assets
├── tests/
│   ├── test_integration.py  # Integration tests (14 tests)
│   ├── test_discover.py     # Discovery tests
│   ├── test_ml_training.py  # ML engine tests
│   └── test_patterns.py     # Pattern recognition tests
├── requirements.txt
└── README.md
```

## Deployment

See [docs/deployment.md](docs/deployment.md) for production deployment with systemd and Tailscale Serve.

## User Guide

See [docs/user-guide.md](docs/user-guide.md) for:
- How to interpret predictions
- How to approve automations
- Understanding pattern analysis
- Troubleshooting

## Roadmap

**Phase 2 (Current)**: Hub-and-spoke architecture with 5 modules ✅
**Phase 3 (Next)**: Advanced features
- Meta-learning (confidence calibration)
- Multi-model blending
- Anomaly detection improvements
- Voice interface integration

See `~/Documents/docs/plans/2026-02-11-ha-hub-lean-roadmap.md` for full roadmap.

## License

Personal project - no formal license.

## Author

Justin McFarland (https://github.com/your-username)
