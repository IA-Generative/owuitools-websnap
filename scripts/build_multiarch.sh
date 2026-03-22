#!/usr/bin/env bash
set -euo pipefail

# Requires: docker buildx create --use --name multiarch --driver docker-container

REGISTRY="${REGISTRY:-ghcr.io/your-org}"
TAG="${TAG:-latest}"
PLATFORMS="linux/amd64,linux/arm64"

echo "=== Building browser-use (lightweight) for ${PLATFORMS} ==="
docker buildx build \
    --platform "${PLATFORMS}" \
    --file docker/Dockerfile \
    --tag "${REGISTRY}/browser-use:${TAG}" \
    --push \
    .

echo "=== Building browser-use-full (with Playwright) for ${PLATFORMS} ==="
docker buildx build \
    --platform "${PLATFORMS}" \
    --file docker/Dockerfile.browser \
    --tag "${REGISTRY}/browser-use-full:${TAG}" \
    --push \
    .

echo "=== Done ==="
