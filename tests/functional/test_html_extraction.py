"""Functional tests for HTML extraction."""

import pytest

from app.parser import parse_html
from tests.conftest import NORMAL_HTML, NON_UTF8_CONTENT


class TestHTMLExtraction:
    """Test HTML parsing and content extraction."""

    def test_extract_normal_page(self):
        result = parse_html(NORMAL_HTML, "http://test/normal")
        assert result.content
        assert len(result.content) > 50
        assert result.title == "Test Page Title"

    def test_extract_images(self):
        result = parse_html(NORMAL_HTML, "http://test/normal")
        assert len(result.images) >= 1
        # Images should have absolute URLs
        for img in result.images:
            assert img["url"].startswith("http")

    def test_extract_non_utf8(self):
        html = NON_UTF8_CONTENT.decode("iso-8859-1")
        result = parse_html(html, "http://test/iso")
        # Should not crash; content may have some characters
        assert result is not None

    def test_extract_headings(self):
        result = parse_html(NORMAL_HTML, "http://test/normal")
        assert "Main Heading" in result.headings

    def test_extract_links(self):
        result = parse_html(NORMAL_HTML, "http://test/normal")
        assert len(result.links) >= 2
