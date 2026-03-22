"""Image extraction, filtering, and optional vision analysis."""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.models import ExtractionError, ExtractionStage, ImageAnalysis

logger = logging.getLogger(__name__)

_image_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _image_semaphore
    if _image_semaphore is None:
        _image_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_IMAGE_ANALYSES)
    return _image_semaphore


def filter_images(images: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter out tracking pixels, tiny images, and data URIs."""
    filtered: list[dict[str, str]] = []
    for img in images:
        url = img.get("url", "")
        if not url or url.startswith("data:"):
            continue
        url_lower = url.lower()
        if any(p in url_lower for p in ("/pixel", "/beacon", "/1x1", "/track")):
            continue
        filtered.append(img)
    return filtered


async def analyze_images(
    images: list[dict[str, str]],
) -> tuple[list[ImageAnalysis], list[ExtractionError]]:
    """Analyze images using vision model if enabled. Returns analyses and errors."""
    errors: list[ExtractionError] = []

    if "vision" not in settings.enabled_features:
        # No vision — just return image refs with alt text
        return [
            ImageAnalysis(image_url=img["url"], alt_text=img.get("alt", ""))
            for img in images
        ], errors

    from app.llm_client import analyze_image

    semaphore = _get_semaphore()

    async def _analyze_one(img: dict[str, str]) -> ImageAnalysis:
        async with semaphore:
            try:
                return await analyze_image(img["url"], img.get("alt", ""))
            except Exception as exc:
                logger.warning("Image analysis failed for %s: %s", img["url"], exc)
                errors.append(ExtractionError(
                    stage=ExtractionStage.IMAGE_ANALYSIS,
                    message=f"Failed to analyze {img['url']}: {exc}",
                    recoverable=True,
                ))
                return ImageAnalysis(
                    image_url=img["url"],
                    alt_text=img.get("alt", ""),
                    error=str(exc),
                )

    # Analyze up to 5 images concurrently
    tasks = [_analyze_one(img) for img in images[:5]]
    analyses = await asyncio.gather(*tasks)

    # Add remaining images without analysis
    for img in images[5:]:
        analyses.append(ImageAnalysis(
            image_url=img["url"],
            alt_text=img.get("alt", ""),
        ))

    return list(analyses), errors
