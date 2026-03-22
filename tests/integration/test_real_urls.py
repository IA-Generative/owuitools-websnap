"""Integration tests against real URLs — skipped by default."""

import pytest

from app.orchestrator import browse_and_extract

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_example_com():
    result = await browse_and_extract("https://example.com/")
    assert result.ok is True
    assert "Example Domain" in result.markdown


@pytest.mark.asyncio
async def test_wikipedia_fr():
    result = await browse_and_extract(
        "https://fr.wikipedia.org/wiki/Intelligence_artificielle"
    )
    assert result.ok is True
    assert len(result.markdown) > 500


@pytest.mark.asyncio
async def test_wikipedia_en():
    result = await browse_and_extract(
        "https://en.wikipedia.org/wiki/Web_scraping"
    )
    assert result.ok is True
    assert result.metadata.get("final_url")


@pytest.mark.asyncio
async def test_arxiv_pdf():
    result = await browse_and_extract(
        "https://arxiv.org/pdf/1706.03762.pdf"
    )
    assert "Attention" in result.markdown or len(result.errors) > 0


@pytest.mark.asyncio
async def test_rfc_text():
    result = await browse_and_extract(
        "https://www.rfc-editor.org/rfc/rfc9110.txt"
    )
    assert result.markdown  # Should have some content


@pytest.mark.asyncio
async def test_spa_graceful():
    """SPA without browser fallback should still return something (possibly thin)."""
    result = await browse_and_extract("https://react.dev/")
    # May or may not have content — just should not crash
    assert result is not None
