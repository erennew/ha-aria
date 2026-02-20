# ARIA Dashboard Screenshot Audit Report

Generated: 2026-02-20T01:26:04.709Z

## Summary

| Route | Screenshot | Page Errors | Console Errors | API Endpoints | API Failures |
|-------|-----------|-------------|----------------|---------------|-------------|
| home | captured | - | 2 | 8 | - |
| observe | captured | - | 1 | 3 | - |
| understand | captured | - | 1 | 5 | - |
| decide | captured | - | 1 | 2 | - |
| discovery | captured | - | 1 | 2 | - |
| capabilities | captured | - | 1 | 2 | - |
| ml-engine | captured | - | 1 | 5 | - |
| data-curation | captured | - | 1 | 2 | - |
| validation | captured | - | 1 | 1 | - |
| settings | captured | - | 1 | 1 | - |
| guide | captured | - | 1 | 0 | - |

**Totals:** 11 routes, 31 API calls, 0 failures, 0 page errors

---

## home (`/`)

Screenshot: `screenshots/home.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/health` | 200 | 28 | {status, uptime_seconds, modules, cache, timestamp, telegram_ok} | - |
| `/api/ml/anomalies` | 200 | 8 | {anomalies, autoencoder, isolation_forest} | - |
| `/api/shadow/accuracy` | 200 | 17 | {overall_accuracy, predictions_total, predictions_correct, predictions_disagreement, predictions_nothing, ... +4} | - |
| `/api/pipeline` | 200 | 16 | {id, current_stage, stage_entered_at, backtest_accuracy, shadow_accuracy_7d, ... +6} | - |
| `/api/cache/intelligence` | 200 | 22 | {category, data, version, last_updated, metadata} | - |
| `/api/cache/activity_summary` | 200 | 6 | {category, data, version, last_updated, metadata} | - |
| `/api/cache/automation_suggestions` | 200 | 5 | {category, data, version, last_updated, metadata} | - |
| `/api/cache/entities` | 200 | 367 | {category, data, version, last_updated, metadata} | - |

---

## observe (`/observe`)

Screenshot: `screenshots/observe.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/cache/intelligence` | 200 | 27 | {category, data, version, last_updated, metadata} | - |
| `/api/cache/activity_summary` | 200 | 5 | {category, data, version, last_updated, metadata} | - |
| `/api/cache/presence` | 200 | 5 | {category, data, version, last_updated, metadata} | - |

---

## understand (`/understand`)

Screenshot: `screenshots/understand.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/ml/anomalies` | 200 | 15 | {anomalies, autoencoder, isolation_forest} | - |
| `/api/shadow/accuracy` | 200 | 19 | {overall_accuracy, predictions_total, predictions_correct, predictions_disagreement, predictions_nothing, ... +4} | - |
| `/api/ml/drift` | 200 | 7 | {needs_retrain, reason, drifted_metrics, rolling_mae, current_mae, ... +4} | - |
| `/api/ml/shap` | 200 | 7 | {available, attributions, model_type, computed_at} | - |
| `/api/patterns` | 200 | 5 | {trajectory, active, anomaly_explanations, pattern_scales, shadow_events_processed, stats} | - |

---

## decide (`/decide`)

Screenshot: `screenshots/decide.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/cache/automation_suggestions` | 200 | 6 | {category, data, version, last_updated, metadata} | - |
| `/api/automations/feedback` | 200 | 6 | {suggestions, per_capability} | - |

---

## discovery (`/discovery`)

Screenshot: `screenshots/discovery.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/discovery/status` | 200 | 13 | {loaded} | - |
| `/api/settings/discovery` | 200 | 6 | {error} | - |

---

## capabilities (`/capabilities`)

Screenshot: `screenshots/capabilities.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/capabilities/registry` | 200 | 6 | {capabilities, total, by_layer, by_status} | - |
| `/api/capabilities/candidates` | 200 | 25 | {vehicle_tire_pressure, home_distance, device_storage, print_room_sensors, people_directory, ... +168} | - |

---

## ml-engine (`/ml-engine`)

Screenshot: `screenshots/ml-engine.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/ml/models` | 200 | 16 | {reference, incremental, forecaster, ml_models} | - |
| `/api/ml/drift` | 200 | 8 | {needs_retrain, reason, drifted_metrics, rolling_mae, current_mae, ... +4} | - |
| `/api/ml/features` | 200 | 7 | {selected, total, method, max_features, last_computed} | - |
| `/api/ml/hardware` | 200 | 5 | {ram_gb, cpu_cores, gpu_available, gpu_name, recommended_tier, ... +3} | - |
| `/api/ml/online` | 200 | 6 | {models, weight_tuner, online_blend_weight} | - |

---

## data-curation (`/data-curation`)

Screenshot: `screenshots/data-curation.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/curation` | 200 | 254 | {curations} | - |
| `/api/curation/summary` | 200 | 9 | {total, per_tier, per_status} | - |

---

## validation (`/validation`)

Screenshot: `screenshots/validation.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/validation/latest` | 200 | 12 | {status, message} | - |

---

## settings (`/settings`)

Screenshot: `screenshots/settings.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

### API Endpoints

| Endpoint | Status | Time (ms) | Response | Error |
|----------|--------|-----------|----------|-------|
| `/api/config` | 200 | 15 | {configs} | - |

---

## guide (`/guide`)

Screenshot: `screenshots/guide.png`

**Console errors:**
- Failed to load resource: the server responded with a status of 404 (Not Found)

_No API endpoints (static content)._
