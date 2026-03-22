#!/usr/bin/env bash
set -euo pipefail

echo "=== Running bandit (Python security linter) ==="
pip install bandit pip-audit 2>/dev/null
bandit -r app/ -f json -o bandit-report.json || true
bandit -r app/ -ll  # console summary, medium+ severity

echo ""
echo "=== Running pip-audit (dependency vulnerabilities) ==="
pip-audit --format=json --output=pip-audit-report.json || true
pip-audit  # console summary

echo ""
echo "=== Done. Reports: bandit-report.json, pip-audit-report.json ==="
