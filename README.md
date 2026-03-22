# Browser Use — Web Extraction Service

A production-ready web extraction service that fetches URLs, extracts structured content, and returns clean Markdown. Designed for OpenWebUI integration, RAG pipelines, and standalone use.

## Architecture

```
Client (OpenWebUI / API)
    │
    ▼
┌─────────────────────────────┐
│  FastAPI API (/extract)     │
│  main.py + api.py           │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Orchestrator               │
│  orchestrator.py            │
└──┬──┬──┬──┬──┬──────────────┘
   │  │  │  │  │
   ▼  │  │  │  ▼
Fetcher│ │  │ Markdown
   │  ▼  │  │ Builder
   │ Parser │ │
   │  │  ▼  │
   │  │ PDF  │
   │  │Handler│
   │  │  │  ▼
   │  │  │ Browser
   │  │  │ Fallback
   │  │  │
   ▼  ▼  ▼
┌─────────────────────────────┐
│  Security (SSRF protection) │
│  Auth Detector              │
│  Image Handler + Vision LLM │
└─────────────────────────────┘
```

## Quick Start

```bash
# Docker Compose
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
curl http://localhost:8000/healthz
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCW_SECRET_KEY_LLM` | If vision/enrichment enabled | - | Scaleway LLM API key |
| `SCW_LLM_BASE_URL` | No | `https://api.scaleway.ai/v1` | LLM API base URL |
| `SCW_LLM_MODEL` | If enrichment enabled | `gpt-oss-120b` | Text model name |
| `SCW_LLM_VISION_MODEL` | If vision enabled | `mistral/pixtral-12b-2409` | Vision model name |
| `FEATURES_ENABLED` | No | `extraction` | Comma-separated: `extraction`, `vision`, `enrichment` |
| `HTTP_CONNECT_TIMEOUT` | No | `10` | HTTP connect timeout (seconds) |
| `HTTP_READ_TIMEOUT` | No | `30` | HTTP read timeout (seconds) |
| `MAX_RESPONSE_SIZE` | No | `52428800` | Max response body size (bytes, default 50MB) |
| `MAX_REDIRECTS` | No | `5` | Max redirect hops |
| `MAX_BROWSER_SESSIONS` | No | `3` | Max concurrent Playwright instances |
| `MAX_CONCURRENT_IMAGE_ANALYSES` | No | `5` | Max concurrent vision API calls |
| `CACHE_MAX_ENTRIES` | No | `100` | LRU cache max entries |
| `CACHE_TTL_SECONDS` | No | `300` | Cache TTL (seconds) |
| `CORS_ORIGINS` | No | `` | Comma-separated allowed origins (empty = disabled) |

## Features and Feature Flags

Control enabled features via `FEATURES_ENABLED`:

- **`extraction`** (always enabled) — HTML/PDF content extraction, no LLM needed
- **`vision`** — Image analysis via Scaleway vision model (requires `SCW_SECRET_KEY_LLM`)
- **`enrichment`** — Text quality improvement via LLM (requires `SCW_SECRET_KEY_LLM`)

Example: `FEATURES_ENABLED=extraction,vision`

## Local Development

```bash
# Create virtual environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env as needed

# Run with hot reload
uvicorn app.main:app --reload --port 8000

# Or use the script
bash scripts/run_local.sh
```

## Running Tests

```bash
# Install test dependencies
pip install -r requirements.txt -r requirements-test.txt

# Security + functional tests
pytest tests/security/ tests/functional/ -v

# Integration tests (hit real URLs)
pytest -m integration --run-integration -v

# All tests
bash scripts/run_tests.sh
# With integration: bash scripts/run_tests.sh --integration
```

## Docker Build

### Single architecture (local)

```bash
docker build -f docker/Dockerfile -t browser-use:local .
docker run --rm -p 8000:8000 --env-file .env browser-use:local
```

### Multi-architecture (amd64 + arm64)

```bash
# Set up buildx (one-time)
docker buildx create --use --name multiarch --driver docker-container

# Build and push
REGISTRY=ghcr.io/your-org TAG=latest bash scripts/build_multiarch.sh
```

Two images are produced:
- **`browser-use`** — Lightweight, no browser (~200MB). For standard HTML/PDF extraction.
- **`browser-use-full`** — With Playwright/Chromium (~1.5GB). For JS-heavy pages with browser fallback.

## Kubernetes Deployment

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Configure secrets
cp k8s/secret.example.yaml k8s/secret.yaml
# Edit k8s/secret.yaml with real values
kubectl apply -f k8s/secret.yaml

# 3. Deploy everything
kubectl apply -f k8s/

# 4. Verify
kubectl rollout status deployment/browser-use -n browser-use
kubectl get pods -n browser-use

# 5. Smoke test
bash scripts/k8s_smoke_test.sh
```

Manifests include: Namespace, ConfigMap, Secret, Deployment (light + full), Service, Ingress, HPA, PDB, NetworkPolicy.

## OpenWebUI Integration

1. Open OpenWebUI → **Workspace** → **Tools** → **Create Tool**
2. Copy the entire content of `app/openwebui_tool.py` and paste it
3. Configure the **Valves** (base_url, timeout, browser fallback)
4. The tool becomes available as `browser_use` in your conversations

## Load Testing

```bash
# Local
TARGET=http://localhost:8000 bash scripts/load_test.sh

# Against K8s
TARGET=https://browser-use.example.com bash scripts/load_test.sh

# Monitor HPA scaling
kubectl get hpa -w -n browser-use
```

## Security Design Decisions

- **SSRF protection**: DNS pre-resolution, private IP blocking, redirect hop validation
- **Size limits**: Streaming body read with early abort at 50MB
- **Timeout enforcement**: Separate connect (10s) and read (30s) timeouts
- **Input validation**: URL scheme allowlist, credential rejection, length limits
- **Container security**: Non-root user, read-only filesystem (lightweight image), dropped capabilities
- **Network policies**: Ingress restricted to ingress controller, egress limited to DNS/HTTP/HTTPS

### Known Limitations

- Browser fallback requires a separate, heavier Docker image
- Vision/enrichment features depend on Scaleway LLM API availability
- No built-in authentication on the API itself (add via ingress or API gateway)
- Cache is in-memory per process (not shared across workers/pods)

## Expected Bottlenecks Under Load

| Component | Bottleneck | Mitigation |
|-----------|-----------|------------|
| External fetch | Target site latency, rate limiting | Timeout + retry with backoff, cache |
| PDF extraction | CPU-bound pymupdf on large docs | Memory limits, async offload |
| Image analysis | Scaleway LLM API latency (~2-5s/image) | Semaphore concurrency limit, timeout |
| Browser fallback | Chromium memory (~200-500MB/instance) | MAX_BROWSER_SESSIONS semaphore, separate deployment |
| Overall | Single-threaded event loop saturation | Multiple uvicorn workers, HPA scaling |

## Multi-Architecture Support

- Both Docker images build for `linux/amd64` and `linux/arm64`
- pymupdf has native wheels for both architectures (PyPI, v1.23+)
- Playwright official Docker images support both architectures (v1.40+)
- Base image: `python:3.11-slim` (Debian bookworm) — available for both
- Do NOT use Alpine (musl libc breaks pymupdf and Playwright)

## Future Extensions

- **RAG pipeline**: Direct integration with vector stores (Qdrant, Weaviate)
- **Authentication**: Keycloak/OIDC for API access control
- **Proxy rotation**: Rotating proxies for rate-limited targets
- **Observability**: Prometheus metrics, OpenTelemetry tracing, Grafana dashboards
- **Queue-based processing**: Redis/RabbitMQ for async extraction jobs
