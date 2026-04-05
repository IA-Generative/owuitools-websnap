"""Download images and create base64 thumbnails."""

from __future__ import annotations

import base64
import io
import logging

import httpx

logger = logging.getLogger(__name__)

# Safety limits
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image
_DOWNLOAD_TIMEOUT = 10  # seconds


async def create_thumbnails(
    image_urls: list[dict],
    max_images: int = 5,
    thumbnail_width: int = 400,
) -> list[dict]:
    """Download images and create base64 JPEG thumbnails.

    Args:
        image_urls: List of {"url": str, "alt": str, "width": int, "height": int}.
        max_images: Maximum number of images to process.
        thumbnail_width: Maximum width for thumbnails.

    Returns:
        List of {"url", "alt", "thumbnail_base64", "width", "height"} dicts.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping thumbnail generation")
        return []

    results: list[dict] = []
    candidates = image_urls[:max_images]

    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        for img_info in candidates:
            url = img_info.get("url", "")
            if not url or not url.startswith(("http://", "https://")):
                continue
            try:
                resp = await client.get(url)
                resp.raise_for_status()

                if len(resp.content) > _MAX_IMAGE_BYTES:
                    logger.warning("Image too large (%d bytes), skipping: %s", len(resp.content), url)
                    continue

                pil_img = Image.open(io.BytesIO(resp.content))
                pil_img.thumbnail((thumbnail_width, thumbnail_width * 4), Image.LANCZOS)

                # Convert to RGB for JPEG (handles RGBA/palette images)
                if pil_img.mode not in ("RGB", "L"):
                    pil_img = pil_img.convert("RGB")

                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=75, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")

                results.append({
                    "url": url,
                    "alt": img_info.get("alt", ""),
                    "thumbnail_base64": f"data:image/jpeg;base64,{b64}",
                    "width": pil_img.width,
                    "height": pil_img.height,
                })
            except Exception as exc:
                logger.debug("Failed to create thumbnail for %s: %s", url, exc)
                continue

    return results
