#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
    echo "ERROR: .env file not found. Copy from .env.example:"
    echo "  cp .env.example .env"
    exit 1
fi

echo "=== Installing dependencies ==="
pip install -r requirements.txt

echo ""
echo "=== Starting browser-use on http://localhost:8000 ==="
uvicorn app.main:app --reload --port 8000
