"""PDF text extraction and Markdown structuring using pymupdf."""

from __future__ import annotations

import logging

from app.config import settings
from app.models import ExtractionError, ExtractionStage

logger = logging.getLogger(__name__)


def is_pdf(content_type: str, url: str) -> bool:
    """Detect PDF from content-type header or .pdf extension."""
    if "application/pdf" in content_type.lower():
        return True
    if url.lower().rstrip("/").endswith(".pdf"):
        return True
    return False


def extract_pdf(
    body: bytes,
    source_url: str,
) -> tuple[str, dict, list[ExtractionError]]:
    """Extract text from PDF bytes and return (markdown, metadata, errors)."""
    errors: list[ExtractionError] = []

    try:
        import fitz  # pymupdf
    except ImportError:
        errors.append(ExtractionError(
            stage=ExtractionStage.PDF,
            message="pymupdf (fitz) is not installed — cannot extract PDF",
            recoverable=False,
        ))
        return "", {"page_count": 0, "source_url": source_url}, errors

    try:
        doc = fitz.open(stream=body, filetype="pdf")
    except Exception as exc:
        errors.append(ExtractionError(
            stage=ExtractionStage.PDF,
            message=f"Failed to open PDF: {exc}",
            recoverable=False,
        ))
        return "", {"page_count": 0, "source_url": source_url}, errors

    page_count = len(doc)
    pages_text: list[str] = []
    total_chars = 0

    for page_num in range(page_count):
        try:
            page = doc[page_num]
            text = page.get_text("text")
            total_chars += len(text)
            pages_text.append(text)
        except Exception as exc:
            errors.append(ExtractionError(
                stage=ExtractionStage.PDF,
                message=f"Failed to extract page {page_num + 1}: {exc}",
                recoverable=True,
            ))
            pages_text.append("")

    doc.close()

    # Build Markdown from pages
    markdown_parts: list[str] = []
    for i, text in enumerate(pages_text):
        if text.strip():
            markdown_parts.append(f"### Page {i + 1}\n\n{text.strip()}")

    markdown = "\n\n".join(markdown_parts)

    metadata = {
        "page_count": page_count,
        "source_url": source_url,
        "total_chars": total_chars,
    }

    # Flag for OCR if text is sparse
    avg_chars_per_page = total_chars / max(page_count, 1)
    needs_ocr = avg_chars_per_page < 200
    if needs_ocr and "vision" in settings.enabled_features:
        metadata["needs_ocr"] = True
        logger.info(
            "PDF has low text density (%.0f chars/page) — flagging for OCR enrichment",
            avg_chars_per_page,
        )

    return markdown, metadata, errors
