# Browser Skill industriel — Prompts séquentiels optimisés

## Philosophie de la réécriture

Ce document remplace le prompt monolithique original par **4 prompts séquentiels** conçus pour maximiser la qualité du code généré par un LLM (Claude Code, Codex, ou tout agent de code).

**Changements clés par rapport à l'original :**

- Découpage en 4 prompts avec dépendances explicites (qualité ×2-3 attendue)
- Priorisation P0 / P1 / P2 dans chaque prompt
- Seuils de sécurité chiffrés (timeouts, taille, redirections)
- Modèle d'erreur structuré `ExtractionError`
- Résolution du conflit Playwright + `python:slim` → deux images Docker distinctes
- Build multi-architecture `linux/amd64` + `linux/arm64` via `docker buildx`
- Format OpenWebUI Tool explicite (classe `Tools` avec `Valves`)
- Dataset enrichi avec cas limites (SPA, paywall, 429, encodage)
- Stratégie de concurrence spécifiée (sémaphores, pool httpx)
- Chaîne de parsing hiérarchisée : `trafilatura` → `BeautifulSoup` → texte brut DOM
- Feature flags via variable `FEATURES_ENABLED`
- Sections redondantes fusionnées

## Mode d'emploi

1. Exécuter le **Prompt 1** dans Claude Code / Codex. Attendre la génération complète.
2. Dans la même session (ou en fournissant les fichiers générés comme contexte), exécuter le **Prompt 2**.
3. Idem pour les prompts 3 et 4.
4. Après le prompt 4, faire un `docker buildx build` et un `pytest` pour valider le scaffolding.

---

# Prompt 1 — Code applicatif core

````text
You are a senior Python engineer expert in web extraction, security, and LLM integration.

Generate the core application code for a "browser-use skill" — a web extraction service that fetches URLs, extracts structured content, and returns clean Markdown. The code must be modular, typed, and production-minded.

This prompt covers ONLY the Python application modules. API, Docker, K8s, and tests come in later prompts. Focus on code quality over breadth.

--------------------------------------------------
PRIORITY TIERS
--------------------------------------------------

P0 — the system does not work without these:
- config.py, security.py, fetcher.py, parser.py, markdown_builder.py
- browse_and_extract() orchestrator
- SSRF protection with concrete thresholds
- Structured error model

P1 — important but degrades gracefully if incomplete:
- pdf_handler.py, auth_detector.py, image_handler.py
- llm_client.py (OpenAI-compatible Scaleway client)

P2 — bonus, implement if context budget allows:
- Optional text enrichment via LLM
- In-memory LRU cache layer
- Language detection

Implement P0 fully and correctly first. Then P1. Then P2 if possible.

--------------------------------------------------
ENVIRONMENT VARIABLES
--------------------------------------------------

All configuration is read from environment variables in a central `config.py` module using Pydantic Settings.

Required variables:

    SCW_SECRET_KEY_LLM=<secret>
    SCW_LLM_BASE_URL=https://api.scaleway.ai/v1
    SCW_LLM_MODEL=gpt-oss-120b
    SCW_LLM_VISION_MODEL=mistral/pixtral-12b-2409

Feature activation is controlled by:

    FEATURES_ENABLED=extraction,vision,enrichment

Rules:
- Never hardcode secrets or model names (defaults from env are OK)
- At startup, validate that variables required by enabled features are present
- If FEATURES_ENABLED includes "vision", require SCW_SECRET_KEY_LLM and SCW_LLM_VISION_MODEL
- If FEATURES_ENABLED includes "enrichment", require SCW_SECRET_KEY_LLM and SCW_LLM_MODEL
- "extraction" is always enabled and needs no LLM credentials

Config module must also expose these tunable constants with sensible defaults:

    HTTP_CONNECT_TIMEOUT=10          # seconds
    HTTP_READ_TIMEOUT=30             # seconds
    MAX_RESPONSE_SIZE=52428800       # 50 MB
    MAX_REDIRECTS=5
    MAX_BROWSER_SESSIONS=3           # concurrent Playwright instances
    MAX_CONCURRENT_IMAGE_ANALYSES=5
    CACHE_MAX_ENTRIES=100
    CACHE_TTL_SECONDS=300

--------------------------------------------------
STRUCTURED ERROR MODEL
--------------------------------------------------

Define in models.py:

```python
from pydantic import BaseModel
from enum import Enum

class ExtractionStage(str, Enum):
    FETCH = "fetch"
    PARSE = "parse"
    PDF = "pdf"
    IMAGE_ANALYSIS = "image_analysis"
    BROWSER = "browser"
    ENRICHMENT = "enrichment"

class ExtractionError(BaseModel):
    stage: ExtractionStage
    message: str
    recoverable: bool

class ExtractionResult(BaseModel):
    ok: bool
    markdown: str
    metadata: dict
    errors: list[ExtractionError]
```

All modules must return or raise errors using this model. Never swallow exceptions silently — always record them in the errors list and continue if recoverable.

--------------------------------------------------
MAIN ORCHESTRATOR
--------------------------------------------------

Implement in orchestrator.py with this exact signature:

```python
async def browse_and_extract(
    url: str,
    cookies: dict | None = None,
    headers: dict | None = None,
    use_browser_fallback: bool = False,
) -> ExtractionResult:
    """Orchestrate the full extraction pipeline. Return structured result."""
```

Pipeline steps (in order):
1. Validate and normalize URL (security.py)
2. SSRF check (security.py)
3. Fetch page via httpx (fetcher.py)
4. Detect content type
5. If PDF → pdf_handler.py
6. If HTML → auth_detector.py check, then parser.py
7. If images found and "vision" feature enabled → image_handler.py
8. If extraction fails and use_browser_fallback=True → browser_fallback.py
9. Assemble Markdown (markdown_builder.py)

Each step that fails records an ExtractionError and the pipeline continues with what it has.

--------------------------------------------------
SECURITY MODULE (security.py) — P0
--------------------------------------------------

SSRF protection must:
- Allowlist schemes: http, https only
- Resolve DNS BEFORE connecting (prevent DNS rebinding)
- Block: localhost, 127.0.0.0/8, ::1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 (link-local), 100.64.0.0/10 (CGN), fd00::/8 (ULA)
- Block cloud metadata endpoints: 169.254.169.254, metadata.google.internal
- Validate each redirect hop (not just the initial URL) up to MAX_REDIRECTS
- Enforce MAX_RESPONSE_SIZE via streaming read with early abort
- Enforce HTTP_CONNECT_TIMEOUT and HTTP_READ_TIMEOUT separately

URL validation:
- Reject empty, whitespace-only, or non-string input
- Reject URLs with credentials (user:pass@host)
- Normalize and strip fragments
- Reject non-http(s) schemes including file://, ftp://, data:, javascript:

Implement as pure functions, no side effects, fully unit-testable.

--------------------------------------------------
FETCHER MODULE (fetcher.py) — P0
--------------------------------------------------

Use httpx.AsyncClient with:
- A shared client instance (connection pooling)
- Custom redirect handling that validates each hop via security.py
- Configurable timeouts from config
- Streaming response body with size limit enforcement
- User-Agent header identifying the tool

Return a FetchResult dataclass containing: status_code, final_url, content_type, headers, body (bytes or str), redirect_chain.

--------------------------------------------------
PARSER MODULE (parser.py) — P0
--------------------------------------------------

Parsing chain with explicit hierarchy:

1. **trafilatura** — primary extractor for article/readable content
2. **BeautifulSoup** — fallback for structured DOM cleanup when trafilatura returns empty or <100 chars
3. **Raw text from DOM** — last resort, strip all tags, collapse whitespace

Each level is a separate function. The parser tries level 1, falls through to 2, then 3.

Extract: title, canonical URL, main content, headings structure, links, detected language (via trafilatura's built-in or a simple heuristic).

--------------------------------------------------
AUTH DETECTOR (auth_detector.py) — P1
--------------------------------------------------

Heuristic detection of login/authentication walls. Receives the FetchResult and parsed DOM.

Signals (each weighted, threshold = 3+ signals):
- HTTP 401 or 403 (weight 3 — strong signal)
- <input type="password"> present (weight 3)
- Form action or CSS class/ID matching: login, log-in, signin, sign-in, auth, authentication, connexion, sso, oidc, oauth (weight 2 each, max 2)
- Redirect chain contains /login, /signin, /auth, /sso, /oauth, /oidc (weight 2)
- Content density < 500 chars of visible text (weight 1)
- Page title contains "login", "sign in", "connexion", "authentification" (weight 1)

Return an AuthDetectionResult with: is_auth_wall (bool), signals (list[str]), score (int).

If auth wall detected, markdown_builder produces the structured notice instead of content.

--------------------------------------------------
PDF HANDLER (pdf_handler.py) — P1
--------------------------------------------------

- Detect PDF from content-type header or .pdf extension
- Download with size limit from config
- Extract text using pymupdf (fitz)
- Structure into Markdown with headings heuristic (font size changes → heading levels)
- Include metadata: page count, source URL
- If text extraction yields < 200 chars per page average and "vision" feature is enabled, flag for OCR enrichment via image_handler's vision model (do NOT implement OCR inline — call a hook)

--------------------------------------------------
IMAGE HANDLER (image_handler.py) — P1
--------------------------------------------------

- Extract <img> tags from parsed HTML
- Filter: skip images < 100×100 px (from width/height attributes), skip data: URIs, skip common tracking pixels (/pixel, /beacon, 1x1)
- Resolve relative URLs to absolute
- Preserve alt text
- If "vision" feature is enabled, analyze up to 5 images concurrently using asyncio.Semaphore(MAX_CONCURRENT_IMAGE_ANALYSES)

Vision analysis function:

```python
async def analyze_image(image_url: str) -> ImageAnalysis:
    """Call Scaleway vision model. Return description, visible text, relevance summary."""
```

Use the LLM client from llm_client.py. Prompt the vision model to: describe the image concisely, extract visible text (OCR-style), assess relevance. Return structured ImageAnalysis(description, visible_text, relevance).

If analysis fails, log the error, record in ExtractionError list, and still include the image URL + alt text in output.

--------------------------------------------------
LLM CLIENT (llm_client.py) — P1
--------------------------------------------------

Reusable async OpenAI-compatible client:

```python
from openai import AsyncOpenAI

def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.SCW_LLM_BASE_URL,
        api_key=settings.SCW_SECRET_KEY_LLM,
    )
```

Provide helper functions:
- analyze_image(url) → uses SCW_LLM_VISION_MODEL
- enrich_text(raw_markdown) → uses SCW_LLM_MODEL (optional, P2)

Both must have timeout handling and structured error capture.

--------------------------------------------------
BROWSER FALLBACK (browser_fallback.py) — P1
--------------------------------------------------

Optional Playwright-based fallback. Disabled by default.

- Use asyncio.Semaphore(MAX_BROWSER_SESSIONS) to limit concurrent browsers
- Run headless Chromium
- Forward cookies/headers from the original request
- Wait for networkidle or 15s timeout
- Extract rendered HTML
- Pass rendered HTML back into parser.py (same parsing chain)

Keep this module self-contained. It must be importable without Playwright installed (guard imports with try/except, raise clear error if called without Playwright).

--------------------------------------------------
MARKDOWN BUILDER (markdown_builder.py) — P0
--------------------------------------------------

Assemble the final Markdown from all pipeline outputs.

Template (this is an INDICATIVE example — adapt field presence to actual extraction results):

```
# {title or "Untitled"}

- **Source:** {original_url}
- **Final URL:** {resolved_url}
- **Content type:** {html|pdf}
- **Extraction method:** {http|authenticated-http|browser-fallback|pdf}
- **Retrieved at:** {ISO 8601 timestamp}
- **Language:** {detected_language or "unknown"}

## Main content

{extracted_content}

## Images

{for each image: ![alt](url) + analysis block if available}

## Linked PDFs

{if PDFs were found and processed}

## Extraction notes

{any warnings, partial failures, or auth wall notice}
```

The Markdown must be clean enough for: OpenWebUI display, RAG chunking/ingestion, human review.

--------------------------------------------------
CACHING (utils.py) — P2
--------------------------------------------------

Simple async-compatible LRU cache:
- Key = sha256(url + sorted(cookies) + sorted(headers))
- Max entries: CACHE_MAX_ENTRIES
- TTL: CACHE_TTL_SECONDS
- Exclude PDFs from cache (too large)
- Thread-safe via asyncio.Lock

--------------------------------------------------
PROJECT STRUCTURE FOR THIS PROMPT
--------------------------------------------------

Generate these files with full implementation:

```
browser_use/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── security.py
│   ├── fetcher.py
│   ├── parser.py
│   ├── auth_detector.py
│   ├── pdf_handler.py
│   ├── image_handler.py
│   ├── llm_client.py
│   ├── browser_fallback.py
│   ├── markdown_builder.py
│   ├── orchestrator.py
│   └── utils.py
├── requirements.txt
└── .env.example
```

--------------------------------------------------
CODE QUALITY RULES
--------------------------------------------------

- Python 3.11+
- Type hints on all function signatures
- Docstrings on all public functions
- Pydantic for all data models and config
- Structured logging via Python logging module (JSON-friendly format)
- No print() statements
- No bare except clauses
- Every module must be importable and testable independently
- Prefer async/await throughout
````

---

# Prompt 2 — API, OpenWebUI wrapper, Docker multi-arch

````text
You are a senior platform engineer expert in FastAPI, Docker multi-architecture builds, and OpenWebUI plugin development.

You are continuing a project started in a previous prompt. The core application modules already exist in browser_use/app/. You must now add: the FastAPI API layer, the OpenWebUI tool wrapper, and the Docker build system with multi-architecture support (amd64 + arm64).

Do NOT regenerate the core modules. Import from them.

--------------------------------------------------
PRIORITY TIERS
--------------------------------------------------

P0: FastAPI API (main.py, api.py), Dockerfile multi-arch, .dockerignore
P1: OpenWebUI tool wrapper, docker-compose.yaml
P2: Gunicorn config, Prometheus metrics stub

--------------------------------------------------
FASTAPI API
--------------------------------------------------

File: app/main.py — FastAPI application factory
File: app/api.py — route definitions

Endpoints:

GET /healthz
- Return 200 with {"status": "healthy", "features": [...enabled features...]} when service is ready
- Return 503 with {"status": "unhealthy", "missing": [...]} if required config for enabled features is missing
- This endpoint must be fast (<50ms), no external calls

POST /extract
- Request body (Pydantic model):

```python
class ExtractRequest(BaseModel):
    url: str
    cookies: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    use_browser_fallback: bool = False
```

- Response body: the ExtractionResult model from models.py
- On unhandled exceptions: return 500 with {"ok": false, "markdown": "", "errors": [{"stage": "fetch", "message": "...", "recoverable": false}], "metadata": {}}
- Add request ID middleware (UUID per request, in logs and response headers)

Startup:
- Validate config on startup (fail fast)
- Log enabled features and config summary (without secrets)

CORS:
- Disabled by default
- Configurable via CORS_ORIGINS env var (comma-separated)

--------------------------------------------------
OPENWEBUI TOOL WRAPPER
--------------------------------------------------

File: app/openwebui_tool.py

OpenWebUI expects a specific class format. Implement EXACTLY this structure:

```python
"""
title: Browser Use - Web Extraction Tool
description: Fetch and extract structured content from web pages, detect login walls, process PDFs, and analyze images.
author: browser-use
version: 0.1.0
"""

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        """Configuration knobs exposed in OpenWebUI admin panel."""
        base_url: str = Field(
            default="http://localhost:8000",
            description="Base URL of the browser-use API service",
        )
        timeout: int = Field(
            default=60,
            description="Request timeout in seconds",
        )
        use_browser_fallback: bool = Field(
            default=False,
            description="Enable headless browser fallback for JS-heavy pages",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def browser_use(
        self,
        url: str,
        __event_emitter__=None,
    ) -> str:
        """
        Fetch a web page and extract its content as clean Markdown.
        Handles HTML pages, PDFs, login detection, and image analysis.

        :param url: The URL to fetch and extract content from.
        :return: Extracted content in Markdown format.
        """
        import httpx

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Fetching {url}...", "done": False}})

        async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
            response = await client.post(
                f"{self.valves.base_url}/extract",
                json={
                    "url": url,
                    "use_browser_fallback": self.valves.use_browser_fallback,
                },
            )
            response.raise_for_status()
            result = response.json()

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Extraction complete", "done": True}})

        if result.get("ok"):
            return result["markdown"]
        else:
            errors = result.get("errors", [])
            error_summary = "\n".join(f"- [{e['stage']}] {e['message']}" for e in errors)
            return f"# Extraction failed\n\n{error_summary}\n\nPartial content:\n\n{result.get('markdown', '')}"
```

This file must be self-contained and copy-pastable into OpenWebUI's Tools interface.

--------------------------------------------------
DOCKER — MULTI-ARCHITECTURE BUILD (amd64 + arm64)
--------------------------------------------------

The project produces TWO Docker images to resolve the Playwright + slim base conflict:

### Image 1: browser-use (lightweight, no browser)

File: docker/Dockerfile

```dockerfile
# ----- Build stage -----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ----- Runtime stage -----
FROM python:3.11-slim AS runtime

# Labels for multi-arch awareness
LABEL org.opencontainers.image.title="browser-use"
LABEL org.opencontainers.image.description="Web extraction service"
LABEL org.opencontainers.image.source="https://github.com/your-org/browser-use"

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/

# pymupdf needs this on arm64
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev libfreetype6 libharfbuzz0b libjbig2dec0 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### Image 2: browser-use-full (with Playwright/Chromium)

File: docker/Dockerfile.browser

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0 AS base

# Note: playwright base image is Debian-based, available for amd64 and arm64

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY requirements.txt requirements-browser.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-browser.txt

COPY app/ ./app/

USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### Multi-arch build script

File: scripts/build_multiarch.sh

```bash
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
```

IMPORTANT multi-arch notes to respect in generated code:
- pymupdf (fitz) has native wheels for amd64 and arm64 on PyPI — no special handling needed
- Playwright official Docker images support amd64 and arm64 since v1.40+
- Do NOT use alpine-based images (musl libc breaks pymupdf and Playwright)
- Use python:3.11-slim (Debian bookworm) which is available for both architectures
- All pip dependencies must have wheels or be pure Python for both platforms
- Test locally with: docker buildx build --platform linux/arm64 --load -f docker/Dockerfile -t test-arm64 .

### requirements.txt (for lightweight image)

```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30
httpx>=0.27
pydantic>=2.9
pydantic-settings>=2.5
beautifulsoup4>=4.12
lxml>=5.0
trafilatura>=1.12
pymupdf>=1.24
openai>=1.50
```

### requirements-browser.txt (additional deps for full image)

```
playwright>=1.49
```

### .dockerignore

```
.git
.env
__pycache__
*.pyc
.pytest_cache
.mypy_cache
tests/
datasets/
k8s/
scripts/
docs/
*.md
!README.md
docker-compose*.yaml
```

### docker-compose.yaml (local dev)

File: docker-compose.yaml

```yaml
version: "3.9"

services:
  browser-use:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"]
      interval: 30s
      timeout: 5s
      retries: 3
```

--------------------------------------------------
FILES TO GENERATE IN THIS PROMPT
--------------------------------------------------

```
browser_use/
├── app/
│   ├── main.py
│   ├── api.py
│   └── openwebui_tool.py
├── docker/
│   ├── Dockerfile
│   └── Dockerfile.browser
├── scripts/
│   └── build_multiarch.sh
├── docker-compose.yaml
├── requirements.txt
├── requirements-browser.txt
├── .dockerignore
└── .env.example
```

Generate full file contents. Do not regenerate core modules from prompt 1.
````

---

# Prompt 3 — Tests fonctionnels et tests de sécurité

````text
You are a senior QA and security engineer.

You are continuing a project where the core application and API are already implemented (browser_use/app/). You must now create comprehensive functional and security tests.

Do NOT regenerate application code. Import from app.* modules.

--------------------------------------------------
PRIORITY TIERS
--------------------------------------------------

P0: Security tests (SSRF, scheme validation, URL validation)
P1: Functional tests with synthetic fixtures (no network dependency for core tests)
P2: Integration tests against real URLs (marked as @pytest.mark.integration, skippable)

--------------------------------------------------
TEST INFRASTRUCTURE
--------------------------------------------------

Framework: pytest + pytest-asyncio + httpx (for FastAPI TestClient)

Create a conftest.py with:
- An async FastAPI TestClient fixture
- A synthetic HTTP server fixture (using pytest-httpserver or a minimal ASGI app) that serves:
  - A normal HTML page with title, content, 2 images, 3 links
  - A login page (with <input type="password">, form action="/login", HTTP 200)
  - A 401 response page
  - A 403 redirect chain → /login
  - A page with zero content (empty body shell)
  - A small test PDF (generate inline with pymupdf, 2 pages, known text)
  - A JS-heavy page stub (minimal HTML with a <noscript> tag, for browser fallback test)
  - A page returning non-UTF-8 encoding (ISO-8859-1)
  - A page returning HTTP 429

These fixtures make tests deterministic — no network calls for P0 and P1 tests.

--------------------------------------------------
SECURITY TESTS (tests/security/) — P0
--------------------------------------------------

File: tests/security/test_ssrf.py

Test cases:
- REJECT file:///etc/passwd
- REJECT ftp://example.com/file
- REJECT data:text/html,<h1>hi</h1>
- REJECT javascript:alert(1)
- REJECT http://127.0.0.1/admin
- REJECT http://localhost/admin
- REJECT http://[::1]/admin
- REJECT http://169.254.169.254/latest/meta-data/ (AWS metadata)
- REJECT http://metadata.google.internal/ (GCP metadata)
- REJECT http://10.0.0.1/internal
- REJECT http://172.16.0.1/internal
- REJECT http://192.168.1.1/internal
- REJECT http://100.64.0.1/cgnat (CGN range)
- REJECT http://user:pass@example.com/page (credentials in URL)
- REJECT URLs with double encoding tricks
- REJECT empty string, None, whitespace-only, non-string types
- ACCEPT http://example.com/
- ACCEPT https://fr.wikipedia.org/wiki/Test

File: tests/security/test_redirects.py

Test cases:
- REJECT redirect chain that resolves to 127.0.0.1
- REJECT redirect chain that resolves to 169.254.169.254
- REJECT redirect chain exceeding MAX_REDIRECTS (default 5)
- ACCEPT redirect chain of 3 hops to a valid external host

File: tests/security/test_response_limits.py

Test cases:
- REJECT response exceeding MAX_RESPONSE_SIZE (mock a streaming response >50MB)
- Verify timeout behavior: connect timeout and read timeout separately
- Verify that slow-drip responses (1 byte/sec) are killed by read timeout

File: tests/security/test_url_validation.py

Test cases:
- Various malformed URLs: missing scheme, double slashes, unicode tricks
- URLs with fragments are accepted but fragments stripped
- Very long URLs (>8KB) are rejected

--------------------------------------------------
FUNCTIONAL TESTS (tests/functional/) — P1
--------------------------------------------------

File: tests/functional/test_html_extraction.py

Using the synthetic server fixture:
- Extract normal HTML page → markdown is not empty, contains title, source URL present
- Extract page with images → ## Images section present, image URLs resolved to absolute
- Extract non-UTF-8 page → content extracted without crash, encoding handled

File: tests/functional/test_auth_detection.py

Using the synthetic server fixture:
- Login page (password field) → is_auth_wall=True, "password field" in signals
- 401 response → is_auth_wall=True, "HTTP 401" in signals
- 403 + redirect to /login → is_auth_wall=True, score >= 5
- Normal page → is_auth_wall=False
- Empty body shell → is_auth_wall=True (low content density)

File: tests/functional/test_pdf_extraction.py

Using the synthetic PDF fixture:
- Extract 2-page test PDF → markdown contains known text, page count = 2
- Content-type application/pdf detected correctly
- .pdf extension detected correctly

File: tests/functional/test_api.py

Using FastAPI TestClient:
- GET /healthz → 200, status=healthy
- POST /extract with valid URL → 200, ok=True, markdown non-empty
- POST /extract with invalid URL → 200, ok=False, errors list non-empty
- POST /extract with SSRF attempt → 200, ok=False, stage=fetch

File: tests/functional/test_markdown_builder.py

- Verify output contains required metadata fields
- Verify ## Images section only present when images exist
- Verify auth wall notice format when auth detected

File: tests/functional/test_429_handling.py

- Extract page returning 429 → error recorded, recoverable=True

--------------------------------------------------
INTEGRATION TESTS (tests/integration/) — P2
--------------------------------------------------

Marked with @pytest.mark.integration — skipped by default, run with:
    pytest -m integration --run-integration

File: tests/integration/test_real_urls.py

Using datasets/urls.txt:
- https://example.com/ → markdown contains "Example Domain"
- https://fr.wikipedia.org/wiki/Intelligence_artificielle → title present, >500 chars content
- https://en.wikipedia.org/wiki/Web_scraping → title present
- https://arxiv.org/pdf/1706.03762.pdf → "Attention" in content, page count > 0
- https://www.rfc-editor.org/rfc/rfc9110.txt → content extracted
- (SPA example) https://react.dev/ → if browser fallback disabled, content may be thin (acceptable)
- (Rate limited) Any URL returning 429 → error captured gracefully

--------------------------------------------------
DATASET FILE
--------------------------------------------------

File: datasets/urls.txt

```
# Standard HTML pages
https://example.com/
https://fr.wikipedia.org/wiki/Intelligence_artificielle
https://en.wikipedia.org/wiki/Web_scraping

# PDF
https://arxiv.org/pdf/1706.03762.pdf

# Plain text
https://www.rfc-editor.org/rfc/rfc9110.txt

# Image-rich page
https://en.wikipedia.org/wiki/Earth

# JS-heavy SPA (may need browser fallback)
https://react.dev/

# Edge cases — these test graceful degradation:
# Rate limiting is unpredictable, test checks error handling
# Non-UTF-8 pages are synthetic (in fixtures)
```

--------------------------------------------------
SECURITY SCANNING SCRIPTS
--------------------------------------------------

File: scripts/security_scan.sh

```bash
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
```

--------------------------------------------------
TEST CONFIGURATION
--------------------------------------------------

File: pytest.ini

```ini
[pytest]
asyncio_mode = auto
markers =
    integration: tests that hit real external URLs (deselect with -m "not integration")
testpaths = tests
```

File: tests/conftest.py — implement all fixtures described above.

--------------------------------------------------
FILES TO GENERATE
--------------------------------------------------

```
browser_use/
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── security/
│   │   ├── __init__.py
│   │   ├── test_ssrf.py
│   │   ├── test_redirects.py
│   │   ├── test_response_limits.py
│   │   └── test_url_validation.py
│   ├── functional/
│   │   ├── __init__.py
│   │   ├── test_html_extraction.py
│   │   ├── test_auth_detection.py
│   │   ├── test_pdf_extraction.py
│   │   ├── test_api.py
│   │   ├── test_markdown_builder.py
│   │   └── test_429_handling.py
│   └── integration/
│       ├── __init__.py
│       └── test_real_urls.py
├── datasets/
│   └── urls.txt
├── scripts/
│   └── security_scan.sh
├── pytest.ini
└── requirements-test.txt
```

requirements-test.txt:
```
pytest>=8.0
pytest-asyncio>=0.24
pytest-httpserver>=1.1
httpx>=0.27
```

Generate full file contents. Do not regenerate application code or Docker files from previous prompts.
````

---

# Prompt 4 — Kubernetes, load tests, documentation

````text
You are a senior DevOps/SRE engineer expert in Kubernetes, load testing, and technical documentation.

You are completing a project where the application, API, Docker images, and tests are already implemented. You must now create: Kubernetes manifests, load testing scripts, operations scripts, and the final README.

Do NOT regenerate application code, API, Docker, or tests.

--------------------------------------------------
PRIORITY TIERS
--------------------------------------------------

P0: K8s manifests (namespace, deployment, service, configmap, secret, probes)
P1: HPA, PDB, NetworkPolicy, Ingress, load test script
P2: K8s smoke test script, detailed bottleneck documentation

--------------------------------------------------
KUBERNETES MANIFESTS
--------------------------------------------------

Target: generic Kubernetes 1.28+ cluster. Manifests must work on both amd64 and arm64 node pools.

Namespace: browser-use

All manifests use consistent labels:
    app.kubernetes.io/name: browser-use
    app.kubernetes.io/component: extraction-service
    app.kubernetes.io/managed-by: kubectl

### Namespace (k8s/namespace.yaml)

### ConfigMap (k8s/configmap.yaml)

Non-secret configuration:
- SCW_LLM_BASE_URL
- FEATURES_ENABLED
- HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT
- MAX_RESPONSE_SIZE, MAX_REDIRECTS
- MAX_BROWSER_SESSIONS, MAX_CONCURRENT_IMAGE_ANALYSES
- CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS
- CORS_ORIGINS (empty by default)

### Secret (k8s/secret.example.yaml)

Example only (not applied directly), with placeholders:
- SCW_SECRET_KEY_LLM
- SCW_LLM_MODEL
- SCW_LLM_VISION_MODEL

Include a comment: "Replace placeholders and apply with: kubectl apply -f secret.yaml"

### Deployment (k8s/deployment.yaml)

TWO deployment variants in the same file (separated by ---):

1. browser-use (lightweight image, no Playwright)
2. browser-use-full (with Playwright, for browser fallback)

Common settings for both:
- replicas: 2
- strategy: RollingUpdate, maxSurge=1, maxUnavailable=0
- env from ConfigMap + Secret
- resources:
  - lightweight: requests 128Mi/100m, limits 512Mi/500m
  - full: requests 512Mi/250m, limits 2Gi/1000m (Playwright is heavy)
- securityContext:
  - runAsNonRoot: true
  - runAsUser: 1000
  - readOnlyRootFilesystem: true (lightweight only — Playwright needs /tmp writes)
  - allowPrivilegeEscalation: false
  - capabilities: drop ALL
- readinessProbe: httpGet /healthz, initialDelay 5s, period 10s
- livenessProbe: httpGet /healthz, initialDelay 15s, period 30s, failureThreshold 3
- Topology spread: prefer spreading across nodes

For multi-arch support, add:
```yaml
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/arch
                    operator: In
                    values:
                      - amd64
                      - arm64
```

### Service (k8s/service.yaml)

ClusterIP service on port 80 → targetPort 8000.

### Ingress (k8s/ingress.yaml)

Generic Ingress with annotations for:
- nginx ingress controller (default)
- commented-out Traefik alternative annotations
- TLS section (with placeholder cert secret name)
- Host: browser-use.example.com (placeholder)

### HPA (k8s/hpa.yaml)

- minReplicas: 2
- maxReplicas: 10
- Target CPU: 70%
- Behavior: scale up fast (60s stabilization), scale down slow (300s stabilization)
- Include YAML comments explaining how to add custom metrics (RPS, latency via KEDA or prometheus-adapter)

### PodDisruptionBudget (k8s/pdb.yaml)

- minAvailable: 1

### NetworkPolicy (k8s/networkpolicy.yaml)

- Allow ingress only from ingress controller namespace (label: app.kubernetes.io/name=ingress-nginx) on port 8000
- Allow egress to: DNS (port 53 TCP/UDP), HTTPS (port 443) to any external
- Block all other ingress and egress
- Include comments explaining how to customize

--------------------------------------------------
LOAD TESTING
--------------------------------------------------

Use Locust (Python-based, easier to customize than k6 for this team).

File: tests/load/locustfile.py

Scenarios:
1. extract_simple — POST /extract with https://example.com/ (fast, baseline)
2. extract_wikipedia — POST /extract with a Wikipedia URL (medium)
3. extract_pdf — POST /extract with the arxiv PDF URL (heavy)

Weight distribution: 60% simple, 30% wikipedia, 10% pdf.

Ramp: 50 → 500 users over 5 minutes, sustain for 5 minutes, then ramp down.

File: scripts/load_test.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000}"
USERS="${USERS:-200}"
SPAWN_RATE="${SPAWN_RATE:-10}"
DURATION="${DURATION:-5m}"

echo "=== Load test against ${TARGET} ==="
echo "Users: ${USERS}, spawn rate: ${SPAWN_RATE}/s, duration: ${DURATION}"

pip install locust 2>/dev/null

locust \
    -f tests/load/locustfile.py \
    --host "${TARGET}" \
    --users "${USERS}" \
    --spawn-rate "${SPAWN_RATE}" \
    --run-time "${DURATION}" \
    --headless \
    --html=load-test-report.html \
    --csv=load-test-results

echo "=== Report: load-test-report.html ==="
```

File: scripts/load_test_k8s.sh

Instructions to:
1. Deploy to K8s
2. Port-forward or use Ingress URL
3. Run locust against the K8s service
4. Watch HPA: kubectl get hpa -w -n browser-use
5. Check pod scaling: kubectl get pods -n browser-use -w

--------------------------------------------------
OPERATIONS SCRIPTS
--------------------------------------------------

File: scripts/run_local.sh
- Check .env exists
- pip install -r requirements.txt
- uvicorn app.main:app --reload --port 8000

File: scripts/run_tests.sh
- pip install -r requirements-test.txt
- pytest tests/security/ tests/functional/ -v
- Optional: pytest -m integration --run-integration (if flag passed)

File: scripts/k8s_smoke_test.sh
- kubectl apply -f k8s/namespace.yaml
- kubectl apply -f k8s/ (all manifests)
- Wait for rollout: kubectl rollout status deployment/browser-use -n browser-use --timeout=120s
- Smoke test: kubectl run smoke --rm -it --image=curlimages/curl -- curl -sf http://browser-use.browser-use.svc/healthz
- Print result

--------------------------------------------------
README
--------------------------------------------------

File: README.md

Structure:
1. Project title + one-line description
2. Architecture overview (text diagram showing: Client → API → Orchestrator → [Fetcher|Parser|PDF|Images|Browser] → Markdown)
3. Quick start (docker-compose up)
4. Environment variables table (name, required, default, description)
5. Features and feature flags
6. Local development setup
7. Running tests (unit, security, functional, integration)
8. Docker build (single arch + multi-arch)
9. Kubernetes deployment (step by step)
10. OpenWebUI integration (copy-paste the tool file + screenshot placeholder)
11. Load testing
12. Security design decisions and known limitations
13. Expected bottlenecks under load (table: component, bottleneck, mitigation)
14. Multi-architecture support notes (amd64/arm64, what works, what to watch)
15. Future extensions (RAG pipeline, Keycloak/OIDC, proxy rotation, observability)

### Bottlenecks table for README:

| Component | Bottleneck | Mitigation |
|-----------|-----------|------------|
| External fetch | Target site latency, rate limiting | Timeout + retry with backoff, cache |
| PDF extraction | CPU-bound pymupdf on large docs | Memory limits, async offload |
| Image analysis | Scaleway LLM API latency (~2-5s/image) | Semaphore concurrency limit, timeout |
| Browser fallback | Chromium memory (~200-500MB/instance) | MAX_BROWSER_SESSIONS semaphore, separate deployment |
| Overall | Single-threaded event loop saturation | Multiple uvicorn workers, HPA scaling |

--------------------------------------------------
.env.example
--------------------------------------------------

```bash
# Required
SCW_SECRET_KEY_LLM=scw-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SCW_LLM_BASE_URL=https://api.scaleway.ai/v1
SCW_LLM_MODEL=gpt-oss-120b
SCW_LLM_VISION_MODEL=mistral/pixtral-12b-2409

# Feature flags (comma-separated: extraction,vision,enrichment)
FEATURES_ENABLED=extraction

# Tuning
HTTP_CONNECT_TIMEOUT=10
HTTP_READ_TIMEOUT=30
MAX_RESPONSE_SIZE=52428800
MAX_REDIRECTS=5
MAX_BROWSER_SESSIONS=3
MAX_CONCURRENT_IMAGE_ANALYSES=5
CACHE_MAX_ENTRIES=100
CACHE_TTL_SECONDS=300

# CORS (empty = disabled)
CORS_ORIGINS=
```

--------------------------------------------------
FILES TO GENERATE
--------------------------------------------------

```
browser_use/
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.example.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   └── networkpolicy.yaml
├── tests/
│   └── load/
│       └── locustfile.py
├── scripts/
│   ├── run_local.sh
│   ├── run_tests.sh
│   ├── load_test.sh
│   ├── load_test_k8s.sh
│   ├── k8s_smoke_test.sh
│   └── build_multiarch.sh  (already exists from prompt 2, do not regenerate)
├── README.md
└── .env.example
```

Generate full file contents. Do not regenerate code from previous prompts.
````

---

## Résumé des améliorations appliquées

| # | Recommandation critique | Où c'est appliqué |
|---|------------------------|-------------------|
| 1 | Découpage en 4 prompts séquentiels | Structure globale du document |
| 2 | Priorisation P0/P1/P2 dans chaque prompt | En-tête de chaque prompt |
| 3 | Seuils de sécurité chiffrés | Prompt 1 — config.py + security.py |
| 4 | Modèle d'erreur structuré ExtractionError | Prompt 1 — models.py |
| 5 | Deux images Docker (slim + Playwright) | Prompt 2 — Dockerfile + Dockerfile.browser |
| 6 | Build multi-arch amd64 + arm64 via buildx | Prompt 2 — build_multiarch.sh |
| 7 | Format exact du tool OpenWebUI | Prompt 2 — openwebui_tool.py |
| 8 | Dataset enrichi avec cas limites | Prompt 3 — fixtures + datasets/urls.txt |
| 9 | Stratégie de concurrence (sémaphores, pool) | Prompt 1 — config + orchestrator |
| 10 | Chaîne de parsing hiérarchisée | Prompt 1 — parser.py |
| 11 | Feature flags via FEATURES_ENABLED | Prompt 1 — config.py |
| 12 | Sections redondantes fusionnées | Prompt 4 — README unique |
| 13 | Exemples marqués comme « indicatifs » | Templates Markdown, structure tool |
| 14 | pymupdf / Playwright arm64 compatibility notes | Prompt 2 — Dockerfile comments |
| 15 | K8s multi-arch nodeAffinity | Prompt 4 — deployment.yaml |
| 16 | Tests déterministes via fixtures synthétiques | Prompt 3 — conftest.py |
