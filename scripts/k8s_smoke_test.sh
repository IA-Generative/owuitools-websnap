#!/usr/bin/env bash
set -euo pipefail

echo "=== K8s Smoke Test ==="

echo "Applying namespace..."
kubectl apply -f k8s/namespace.yaml

echo "Applying all manifests..."
kubectl apply -f k8s/

echo "Waiting for rollout..."
kubectl rollout status deployment/browser-use -n browser-use --timeout=120s

echo "Running smoke test..."
kubectl run smoke-test --rm -it --restart=Never \
    --namespace=browser-use \
    --image=curlimages/curl \
    -- curl -sf http://browser-use.browser-use.svc/healthz

echo ""
echo "=== Smoke test complete ==="
