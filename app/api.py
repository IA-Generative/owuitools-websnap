"""API route definitions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from collections import OrderedDict

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import settings
from app.models import ExtractionError, ExtractionResult, ExtractionStage
from app.orchestrator import browse_and_extract

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory screenshot store (LRU, max 50 entries, 10 min TTL)
# Each entry: (full_bytes, thumb_bytes, content_type, timestamp, source_url)
_screenshot_store: OrderedDict[str, tuple[bytes, bytes, str, float, str]] = OrderedDict()
_STORE_MAX = 50
_STORE_TTL = 600

# Map screenshot_id → source_url (persists after image data expires)
_screenshot_urls: dict[str, str] = {}
_URLS_MAX = 500

# Lock to prevent concurrent regeneration of the same ID
_regen_locks: dict[str, asyncio.Lock] = {}


def _make_thumbnail(data: bytes, width: int = 800, quality: int = 60) -> bytes:
    """Create a JPEG thumbnail from image bytes.

    For full-page screenshots (height > 1.5× width), crop the top viewport
    portion first so the thumbnail shows the above-the-fold content, not a
    tiny squished version of the whole page.
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(data))
        w, h = img.size
        # Crop to viewport ratio if the page is very tall (full_page capture)
        max_thumb_height = int(w * 0.625)  # 16:10 ratio
        if h > w * 1.5:
            img = img.crop((0, 0, w, max_thumb_height))
        img.thumbnail((width, width), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return data


def store_screenshot(data: bytes, content_type: str = "image/png", source_url: str = "") -> str:
    """Store screenshot bytes + thumbnail and return an ID."""
    sid = hashlib.sha256(data[:1024] + str(time.time()).encode()).hexdigest()[:16]
    thumb = _make_thumbnail(data)
    _screenshot_store[sid] = (data, thumb, content_type, time.time(), source_url)
    # Track URL for regeneration after expiry
    _screenshot_urls[sid] = source_url
    while len(_screenshot_store) > _STORE_MAX:
        _screenshot_store.popitem(last=False)
    while len(_screenshot_urls) > _URLS_MAX:
        oldest = next(iter(_screenshot_urls))
        del _screenshot_urls[oldest]
    return sid


def _get_entry(screenshot_id: str):
    entry = _screenshot_store.get(screenshot_id)
    if not entry:
        return None
    data, thumb, content_type, ts, _url = entry
    if time.time() - ts > _STORE_TTL:
        del _screenshot_store[screenshot_id]
        return None
    return data, thumb, content_type


async def _regenerate_screenshot(screenshot_id: str) -> tuple[bytes, bytes, str] | None:
    """Re-capture a screenshot for an expired ID. Returns (full, thumb, content_type) or None."""
    source_url = _screenshot_urls.get(screenshot_id)
    if not source_url:
        return None

    # Serialize concurrent requests for the same ID
    if screenshot_id not in _regen_locks:
        _regen_locks[screenshot_id] = asyncio.Lock()
    async with _regen_locks.pop(screenshot_id, asyncio.Lock()):
        # Check if another request already regenerated it
        entry = _get_entry(screenshot_id)
        if entry:
            return entry

        try:
            from app.browser_fallback import screenshot_page
        except ImportError:
            return None

        try:
            logger.info("Regenerating expired screenshot %s for %s", screenshot_id, source_url)
            result = await screenshot_page(url=source_url, full_page=False, wait_seconds=2.0)
        except Exception as exc:
            logger.warning("Screenshot regeneration failed for %s: %s", source_url, exc)
            return None

        screenshot_bytes = result["screenshot"]
        content_type = "image/png"
        thumb = _make_thumbnail(screenshot_bytes)
        # Re-store under the same ID
        _screenshot_store[screenshot_id] = (screenshot_bytes, thumb, content_type, time.time(), source_url)
        return screenshot_bytes, thumb, content_type


_EXPIRED_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="480" height="150" viewBox="0 0 480 150">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ccd0da"/>
      <stop offset="100%" stop-color="#bcc0cc"/>
    </linearGradient>
  </defs>
  <rect width="480" height="150" rx="12" fill="url(#bg)"/>
  <rect x="1" y="1" width="478" height="148" rx="11" fill="none" stroke="#9ca0b0" stroke-width="0.5"/>
  <!-- Trash / cache purged icon (centered top) -->
  <g transform="translate(228,18)" fill="none" stroke="#7c7f93" stroke-width="1.8"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="M2 5h20"/>
    <path d="M8 5V3a2 2 0 012-2h4a2 2 0 012 2v2"/>
    <path d="M19 5l-.87 12.14A2 2 0 0116.14 19H7.86a2 2 0 01-1.99-1.86L5 5"/>
    <line x1="10" y1="9" x2="10" y2="15"/>
    <line x1="14" y1="9" x2="14" y2="15"/>
  </g>
  <!-- Main text -->
  <text x="240" y="68" text-anchor="middle"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif"
        font-size="14" font-weight="500" fill="#4c4f69">Le cache de votre capture a expiré</text>
  <!-- Sub text -->
  <text x="240" y="92" text-anchor="middle"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif"
        font-size="12" fill="#6c6f85">Régénération impossible — relancez le prompt avec</text>
  <!-- Retry arrows icon + "pour réessayer" on same line -->
  <g transform="translate(178,108)" fill="none" stroke="#1e66f5" stroke-width="1.8"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="M14 0v4.2h-4.2"/>
    <path d="M1 15v-4.2h4.2"/>
    <path d="M2.9 4.8a7 7 0 0111.1.7"/>
    <path d="M12.1 10.2a7 7 0 01-11.1-.7"/>
  </g>
  <text x="196" y="120" text-anchor="start"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif"
        font-size="12" fill="#1e66f5">pour réessayer</text>
</svg>"""


@router.get("/screenshots/{screenshot_id}")
async def get_screenshot(screenshot_id: str, size: str = "full"):
    """Serve screenshot. If expired but URL is known, regenerate on the fly."""
    entry = _get_entry(screenshot_id)

    if not entry:
        # Try to regenerate from the original URL
        entry = await _regenerate_screenshot(screenshot_id)
        if not entry:
            return Response(
                content=_EXPIRED_SVG,
                media_type="image/svg+xml",
                headers={"Cache-Control": "no-cache"},
            )

    data, thumb, content_type = entry
    if size == "thumb":
        return Response(content=thumb, media_type="image/jpeg")
    return Response(content=data, media_type=content_type)


class ExtractRequest(BaseModel):
    url: str
    cookies: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    use_browser_fallback: bool = False
    force_browser: bool = False


class ScreenshotRequest(BaseModel):
    url: str
    full_page: bool = False
    width: int = 1280
    height: int = 800
    wait_seconds: float = Field(default=2.0, ge=0, le=10)
    extract_key_images: bool = True
    max_images: int = Field(default=5, ge=0, le=20)
    thumbnail_width: int = Field(default=400, ge=100, le=1920)


class ScreenshotResponse(BaseModel):
    ok: bool
    url: str
    screenshot_base64: str = ""
    screenshot_size: int = 0
    screenshot_id: str = ""
    title: str = ""
    description: str = ""
    page_text: str = ""
    overlay_actions: list[str] = Field(default_factory=list)
    key_images: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ImageAnalyzeRequest(BaseModel):
    image_data: str  # base64 data URI or URL
    prompt: str = "Describe this image in detail. Extract any visible text."


class ImageAnalyzeResponse(BaseModel):
    ok: bool
    description: str
    visible_text: str
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    features: list[str]
    missing: list[str] | None = None


@router.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Health check endpoint — fast, no external calls."""
    missing = settings.validate_features()
    if missing:
        return HealthResponse(
            status="unhealthy",
            features=sorted(settings.enabled_features),
            missing=missing,
        )
    return HealthResponse(
        status="healthy",
        features=sorted(settings.enabled_features),
    )


@router.post("/extract", response_model=ExtractionResult)
async def extract(request: ExtractRequest) -> ExtractionResult:
    """Extract content from a URL and return structured Markdown."""
    try:
        result = await browse_and_extract(
            url=request.url,
            cookies=request.cookies,
            headers=request.headers,
            use_browser_fallback=request.use_browser_fallback,
            force_browser=request.force_browser,
        )
        return result
    except Exception as exc:
        logger.exception("Unhandled exception in /extract: %s", exc)
        return ExtractionResult(
            ok=False,
            markdown="",
            metadata={},
            errors=[
                ExtractionError(
                    stage=ExtractionStage.FETCH,
                    message=f"Internal error: {exc}",
                    recoverable=False,
                )
            ],
        )


@router.post("/analyze-image", response_model=ImageAnalyzeResponse)
async def analyze_image(request: ImageAnalyzeRequest) -> ImageAnalyzeResponse:
    """Analyze an uploaded image using a vision LLM."""
    if "vision" not in settings.enabled_features:
        return ImageAnalyzeResponse(
            ok=False,
            description="",
            visible_text="",
            error="Vision feature is not enabled. Set FEATURES_ENABLED=extraction,vision",
        )

    try:
        from app.llm_client import get_llm_client

        client = get_llm_client()
        response = await client.chat.completions.create(
            model=settings.SCW_LLM_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.prompt},
                        {"type": "image_url", "image_url": {"url": request.image_data}},
                    ],
                }
            ],
            max_tokens=1024,
            timeout=60,
        )
        text = response.choices[0].message.content or ""

        return ImageAnalyzeResponse(
            ok=True,
            description=text,
            visible_text="",
        )
    except Exception as exc:
        logger.exception("Image analysis failed: %s", exc)
        return ImageAnalyzeResponse(
            ok=False,
            description="",
            visible_text="",
            error=str(exc),
        )


# Max screenshot size: 2 MB before base64 encoding
_MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024


@router.post("/screenshot", response_model=ScreenshotResponse)
async def screenshot(request: ScreenshotRequest) -> ScreenshotResponse:
    """Capture a screenshot of a web page and extract key images."""
    from app.security import validate_url

    errors: list[str] = []

    try:
        validated_url = validate_url(request.url)
    except ValueError as exc:
        return ScreenshotResponse(ok=False, url=request.url, errors=[str(exc)])

    # Take the screenshot
    try:
        from app.browser_fallback import screenshot_page
    except ImportError:
        return ScreenshotResponse(
            ok=False,
            url=validated_url,
            errors=["Screenshot requires Playwright. Use websnap-full image."],
        )

    try:
        result = await screenshot_page(
            url=validated_url,
            full_page=request.full_page,
            width=request.width,
            height=request.height,
            wait_seconds=request.wait_seconds,
        )
    except ImportError:
        return ScreenshotResponse(
            ok=False,
            url=validated_url,
            errors=["Screenshot requires Playwright. Use websnap-full image."],
        )
    except Exception as exc:
        logger.exception("Screenshot failed for %s: %s", validated_url, exc)
        return ScreenshotResponse(
            ok=False, url=validated_url, errors=[f"Screenshot failed: {exc}"],
        )

    # Encode screenshot to base64, compress if too large
    screenshot_bytes: bytes = result["screenshot"]
    if len(screenshot_bytes) > _MAX_SCREENSHOT_BYTES:
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(screenshot_bytes))
            # Reduce to fit within limit
            for quality in (70, 50, 30):
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                screenshot_bytes = buf.getvalue()
                if len(screenshot_bytes) <= _MAX_SCREENSHOT_BYTES:
                    break
            else:
                # Last resort: resize
                img.thumbnail((request.width // 2, request.height * 4), Image.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=50, optimize=True)
                screenshot_bytes = buf.getvalue()
        except ImportError:
            errors.append("Pillow not installed — cannot compress large screenshot")

    screenshot_b64 = f"data:image/png;base64,{base64.b64encode(screenshot_bytes).decode('ascii')}"

    # Extract key image thumbnails
    key_images: list[dict] = []
    if request.extract_key_images:
        image_candidates = result.get("image_urls", [])
        # Prepend og:image if available
        og_image = result.get("og_image")
        if og_image:
            image_candidates = [{"url": og_image, "alt": "Open Graph image", "width": 0, "height": 0}] + image_candidates

        if image_candidates:
            try:
                from app.thumbnail import create_thumbnails

                key_images = await create_thumbnails(
                    image_urls=image_candidates,
                    max_images=request.max_images,
                    thumbnail_width=request.thumbnail_width,
                )
            except Exception as exc:
                logger.warning("Thumbnail creation failed: %s", exc)
                errors.append(f"Thumbnail extraction failed: {exc}")

    # Store full-size screenshot for retrieval via /screenshots/{id}
    screenshot_id = store_screenshot(screenshot_bytes, "image/png", source_url=validated_url)

    return ScreenshotResponse(
        ok=True,
        url=validated_url,
        screenshot_base64=screenshot_b64,
        screenshot_size=len(screenshot_bytes),
        screenshot_id=screenshot_id,
        title=result.get("title", ""),
        description=result.get("description", ""),
        page_text=result.get("page_text", ""),
        overlay_actions=result.get("overlay_actions", []),
        key_images=key_images,
        errors=errors,
    )
