"""API route definitions."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.models import ExtractionError, ExtractionResult, ExtractionStage
from app.orchestrator import browse_and_extract

logger = logging.getLogger(__name__)

router = APIRouter()


class ExtractRequest(BaseModel):
    url: str
    cookies: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    use_browser_fallback: bool = False


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
