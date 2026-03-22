"""Assemble final Markdown output from all pipeline results."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models import (
    AuthDetectionResult,
    ExtractionError,
    ImageAnalysis,
    ParsedContent,
)

logger = logging.getLogger(__name__)


def build_markdown(
    original_url: str,
    final_url: str,
    content_type: str,
    parsed: ParsedContent | None = None,
    auth_result: AuthDetectionResult | None = None,
    images: list[ImageAnalysis] | None = None,
    pdf_markdown: str | None = None,
    pdf_metadata: dict | None = None,
    errors: list[ExtractionError] | None = None,
    extraction_method: str = "http",
) -> str:
    """Build the final Markdown document from all extraction outputs."""
    parts: list[str] = []

    # Title
    title = "Untitled"
    if parsed and parsed.title:
        title = parsed.title
    parts.append(f"# {title}")

    # Metadata header
    now = datetime.now(timezone.utc).isoformat()
    language = "unknown"
    if parsed and parsed.language != "unknown":
        language = parsed.language

    detected_type = "pdf" if pdf_markdown is not None else "html"
    parts.append("")
    parts.append(f"- **Source:** {original_url}")
    if final_url != original_url:
        parts.append(f"- **Final URL:** {final_url}")
    parts.append(f"- **Content type:** {detected_type}")
    parts.append(f"- **Extraction method:** {extraction_method}")
    parts.append(f"- **Retrieved at:** {now}")
    parts.append(f"- **Language:** {language}")

    # Auth wall notice
    if auth_result and auth_result.is_auth_wall:
        parts.append("")
        parts.append("## Authentication Wall Detected")
        parts.append("")
        parts.append(
            "> **Warning:** This page appears to require authentication. "
            "The content below may be incomplete or reflect a login page."
        )
        parts.append(f"> **Detection score:** {auth_result.score}")
        parts.append("> **Signals:**")
        for signal in auth_result.signals:
            parts.append(f">   - {signal}")

    # Main content
    parts.append("")
    parts.append("## Main content")
    parts.append("")

    if pdf_markdown is not None:
        parts.append(pdf_markdown)
        if pdf_metadata:
            parts.append("")
            parts.append(f"*PDF — {pdf_metadata.get('page_count', '?')} pages*")
    elif parsed and parsed.content:
        parts.append(parsed.content)
    else:
        parts.append("*No content could be extracted.*")

    # Images section
    if images:
        analyzed_images = [img for img in images if img.description or img.alt_text]
        if analyzed_images:
            parts.append("")
            parts.append("## Images")
            parts.append("")
            for img in analyzed_images:
                alt = img.alt_text or "image"
                parts.append(f"![{alt}]({img.image_url})")
                if img.description:
                    parts.append(f"  *Description:* {img.description}")
                if img.visible_text:
                    parts.append(f"  *Visible text:* {img.visible_text}")
                if img.relevance:
                    parts.append(f"  *Relevance:* {img.relevance}")
                parts.append("")

    # Extraction notes
    if errors:
        parts.append("")
        parts.append("## Extraction notes")
        parts.append("")
        for err in errors:
            severity = "Warning" if err.recoverable else "Error"
            parts.append(f"- **[{severity}]** [{err.stage.value}] {err.message}")

    return "\n".join(parts)
