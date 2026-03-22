#!/usr/bin/env bash
# Deploy browser-use service locally via Docker, alongside the grafrag-experimentation stack.
# Builds the image, starts the container on the Docker network, and registers
# the OpenWebUI tool + vision filter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GRAFRAG_ROOT="${GRAFRAG_ROOT:-${PROJECT_ROOT}/../grafrag-experimentation}"

# ── Configuration ──────────────────────────────────────────────
BROWSER_USE_IMAGE="${BROWSER_USE_IMAGE:-browser-use:local}"
BROWSER_USE_PORT="${BROWSER_USE_PORT:-8086}"
BROWSER_USE_CONTAINER="${BROWSER_USE_CONTAINER:-browser-use}"
FEATURES_ENABLED="${FEATURES_ENABLED:-extraction,vision}"
DOCKER_NETWORK="${DOCKER_NETWORK:-grafrag-experimentation_default}"

# ── Preflight checks ──────────────────────────────────────────
if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
  echo "No .env found — copying from .env.example"
  cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
  echo "Edit ${PROJECT_ROOT}/.env with your Scaleway credentials, then re-run."
  exit 1
fi

# ── Build ─────────────────────────────────────────────────────
printf '=== Building %s ===\n' "${BROWSER_USE_IMAGE}"
docker build -f "${PROJECT_ROOT}/docker/Dockerfile" \
  -t "${BROWSER_USE_IMAGE}" "${PROJECT_ROOT}"

# ── Stop previous container if running ────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${BROWSER_USE_CONTAINER}$"; then
  printf '=== Stopping existing container %s ===\n' "${BROWSER_USE_CONTAINER}"
  docker rm -f "${BROWSER_USE_CONTAINER}" >/dev/null 2>&1
fi

# ── Detect Docker network (grafrag stack) ─────────────────────
if ! docker network inspect "${DOCKER_NETWORK}" >/dev/null 2>&1; then
  echo "Docker network '${DOCKER_NETWORK}' not found."
  echo "If grafrag stack is running, set DOCKER_NETWORK to the correct network name."
  echo "Starting browser-use on host network instead."
  NETWORK_FLAG="--publish ${BROWSER_USE_PORT}:8000"
else
  NETWORK_FLAG="--network ${DOCKER_NETWORK} --publish ${BROWSER_USE_PORT}:8000"
fi

# ── Run ───────────────────────────────────────────────────────
printf '=== Starting %s on port %s ===\n' "${BROWSER_USE_CONTAINER}" "${BROWSER_USE_PORT}"
# shellcheck disable=SC2086
docker run -d \
  --name "${BROWSER_USE_CONTAINER}" \
  ${NETWORK_FLAG} \
  --env-file "${PROJECT_ROOT}/.env" \
  -e FEATURES_ENABLED="${FEATURES_ENABLED}" \
  --restart unless-stopped \
  "${BROWSER_USE_IMAGE}"

# ── Wait for healthy ──────────────────────────────────────────
printf 'Waiting for healthcheck...'
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${BROWSER_USE_PORT}/healthz" >/dev/null 2>&1; then
    printf ' OK\n'
    curl -s "http://localhost:${BROWSER_USE_PORT}/healthz" | python3 -m json.tool
    break
  fi
  printf '.'
  sleep 1
done

# ── Register tool & filter in OpenWebUI ───────────────────────
if [[ -f "${PROJECT_ROOT}/scripts/register_openwebui.sh" ]]; then
  printf '\n=== Registering tool & filter in OpenWebUI ===\n'
  bash "${PROJECT_ROOT}/scripts/register_openwebui.sh"
fi

printf '\n=== browser-use deployed ===\n'
printf 'Service:  http://localhost:%s\n' "${BROWSER_USE_PORT}"
printf 'Health:   http://localhost:%s/healthz\n' "${BROWSER_USE_PORT}"
printf 'Extract:  curl -X POST http://localhost:%s/extract -H "Content-Type: application/json" -d '"'"'{"url":"https://example.com/"}'"'"'\n' "${BROWSER_USE_PORT}"
