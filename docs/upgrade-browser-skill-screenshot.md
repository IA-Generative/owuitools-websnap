# Prompt : Ajouter le screenshot intelligent à browser-skill-owui

Tu es un coding assistant. Tu vas modifier le repo existant `~/Documents/GitHub/browser-skill-owui` pour ajouter la capture d'écran de pages web et l'extraction intelligente des images.

## Contexte

Le service `browser-skill-owui` est un microservice FastAPI qui extrait le contenu de pages web. Il est intégré dans OpenWebUI comme tool OWUI. Il tourne sur Scaleway K8s (namespace `miraiku`).

Actuellement :
- `/extract` → retourne le contenu HTML converti en Markdown + métadonnées + liste d'URLs d'images
- `/analyze-image` → analyse une image via un modèle vision LLM (sera deprecated, remplacé par le filter Pixtral)
- Playwright est installé dans la version `browser-use-full` (Dockerfile avec Chromium)

On veut ajouter :
1. **Screenshot pleine page** via Playwright
2. **Extraction des images clés** (og:image, hero images) en base64 thumbnails
3. **Retour des visuels dans la réponse du tool OWUI** pour que l'utilisateur voie le site dans le chat

## Architecture actuelle du repo

```
browser-skill-owui/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── api.py               # Routes (/extract, /analyze-image, /healthz)
│   ├── config.py            # Settings
│   ├── models.py            # Pydantic models
│   ├── orchestrator.py      # browse_and_extract() — orchestre fetch + parse
│   ├── fetcher.py           # HTTP fetch (httpx)
│   ├── parser.py            # HTML → Markdown (BeautifulSoup + markdownify)
│   ├── browser_fallback.py  # Playwright headless browser
│   ├── llm_client.py        # Client LLM (Scaleway)
│   ├── mcp_server.py        # Serveur MCP (FastMCP)
│   └── mcp_app.py           # ASGI app MCP standalone
├── openwebui/
│   └── data_query_tool.py   # Tool OWUI (peut ne pas exister encore)
├── docker/
│   └── Dockerfile
├── entrypoint.py
├── requirements.txt
├── owui-plugin.yaml
└── docker-compose.yaml
```

## Modifications à apporter

### 1. Nouveau endpoint `/screenshot`

```python
# app/api.py — nouveau endpoint

class ScreenshotRequest(BaseModel):
    url: str
    full_page: bool = True           # True = page entière, False = viewport only
    width: int = 1280                # Largeur du viewport
    height: int = 800                # Hauteur du viewport
    wait_seconds: float = 2.0        # Attente après chargement (pour JS)
    extract_key_images: bool = True   # Extraire aussi les images clés
    max_images: int = 5              # Nombre max d'images clés à extraire
    thumbnail_width: int = 400       # Largeur max des thumbnails

class ScreenshotResponse(BaseModel):
    ok: bool
    url: str
    screenshot_base64: str           # Capture d'écran PNG en base64
    screenshot_size: int             # Taille en octets
    title: str                       # Titre de la page
    description: str                 # Meta description
    key_images: list[dict]           # Images clés extraites
    # Chaque image : {"url": "...", "alt": "...", "thumbnail_base64": "...", "width": int, "height": int}
    errors: list[str]
```

### 2. Modifier `browser_fallback.py`

Ajouter une fonction `screenshot_page()` :

```python
async def screenshot_page(
    url: str,
    full_page: bool = True,
    width: int = 1280,
    height: int = 800,
    wait_seconds: float = 2.0,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """
    Capture screenshot + extract metadata from a page using Playwright.
    
    Returns:
        {
            "screenshot": bytes,          # PNG screenshot
            "title": str,
            "description": str,
            "og_image": str | None,       # Open Graph image URL
            "image_urls": list[str],      # All significant image URLs found
            "html": str,                  # Rendered HTML
        }
    """
```

**Implémentation :**
- Lancer Playwright Chromium headless
- Configurer le viewport (width x height)
- Naviguer vers l'URL (wait_until="networkidle", timeout 15s, fallback "domcontentloaded")
- Attendre `wait_seconds` supplémentaires (pour les animations/lazy load)
- Prendre le screenshot (`page.screenshot(full_page=full_page, type="png")`)
- Extraire le titre (`page.title()`)
- Extraire la meta description et og:image via JavaScript :
  ```javascript
  document.querySelector('meta[name="description"]')?.content || ''
  document.querySelector('meta[property="og:image"]')?.content || ''
  ```
- Extraire les URLs des images significatives (filtrer les icônes, trackers, < 100px) :
  ```javascript
  Array.from(document.querySelectorAll('img'))
    .filter(img => img.naturalWidth > 100 && img.naturalHeight > 100)
    .map(img => ({ url: img.src, alt: img.alt, width: img.naturalWidth, height: img.naturalHeight }))
  ```
- Retourner le tout

### 3. Nouveau module `app/thumbnail.py`

Télécharge les images clés et crée des thumbnails :

```python
async def create_thumbnails(
    image_urls: list[dict],    # [{"url": "...", "alt": "...", "width": int, "height": int}]
    max_images: int = 5,
    thumbnail_width: int = 400,
) -> list[dict]:
    """
    Download images and create base64 thumbnails.
    
    Returns list of:
        {"url": "...", "alt": "...", "thumbnail_base64": "data:image/jpeg;base64,...", "width": int, "height": int}
    """
```

**Implémentation :**
- Télécharger chaque image via httpx (timeout 10s, max 5 Mo par image)
- Redimensionner avec Pillow (`PIL.Image.thumbnail((thumbnail_width, ...))`)
- Convertir en JPEG qualité 75 pour réduire la taille
- Encoder en base64 data URI
- Ignorer les images qui échouent (pas d'erreur bloquante)

### 4. Modifier le tool OWUI `openwebui/data_query_tool.py` → renommer en `openwebui/browser_use_tool.py`

**IMPORTANT** : ce fichier doit contenir une classe `Tools` (T majuscule).

Ajouter une méthode `screenshot` au tool OWUI existant :

```python
"""
title: Browser Use - Web Extraction
description: Fetch and extract content from web pages, take screenshots, compare websites.
author: browser-use
version: 1.0.0
"""

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default="http://host.docker.internal:8086",
            description="Base URL of the browser-use API service",
        )
        timeout: int = Field(default=60)
        use_browser_fallback: bool = Field(default=False)

    def __init__(self):
        self.valves = self.Valves()

    async def browser_use(self, url: str, __event_emitter__=None) -> str:
        """
        Fetch a web page and extract its content as clean Markdown.
        Use this for reading articles, documentation, or any web page.

        :param url: The URL to fetch and extract content from.
        :return: Extracted content in Markdown format.
        """
        # ... (existant, ne pas modifier)

    async def screenshot(self, url: str, __event_emitter__=None) -> str:
        """
        Take a screenshot of a web page and extract its key images.
        Shows a visual preview of the website directly in the chat.
        Use this when the user wants to SEE a website, not just read its text.

        :param url: The URL of the website to screenshot.
        :return: Screenshot and key images from the page.
        """
        import httpx
        import base64

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Capturing screenshot of {url}...", "done": False}})

        try:
            async with httpx.AsyncClient(timeout=self.valves.timeout) as client:
                response = await client.post(
                    f"{self.valves.base_url}/screenshot",
                    json={"url": url, "full_page": False, "extract_key_images": True},
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            return f"# Screenshot error\n\n{exc}"

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Screenshot captured", "done": True}})

        if not result.get("ok"):
            return f"# Screenshot failed\n\n{'; '.join(result.get('errors', []))}"

        parts = []
        parts.append(f"# {result.get('title', url)}\n")

        if result.get("description"):
            parts.append(f"> {result['description']}\n")

        # Inline screenshot as base64 image
        if result.get("screenshot_base64"):
            parts.append(f"## Capture d'écran\n")
            parts.append(f"![Screenshot]({result['screenshot_base64']})\n")

        # Key images as thumbnails
        key_images = result.get("key_images", [])
        if key_images:
            parts.append(f"## Images clés ({len(key_images)})\n")
            for i, img in enumerate(key_images, 1):
                alt = img.get("alt", f"Image {i}")
                if img.get("thumbnail_base64"):
                    parts.append(f"### {alt}")
                    parts.append(f"![{alt}]({img['thumbnail_base64']})")
                    parts.append(f"*Source: [{img['url'][:60]}...]({img['url']})*\n")

        return "\n".join(parts)

    async def compare_urls(self, urls: str, __event_emitter__=None) -> str:
        """
        Fetch and compare multiple web pages side by side.

        :param urls: Comma-separated list of URLs to compare.
        :return: Extracted content from all URLs, ready for comparison.
        """
        # ... (existant, ne pas modifier)
```

### 5. Mettre à jour le `owui-plugin.yaml`

Le tool a maintenant 3 méthodes : `browser_use`, `screenshot`, `compare_urls`.

### 6. Ajouter Pillow dans `requirements.txt`

```
Pillow>=10.0
```

### 7. Vérifier que le Dockerfile `browser-use-full` a Playwright

Le Dockerfile existant dans `docker/Dockerfile` est la version "light" sans Playwright.
Créer `docker/Dockerfile.full` si nécessaire, ou vérifier qu'il existe déjà :

```dockerfile
# docker/Dockerfile.full
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
LABEL org.opencontainers.image.title="browser-use-full"

RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -r -d /app -s /sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY openwebui/ ./openwebui/
COPY entrypoint.py .

# Install Playwright + Chromium
RUN pip install playwright && playwright install --with-deps chromium

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libharfbuzz0b libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* || true

USER appuser

EXPOSE 8000 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"

CMD ["python", "entrypoint.py"]
```

**IMPORTANT** : Le screenshot nécessite Playwright. Si l'endpoint `/screenshot` est appelé sur la version light (sans Playwright), retourner une erreur claire :
```json
{"ok": false, "errors": ["Screenshot requires Playwright. Use browser-use-full image."]}
```

## Tests

### test_screenshot.py

```python
# Utiliser des mocks pour Playwright
# Tester :
# 1. Screenshot d'une page simple (mock Playwright)
# 2. Extraction de métadonnées (title, description, og:image)
# 3. Filtrage des images < 100px
# 4. Création de thumbnails (mock image download)
# 5. Gestion d'erreur (URL invalide, timeout, Playwright non installé)
# 6. Taille max du screenshot (ne pas retourner des images > 2 Mo)
```

### test_thumbnail.py

```python
# Tester :
# 1. Redimensionnement correct (respecte le ratio)
# 2. Conversion JPEG avec compression
# 3. Base64 encoding
# 4. Gestion d'erreur (image inaccessible, format inconnu)
# 5. Limite max_images respectée
```

## Contraintes

- Le screenshot ne doit PAS dépasser **2 Mo** en base64 (sinon le chat OWUI rame). Si nécessaire, réduire la qualité JPEG ou la résolution.
- Les thumbnails doivent être en **JPEG qualité 75**, largeur max 400px.
- Si Playwright n'est pas installé (version light), l'endpoint `/screenshot` doit retourner une erreur claire, pas un crash.
- Le tool OWUI doit avoir la classe `Tools` (T majuscule) avec le docstring module (title, author, version).
- Le screenshot doit être au format **viewport** par défaut (`full_page=False`) car les pages complètes sont souvent trop grandes.
- Timeout total pour le screenshot : 20 secondes max.
- Sécurité : ne pas suivre les redirections vers des protocoles non-HTTP (file://, javascript:).
- Ne pas modifier les méthodes existantes `browser_use()` et `compare_urls()`, seulement ajouter `screenshot()`.
- Tous les fichiers doivent être créés ou modifiés, pas de placeholders.
- Les tests doivent pouvoir tourner sans réseau (mocks).

## Vérification

Après les modifications :

```bash
cd ~/Documents/GitHub/browser-skill-owui

# Tests
pip install -r requirements.txt
pytest tests/ -v

# Build local (version light — screenshot disabled)
docker compose build

# Build version full (avec Playwright)
docker build -f docker/Dockerfile.full -t browser-use-full:test .

# Test endpoint screenshot
docker run --rm -p 8000:8000 browser-use-full:test &
sleep 10
curl -X POST http://localhost:8000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.service-public.fr/particuliers/vosdroits/F21089"}'

# Commit
git add -A
git commit -m "feat: add screenshot endpoint with Playwright + key image extraction

- /screenshot endpoint: full page or viewport capture via Playwright
- Thumbnail generation for key images (Pillow, JPEG q75, max 400px)
- Tool OWUI: screenshot() method shows visuals in chat
- Dockerfile.full with Playwright + Chromium
- Graceful degradation: error message if Playwright not installed
- Max 2Mo per screenshot, auto-compress if larger

Co-Authored-By: Claude <noreply@anthropic.com>"
```
