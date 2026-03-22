#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000}"
USERS="${USERS:-200}"
SPAWN_RATE="${SPAWN_RATE:-10}"
DURATION="${DURATION:-5m}"

echo "=== Load test against ${TARGET} ==="
echo "Users: ${USERS}, spawn rate: ${SPAWN_RATE}/s, duration: ${DURATION}"

pip install locust 2>/dev/null

locust \
    -f tests/load/locustfile.py \
    --host "${TARGET}" \
    --users "${USERS}" \
    --spawn-rate "${SPAWN_RATE}" \
    --run-time "${DURATION}" \
    --headless \
    --html=load-test-report.html \
    --csv=load-test-results

echo "=== Report: load-test-report.html ==="
