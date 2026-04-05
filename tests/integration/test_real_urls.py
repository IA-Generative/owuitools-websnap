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


# ---- Screenshot + overlay dismissal integration tests ----


@pytest.mark.asyncio
async def test_screenshot_gouvernement_fr_overlay_dismissed():
    """gouvernement.fr uses TarteAuCitron — overlay should be dismissed."""
    from app.browser_fallback import screenshot_page

    result = await screenshot_page(
        "https://www.gouvernement.fr", full_page=False, wait_seconds=2.0,
    )
    assert result["screenshot"]
    assert result["title"]
    # TarteAuCitron should have been clicked or JS-removed
    assert len(result["overlay_actions"]) > 0
    assert any(
        "tarteaucitron" in a.lower() or "js-removed" in a
        for a in result["overlay_actions"]
    )
    # Page text should contain actual content, not cookie banner text
    assert len(result["page_text"]) > 100


@pytest.mark.asyncio
async def test_screenshot_lemonde_fr_overlay_dismissed():
    """lemonde.fr uses Didomi — overlay should be dismissed."""
    from app.browser_fallback import screenshot_page

    result = await screenshot_page(
        "https://www.lemonde.fr", full_page=False, wait_seconds=2.0,
    )
    assert result["screenshot"]
    assert result["title"]
    assert len(result["overlay_actions"]) > 0
    assert len(result["page_text"]) > 100


@pytest.mark.asyncio
async def test_screenshot_example_com_no_overlay():
    """example.com has no popups — overlay_actions should be empty."""
    from app.browser_fallback import screenshot_page

    result = await screenshot_page(
        "https://example.com", full_page=False, wait_seconds=1.0,
    )
    assert result["screenshot"]
    assert result["title"] == "Example Domain"
    assert result["overlay_actions"] == []
    assert "Example Domain" in result["page_text"]


# ---- RSS fallback integration tests ----


@pytest.mark.asyncio
async def test_liberation_fr_rss_fallback():
    """liberation.fr is blocked by Datadome — RSS fallback should return content."""
    result = await browse_and_extract("https://www.liberation.fr")
    # Either direct extraction works or RSS fallback kicks in
    assert result.ok is True
    assert len(result.markdown) > 500
    # If RSS fallback was used, metadata should contain rss_url
    if result.metadata.get("auth_wall") or result.metadata.get("status_code") == 403:
        assert result.metadata.get("rss_url") or "Libération" in result.markdown


@pytest.mark.asyncio
async def test_fnac_com_extraction_works_via_http():
    """fnac.com blocks Playwright but HTTP extraction works."""
    result = await browse_and_extract("https://www.fnac.com")
    assert result.ok is True
    assert len(result.markdown) > 1000
    # Should contain product/category content
    assert "fnac" in result.markdown.lower()


@pytest.mark.asyncio
async def test_liberation_fr_rss_discovery():
    """liberation.fr RSS feed can be discovered and parsed."""
    from app.rss_fallback import discover_rss_url, fetch_and_parse_rss

    rss_url = await discover_rss_url("https://www.liberation.fr")
    assert rss_url is not None
    assert "liberation" in rss_url

    feed = await fetch_and_parse_rss(rss_url)
    assert feed["ok"] is True
    assert len(feed["items"]) > 0
    assert feed["feed_title"]  # should have a title
