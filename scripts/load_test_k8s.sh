#!/usr/bin/env bash
set -euo pipefail

echo "=== Load Test against Kubernetes ==="
echo ""
echo "Prerequisites:"
echo "  1. Deploy to K8s: kubectl apply -f k8s/"
echo "  2. Wait for rollout: kubectl rollout status deployment/browser-use -n browser-use"
echo ""
echo "Option A — Port-forward:"
echo "  kubectl port-forward svc/browser-use 8000:80 -n browser-use &"
echo "  TARGET=http://localhost:8000 bash scripts/load_test.sh"
echo ""
echo "Option B — Use Ingress URL:"
echo "  TARGET=https://browser-use.example.com bash scripts/load_test.sh"
echo ""
echo "Monitor scaling:"
echo "  kubectl get hpa -w -n browser-use"
echo "  kubectl get pods -n browser-use -w"
echo ""

# If TARGET is set, run the load test
if [[ -n "${TARGET:-}" ]]; then
    echo "Running load test against ${TARGET}..."
    bash scripts/load_test.sh
else
    echo "Set TARGET env var to run. Example:"
    echo "  TARGET=http://localhost:8000 bash scripts/load_test_k8s.sh"
fi
