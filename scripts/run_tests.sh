#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing test dependencies ==="
pip install -r requirements.txt -r requirements-test.txt

echo ""
echo "=== Running security and functional tests ==="
pytest tests/security/ tests/functional/ -v

if [[ "${1:-}" == "--integration" ]]; then
    echo ""
    echo "=== Running integration tests ==="
    pytest -m integration --run-integration -v
fi
