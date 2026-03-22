"""Functional tests for Markdown builder."""

import pytest

from app.markdown_builder import build_markdown
from app.models import (
    AuthDetectionResult,
    ExtractionError,
    ExtractionStage,
    ImageAnalysis,
    ParsedContent,
)


class TestMarkdownBuilder:
    """Test Markdown output assembly."""

    def test_contains_metadata_fields(self):
        parsed = ParsedContent(title="Test Title", content="Some content here.")
        md = build_markdown(
            original_url="http://example.com/page",
            final_url="http://example.com/page",
            content_type="text/html",
            parsed=parsed,
        )
        assert "# Test Title" in md
        assert "**Source:**" in md
        assert "**Content type:**" in md
        assert "**Extraction method:**" in md
        assert "**Retrieved at:**" in md

    def test_images_section_when_images_present(self):
        parsed = ParsedContent(title="Test", content="Content")
        images = [
            ImageAnalysis(
                image_url="http://example.com/img.jpg",
                alt_text="A photo",
                description="A nice photo",
            )
        ]
        md = build_markdown(
            original_url="http://example.com/",
            final_url="http://example.com/",
            content_type="text/html",
            parsed=parsed,
            images=images,
        )
        assert "## Images" in md
        assert "![A photo]" in md

    def test_no_images_section_when_empty(self):
        parsed = ParsedContent(title="Test", content="Content")
        md = build_markdown(
            original_url="http://example.com/",
            final_url="http://example.com/",
            content_type="text/html",
            parsed=parsed,
            images=[],
        )
        assert "## Images" not in md

    def test_auth_wall_notice(self):
        parsed = ParsedContent(title="Login", content="Sign in")
        auth = AuthDetectionResult(
            is_auth_wall=True,
            signals=["password field", "HTTP 401"],
            score=6,
        )
        md = build_markdown(
            original_url="http://example.com/",
            final_url="http://example.com/",
            content_type="text/html",
            parsed=parsed,
            auth_result=auth,
        )
        assert "Authentication Wall Detected" in md

    def test_extraction_notes_on_errors(self):
        parsed = ParsedContent(title="Test", content="Content")
        errors = [
            ExtractionError(
                stage=ExtractionStage.IMAGE_ANALYSIS,
                message="Timeout",
                recoverable=True,
            )
        ]
        md = build_markdown(
            original_url="http://example.com/",
            final_url="http://example.com/",
            content_type="text/html",
            parsed=parsed,
            errors=errors,
        )
        assert "## Extraction notes" in md
        assert "Timeout" in md
