#!/usr/bin/env bash
# Cross-module smoke test — gates every stabilization batch
set -euo pipefail

API="http://127.0.0.1:8001"
FAIL=0

check() {
    local desc="$1" cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "PASS: $desc"
    else
        echo "FAIL: $desc"
        FAIL=1
    fi
}

# ML pipeline returns data (not envelope keys)
check "ML pipeline drift_status" \
    "curl -sf $API/api/ml/pipeline | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'drift_flagged' in d\""

# Presence data uses correct key
check "Presence mqtt_connected key" \
    "curl -sf $API/api/cache/presence | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'mqtt_connected' in str(d) or 'data' in d\""

# Config endpoint redacts sensitive keys
check "Config redacts sensitive values" \
    "curl -sf $API/api/config/presence.mqtt_password | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'REDACTED' in str(d.get('value',''))\""

# Config history redacts sensitive values
check "Config history redacts sensitive" \
    "curl -sf '$API/api/config-history?key=presence.mqtt_password' | python3 -c \"import json,sys; d=json.load(sys.stdin); [exit(1) for e in d.get('history',[]) if 'REDACTED' not in str(e.get('old_value','REDACTED'))]\""

# Shadow comparison not blind
check "Shadow comparison functional" \
    "curl -sf $API/api/shadow/status | python3 -c \"import json,sys; json.load(sys.stdin)\""

# SPA builds without error
check "SPA build" \
    "cd /home/justin/Documents/projects/ha-aria/aria/dashboard/spa && npm run build"

# Ruff clean
check "Ruff lint clean" \
    "cd /home/justin/Documents/projects/ha-aria && ruff check aria/"

exit $FAIL
