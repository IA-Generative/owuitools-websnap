#!/usr/bin/env bash
# Redeploy the full OpenWebUI stack (grafrag + browser-use).
#
# This script:
#   1. Calls grafrag-experimentation's redeploy script to rebuild the full stack
#   2. Deploys browser-use (Docker or K8s depending on mode)
#   3. Registers the browser-use tool & vision filter in OpenWebUI
#
# Usage:
#   bash scripts/redeploy_full_stack.sh              # Docker mode (default)
#   bash scripts/redeploy_full_stack.sh --k8s        # Kubernetes mode
#   GRAFRAG_ROOT=/path/to/grafrag bash scripts/redeploy_full_stack.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GRAFRAG_ROOT="${GRAFRAG_ROOT:-${PROJECT_ROOT}/../grafrag-experimentation}"
MODE="${1:-docker}"

# ── Validate grafrag repo ─────────────────────────────────────
if [[ ! -d "${GRAFRAG_ROOT}" ]]; then
  printf 'ERROR: grafrag-experimentation repository not found at: %s\n' "${GRAFRAG_ROOT}" >&2
  printf 'Set GRAFRAG_ROOT env var to the correct path.\n' >&2
  exit 1
fi

printf '╔══════════════════════════════════════════════════════╗\n'
printf '║  Full Stack Redeploy: grafrag + browser-use         ║\n'
printf '╚══════════════════════════════════════════════════════╝\n\n'
printf 'grafrag root:    %s\n' "${GRAFRAG_ROOT}"
printf 'browser-use root: %s\n' "${PROJECT_ROOT}"
printf 'Mode:            %s\n\n' "${MODE}"

# ── Step 1: Redeploy grafrag OpenWebUI stack ──────────────────
printf '┌──────────────────────────────────────────────────────┐\n'
printf '│ [1/3] Redeploying grafrag OpenWebUI stack            │\n'
printf '└──────────────────────────────────────────────────────┘\n\n'

if [[ "${MODE}" == "--k8s" || "${MODE}" == "k8s" ]]; then
  # K8s mode: use grafrag's full K8s deploy pipeline
  if [[ -x "${GRAFRAG_ROOT}/scripts/redeploy_openwebui_stack.sh" ]]; then
    export GRAFRAG_ROOT
    bash "${GRAFRAG_ROOT}/scripts/redeploy_openwebui_stack.sh"
  else
    printf 'WARNING: grafrag redeploy script not found, skipping grafrag deploy.\n'
    printf 'Continuing with browser-use K8s deploy only.\n\n'
  fi
else
  # Docker mode: rebuild and restart grafrag compose stack
  printf 'Pulling latest images and restarting grafrag stack...\n'
  (cd "${GRAFRAG_ROOT}" && docker compose pull && docker compose up -d --remove-orphans)
  printf 'Waiting for OpenWebUI to be healthy...\n'
  for i in $(seq 1 60); do
    if curl -sf "http://localhost:${OPENWEBUI_PORT:-3000}/api/version" >/dev/null 2>&1; then
      version=$(curl -s "http://localhost:${OPENWEBUI_PORT:-3000}/api/version" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))")
      printf '  OpenWebUI v%s is ready.\n\n' "${version}"
      break
    fi
    sleep 2
  done
fi

# ── Step 2: Deploy browser-use ────────────────────────────────
printf '┌──────────────────────────────────────────────────────┐\n'
printf '│ [2/3] Deploying browser-use service                  │\n'
printf '└──────────────────────────────────────────────────────┘\n\n'

if [[ "${MODE}" == "--k8s" || "${MODE}" == "k8s" ]]; then
  bash "${PROJECT_ROOT}/scripts/deploy_k8s.sh"
else
  bash "${PROJECT_ROOT}/scripts/deploy_docker.sh"
fi

# ── Step 3: Register in OpenWebUI ─────────────────────────────
printf '\n┌──────────────────────────────────────────────────────┐\n'
printf '│ [3/3] Registering tool & filter in OpenWebUI         │\n'
printf '└──────────────────────────────────────────────────────┘\n\n'

bash "${PROJECT_ROOT}/scripts/register_openwebui.sh"

printf '\n╔══════════════════════════════════════════════════════╗\n'
printf '║  Full stack redeployed successfully!                 ║\n'
printf '╠══════════════════════════════════════════════════════╣\n'
printf '║  OpenWebUI:    http://localhost:%s              ║\n' "${OPENWEBUI_PORT:-3000}"
printf '║  browser-use:  http://localhost:%s              ║\n' "${BROWSER_USE_PORT:-8086}"
printf '║  GraphRAG:     http://localhost:8081              ║\n'
printf '╚══════════════════════════════════════════════════════╝\n'
