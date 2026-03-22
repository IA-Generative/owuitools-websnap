"""Reusable async OpenAI-compatible LLM client for Scaleway."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings
from app.models import ImageAnalysis

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_llm_client() -> AsyncOpenAI:
    """Return a shared AsyncOpenAI client instance."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.SCW_LLM_BASE_URL,
            api_key=settings.SCW_SECRET_KEY_LLM,
        )
    return _client


async def analyze_image(image_url: str, alt_text: str = "") -> ImageAnalysis:
    """Analyze an image using the Scaleway vision model."""
    client = get_llm_client()

    prompt = (
        "Analyze this image concisely:\n"
        "1. Describe what the image shows (1-2 sentences)\n"
        "2. Extract any visible text (OCR)\n"
        "3. Assess its relevance to the page content\n"
    )
    if alt_text:
        prompt += f"\nThe image alt text is: {alt_text}"

    try:
        response = await client.chat.completions.create(
            model=settings.SCW_LLM_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=300,
            timeout=30,
        )

        text = response.choices[0].message.content or ""
        lines = text.strip().split("\n")

        description = lines[0] if lines else ""
        visible_text = ""
        relevance = ""

        for line in lines:
            line_lower = line.lower()
            if "text" in line_lower or "ocr" in line_lower:
                visible_text = line
            if "relevan" in line_lower:
                relevance = line

        return ImageAnalysis(
            image_url=image_url,
            description=description,
            visible_text=visible_text,
            relevance=relevance,
            alt_text=alt_text,
        )
    except Exception as exc:
        logger.error("Vision analysis failed for %s: %s", image_url, exc)
        raise


async def enrich_text(raw_markdown: str) -> str:
    """Enrich extracted text using the LLM model (P2 feature)."""
    client = get_llm_client()

    try:
        response = await client.chat.completions.create(
            model=settings.SCW_LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a text quality enhancer. Clean up the following extracted "
                        "web content: fix obvious OCR errors, improve formatting, add missing "
                        "punctuation. Do NOT change the meaning or add information. "
                        "Return only the improved text."
                    ),
                },
                {"role": "user", "content": raw_markdown},
            ],
            max_tokens=4096,
            timeout=60,
        )
        return response.choices[0].message.content or raw_markdown
    except Exception as exc:
        logger.warning("Text enrichment failed: %s", exc)
        return raw_markdown
