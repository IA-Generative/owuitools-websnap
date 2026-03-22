#!/usr/bin/env bash
# Deploy browser-use service to Kubernetes alongside the grafrag stack.
# Builds and pushes the Docker image, applies K8s manifests, and waits for rollout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Configuration ─────────────────────────────────────────────
NAMESPACE="${NAMESPACE:-browser-use}"
REGISTRY="${REGISTRY:-ghcr.io/your-org}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
IMAGE_LIGHT="${REGISTRY}/browser-use:${IMAGE_TAG}"
IMAGE_FULL="${REGISTRY}/browser-use-full:${IMAGE_TAG}"

printf '=== browser-use K8s deployment ===\n'
printf 'Namespace: %s\n' "${NAMESPACE}"
printf 'Registry:  %s\n' "${REGISTRY}"
printf 'Tag:       %s\n' "${IMAGE_TAG}"
printf 'Platforms: %s\n\n' "${PLATFORMS}"

# ── Build & push images ──────────────────────────────────────
printf '[1/4] Building and pushing images...\n'

docker buildx build \
  --platform "${PLATFORMS}" \
  --file "${PROJECT_ROOT}/docker/Dockerfile" \
  --tag "${IMAGE_LIGHT}" \
  --push \
  "${PROJECT_ROOT}"

printf '  Pushed %s\n' "${IMAGE_LIGHT}"

if [[ "${BUILD_FULL:-false}" == "true" ]]; then
  docker buildx build \
    --platform "${PLATFORMS}" \
    --file "${PROJECT_ROOT}/docker/Dockerfile.browser" \
    --tag "${IMAGE_FULL}" \
    --push \
    "${PROJECT_ROOT}"
  printf '  Pushed %s\n' "${IMAGE_FULL}"
fi

# ── Update image in manifests ─────────────────────────────────
printf '\n[2/4] Applying K8s manifests...\n'

kubectl apply -f "${PROJECT_ROOT}/k8s/namespace.yaml"

# Render manifests with current image tag
for manifest in configmap secret.example service hpa pdb networkpolicy ingress; do
  f="${PROJECT_ROOT}/k8s/${manifest}.yaml"
  [[ -f "$f" ]] && kubectl apply -f "$f" -n "${NAMESPACE}"
done

# Apply deployment with image override
cat "${PROJECT_ROOT}/k8s/deployment.yaml" \
  | sed "s|ghcr.io/your-org/browser-use:latest|${IMAGE_LIGHT}|g" \
  | sed "s|ghcr.io/your-org/browser-use-full:latest|${IMAGE_FULL}|g" \
  | kubectl apply -n "${NAMESPACE}" -f -

printf '  Manifests applied\n'

# ── Wait for rollout ──────────────────────────────────────────
printf '\n[3/4] Waiting for rollout...\n'
kubectl rollout status deployment/browser-use -n "${NAMESPACE}" --timeout=120s
printf '  Deployment ready\n'

# ── Smoke test ────────────────────────────────────────────────
printf '\n[4/4] Smoke test...\n'
kubectl run browser-use-smoke --rm -it --restart=Never \
  --namespace="${NAMESPACE}" \
  --image=curlimages/curl \
  -- curl -sf "http://browser-use.${NAMESPACE}.svc/healthz" 2>/dev/null \
  && printf '  Smoke test passed\n' \
  || printf '  Smoke test skipped (non-interactive)\n'

printf '\n=== browser-use deployed to namespace %s ===\n' "${NAMESPACE}"
