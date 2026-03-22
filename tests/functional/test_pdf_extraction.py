"""Functional tests for PDF extraction."""

import pytest

from app.pdf_handler import extract_pdf, is_pdf
from tests.conftest import _generate_test_pdf


class TestPDFDetection:
    """Test PDF content-type and extension detection."""

    def test_detect_pdf_content_type(self):
        assert is_pdf("application/pdf", "http://test/doc") is True

    def test_detect_pdf_extension(self):
        assert is_pdf("application/octet-stream", "http://test/doc.pdf") is True

    def test_not_pdf(self):
        assert is_pdf("text/html", "http://test/page.html") is False


class TestPDFExtraction:
    """Test PDF text extraction."""

    def test_extract_test_pdf(self):
        pdf_bytes = _generate_test_pdf()
        markdown, metadata, errors = extract_pdf(pdf_bytes, "http://test/test.pdf")

        assert "Page 1" in markdown
        assert "Page 2" in markdown
        assert metadata["page_count"] == 2
        assert metadata["source_url"] == "http://test/test.pdf"

    def test_extract_pdf_content(self):
        pdf_bytes = _generate_test_pdf()
        markdown, metadata, errors = extract_pdf(pdf_bytes, "http://test/test.pdf")

        assert "first page" in markdown.lower()
        assert "second page" in markdown.lower()

    def test_invalid_pdf(self):
        markdown, metadata, errors = extract_pdf(b"not a pdf", "http://test/bad.pdf")
        assert len(errors) > 0
        assert errors[0].stage.value == "pdf"
