"""Tests for the /screenshot endpoint and screenshot_page function."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def _mock_screenshot_result():
    """A realistic screenshot_page() return value."""
    # 1x1 red PNG (67 bytes)
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
        "nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=="
    )
    return {
        "screenshot": base64.b64decode(png_b64),
        "title": "Test Page",
        "description": "A test page description",
        "og_image": "https://example.com/og.jpg",
        "image_urls": [
            {"url": "https://example.com/hero.jpg", "alt": "Hero", "width": 800, "height": 600},
            {"url": "https://example.com/photo.jpg", "alt": "Photo", "width": 400, "height": 300},
        ],
        "html": "<html><body>test</body></html>",
        "page_text": "Test Page\nThis is a test page description with content.",
        "overlay_actions": [],
    }


@pytest.fixture
def _mock_screenshot_result_with_overlay():
    """Screenshot result simulating a page where overlays were dismissed."""
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
        "nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=="
    )
    return {
        "screenshot": base64.b64decode(png_b64),
        "title": "Page avec cookies",
        "description": "Test page with cookie banner",
        "og_image": None,
        "image_urls": [],
        "html": "<html><body>content</body></html>",
        "page_text": "Contenu principal\nCeci est le contenu reel de la page.",
        "overlay_actions": [
            "clicked:#tarteaucitronPersonalize2",
            "js-removed:3 overlays",
        ],
    }


class TestScreenshotEndpoint:
    """Tests for POST /screenshot."""

    @pytest.mark.asyncio
    async def test_screenshot_success(self, _mock_screenshot_result):
        """Screenshot of a valid page returns ok=True with base64 data."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["title"] == "Test Page"
            assert data["description"] == "A test page description"
            assert data["screenshot_base64"].startswith("data:image/png;base64,")
            assert data["screenshot_size"] > 0

    @pytest.mark.asyncio
    async def test_screenshot_invalid_url(self):
        """Invalid URL scheme returns ok=False with error."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/screenshot", json={"url": "file:///etc/passwd"})

        data = resp.json()
        assert data["ok"] is False
        assert any("not allowed" in e for e in data["errors"])

    @pytest.mark.asyncio
    async def test_screenshot_javascript_url_rejected(self):
        """javascript: URLs are rejected."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/screenshot", json={"url": "javascript:alert(1)"})

        data = resp.json()
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_screenshot_playwright_not_installed(self):
        """When Playwright is missing, return a clear error."""
        with patch("app.browser_fallback.screenshot_page", side_effect=ImportError("Playwright not installed")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is False
        assert any("Playwright" in e for e in data["errors"])

    @pytest.mark.asyncio
    async def test_screenshot_timeout(self):
        """Timeout during screenshot returns error."""
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, side_effect=RuntimeError("Timeout")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is False
        assert any("Timeout" in e or "failed" in e for e in data["errors"])

    @pytest.mark.asyncio
    async def test_screenshot_with_key_images(self, _mock_screenshot_result):
        """Key images are returned when extract_key_images=True."""
        fake_thumbnails = [
            {
                "url": "https://example.com/hero.jpg",
                "alt": "Hero",
                "thumbnail_base64": "data:image/jpeg;base64,abc123",
                "width": 400,
                "height": 300,
            }
        ]
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=fake_thumbnails),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot",
                    json={"url": "https://example.com", "extract_key_images": True},
                )

        data = resp.json()
        assert data["ok"] is True
        assert len(data["key_images"]) == 1
        assert data["key_images"][0]["alt"] == "Hero"
        assert data["key_images"][0]["thumbnail_base64"].startswith("data:image/jpeg;base64,")

    @pytest.mark.asyncio
    async def test_screenshot_no_key_images(self, _mock_screenshot_result):
        """When extract_key_images=False, no thumbnails are returned."""
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot",
                    json={"url": "https://example.com", "extract_key_images": False},
                )

        data = resp.json()
        assert data["ok"] is True
        assert data["key_images"] == []

    @pytest.mark.asyncio
    async def test_screenshot_large_image_compressed(self):
        """Screenshots > 2 MB are compressed via Pillow."""
        from PIL import Image
        import io

        # Create a real large PNG image (will be > 2MB uncompressed)
        img = Image.new("RGB", (2000, 2000), color=(255, 128, 64))
        buf = io.BytesIO()
        img.save(buf, format="BMP")  # BMP is uncompressed = large
        large_bytes = buf.getvalue()
        assert len(large_bytes) > 2 * 1024 * 1024

        large_result = {
            "screenshot": large_bytes,
            "title": "Large Page",
            "description": "",
            "og_image": None,
            "image_urls": [],
            "html": "",
        }

        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=large_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com", "extract_key_images": False})

        data = resp.json()
        assert data["ok"] is True
        assert data["screenshot_size"] <= 2 * 1024 * 1024


class TestScreenshotPageFunction:
    """Tests for browser_fallback.screenshot_page()."""

    @pytest.mark.asyncio
    async def test_playwright_import_error(self):
        """screenshot_page raises ImportError when Playwright missing."""
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            from app.browser_fallback import screenshot_page

            with pytest.raises(ImportError, match="Playwright"):
                await screenshot_page("https://example.com")

    @pytest.mark.asyncio
    async def test_metadata_extraction(self):
        """screenshot_page extracts title, description, og:image from the page."""
        mock_page = AsyncMock()
        mock_page.title.return_value = "Mock Title"
        mock_page.url = "https://example.com"

        # _dismiss_overlays calls locator/get_by_role — make buttons not visible
        not_visible_btn = AsyncMock()
        not_visible_btn.is_visible.return_value = False
        mock_page.locator = lambda sel: MagicMock(first=not_visible_btn)
        mock_page.get_by_role = lambda role, **kw: MagicMock(first=not_visible_btn)

        # evaluate is called by: challenge_retry, dismiss_overlays, scroll_for_lazy_load,
        # then metadata extraction (description, og:image, image_urls, page_text).
        # Use a function to handle varied calls.
        _eval_responses = iter([
            500,                       # _navigate_with_challenge_retry body length check
            [],                        # _dismiss_overlays JS removal
            800,                       # _scroll_for_lazy_load scrollHeight (1st)
            None,                      # _scroll_for_lazy_load scrollTo bottom
            800,                       # _scroll_for_lazy_load scrollHeight (same → stop)
            None,                      # _scroll_for_lazy_load scrollTo top
            "Mock description",        # meta description
            "https://img.com/og.jpg",  # og:image
            [{"url": "https://img.com/big.jpg", "alt": "Big", "width": 800, "height": 600}],
            "Mock page text content",  # page_text extraction
        ])
        mock_page.evaluate = AsyncMock(side_effect=lambda *a, **kw: next(_eval_responses))
        mock_page.screenshot.return_value = b"\x89PNG\r\n"
        mock_page.content.return_value = "<html></html>"
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_context.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        mock_browser.close = AsyncMock()

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser

        mock_pw_cm = AsyncMock()
        mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw_instance)
        mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

        mock_async_pw = MagicMock(return_value=mock_pw_cm)

        with patch.dict("sys.modules", {
            "playwright": MagicMock(),
            "playwright.async_api": MagicMock(async_playwright=mock_async_pw),
        }):
            # Re-import to pick up the mocked playwright
            import importlib
            import app.browser_fallback
            importlib.reload(app.browser_fallback)

            from app.browser_fallback import screenshot_page

            # Patch the function's local import
            with patch.object(
                app.browser_fallback,
                "screenshot_page",
                wraps=app.browser_fallback.screenshot_page,
            ):
                result = await screenshot_page("https://example.com", wait_seconds=0)

            assert result["title"] == "Mock Title"
            assert result["description"] == "Mock description"
            assert result["og_image"] == "https://img.com/og.jpg"
            assert len(result["image_urls"]) == 1
            assert result["image_urls"][0]["url"] == "https://img.com/big.jpg"
            assert result["page_text"] == "Mock page text content"
            assert result["overlay_actions"] == []

            # Restore
            importlib.reload(app.browser_fallback)


class TestScreenshotRegeneration:
    """Tests for expired screenshot auto-regeneration."""

    @pytest.mark.asyncio
    async def test_expired_screenshot_regenerated(self, _mock_screenshot_result):
        """When a screenshot expires, GET re-captures it from the original URL."""
        from app.api import _screenshot_store, _screenshot_urls, store_screenshot, _STORE_TTL

        # 1. Store a screenshot with a known source URL
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})
        data = resp.json()
        sid = data["screenshot_id"]
        assert data["ok"] is True

        # 2. Force expiration by backdating the timestamp
        entry = _screenshot_store[sid]
        _screenshot_store[sid] = (entry[0], entry[1], entry[2], 0, entry[4])  # timestamp=0

        # 3. GET should trigger regeneration
        regen_result = {
            **_mock_screenshot_result,
            "title": "Regenerated Page",
        }
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=regen_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/screenshots/{sid}")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    @pytest.mark.asyncio
    async def test_unknown_id_returns_svg_placeholder(self):
        """A completely unknown screenshot ID returns an SVG placeholder."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/screenshots/nonexistent12345678")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert "expir" in resp.text.lower()
        assert "<svg" in resp.text

    @pytest.mark.asyncio
    async def test_regen_failure_returns_svg_placeholder(self, _mock_screenshot_result):
        """If regeneration fails (site down), return SVG placeholder instead of 404."""
        from app.api import _screenshot_store, _screenshot_urls

        # Store then expire
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})
        sid = resp.json()["screenshot_id"]
        entry = _screenshot_store[sid]
        _screenshot_store[sid] = (entry[0], entry[1], entry[2], 0, entry[4])

        # Regeneration fails
        with patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, side_effect=RuntimeError("Site down")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/screenshots/{sid}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert "relancez" in resp.text.lower()


class TestScreenshotPageText:
    """Tests for page_text and overlay_actions in /screenshot response."""

    @pytest.mark.asyncio
    async def test_page_text_returned(self, _mock_screenshot_result):
        """Screenshot response includes extracted page_text."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert "page_text" in data
        assert "Test Page" in data["page_text"]

    @pytest.mark.asyncio
    async def test_empty_page_text(self, _mock_screenshot_result):
        """When page has no visible text, page_text is empty string."""
        result = {**_mock_screenshot_result, "page_text": ""}
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert data["page_text"] == ""

    @pytest.mark.asyncio
    async def test_overlay_actions_returned(self, _mock_screenshot_result_with_overlay):
        """When overlays are dismissed, overlay_actions is populated."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result_with_overlay),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert len(data["overlay_actions"]) == 2
        assert "clicked:#tarteaucitronPersonalize2" in data["overlay_actions"]
        assert any("js-removed" in a for a in data["overlay_actions"])

    @pytest.mark.asyncio
    async def test_no_overlay_actions_when_clean_page(self, _mock_screenshot_result):
        """Clean page without popups returns empty overlay_actions."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert data["overlay_actions"] == []

    @pytest.mark.asyncio
    async def test_page_text_with_overlay_dismissed(self, _mock_screenshot_result_with_overlay):
        """Page text is extracted after overlay dismissal, not before."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result_with_overlay),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert "Contenu principal" in data["page_text"]
        assert len(data["overlay_actions"]) > 0


class TestDismissOverlays:
    """Tests for the _dismiss_overlays function with mocked Playwright page."""

    @pytest.mark.asyncio
    async def test_clicks_tarteaucitron_button(self):
        """_dismiss_overlays clicks TarteAuCitron consent button when visible."""
        from app.browser_fallback import _dismiss_overlays

        mock_btn = AsyncMock()
        mock_btn.is_visible.return_value = True
        mock_btn.click = AsyncMock()

        mock_page = AsyncMock()
        # locator().first returns our mock button only for tarteaucitron
        def locator_side_effect(selector):
            loc = AsyncMock()
            if "tarteaucitronPersonalize2" in selector:
                loc.first = mock_btn
            else:
                not_visible = AsyncMock()
                not_visible.is_visible.return_value = False
                loc.first = not_visible
            return loc
        mock_page.locator = locator_side_effect
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.url = "https://test.com"

        actions = await _dismiss_overlays(mock_page)

        assert any("tarteaucitronPersonalize2" in a for a in actions)
        mock_btn.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_text_matching(self):
        """When no CSS selector matches, falls back to button text matching."""
        from app.browser_fallback import _dismiss_overlays

        # All CSS selectors return not-visible
        mock_page = AsyncMock()
        not_visible_btn = AsyncMock()
        not_visible_btn.is_visible.return_value = False

        def locator_side_effect(selector):
            loc = AsyncMock()
            loc.first = not_visible_btn
            return loc
        mock_page.locator = locator_side_effect

        # Text-based button matching — "tout accepter" is visible
        accept_btn = AsyncMock()
        accept_btn.is_visible.return_value = True
        accept_btn.click = AsyncMock()

        no_match_btn = AsyncMock()
        no_match_btn.is_visible.return_value = False

        def get_by_role_side_effect(role, name="", exact=False):
            loc = AsyncMock()
            if "tout accepter" in name.lower():
                loc.first = accept_btn
            else:
                loc.first = no_match_btn
            return loc
        mock_page.get_by_role = get_by_role_side_effect
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.url = "https://test.com"

        actions = await _dismiss_overlays(mock_page)

        assert any("tout accepter" in a for a in actions)
        accept_btn.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_js_removal_phase(self):
        """JS overlay removal runs and reports removed elements."""
        from app.browser_fallback import _dismiss_overlays

        # No buttons visible at all
        not_visible = AsyncMock()
        not_visible.is_visible.return_value = False

        mock_page = AsyncMock()
        mock_page.locator = lambda sel: AsyncMock(first=not_visible)
        mock_page.get_by_role = lambda role, **kw: AsyncMock(first=not_visible)
        mock_page.wait_for_timeout = AsyncMock()
        # JS evaluate returns list of removed elements
        mock_page.evaluate = AsyncMock(return_value=["DIV#cookie-banner.consent", "DIV#overlay.modal"])
        mock_page.url = "https://test.com"

        actions = await _dismiss_overlays(mock_page)

        assert any("js-removed:2" in a for a in actions)

    @pytest.mark.asyncio
    async def test_clean_page_no_actions(self):
        """On a clean page with no overlays, no actions are taken."""
        from app.browser_fallback import _dismiss_overlays

        not_visible = AsyncMock()
        not_visible.is_visible.return_value = False

        mock_page = AsyncMock()
        mock_page.locator = lambda sel: AsyncMock(first=not_visible)
        mock_page.get_by_role = lambda role, **kw: AsyncMock(first=not_visible)
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.url = "https://clean.com"

        actions = await _dismiss_overlays(mock_page)

        assert actions == []

    @pytest.mark.asyncio
    async def test_click_failure_does_not_crash(self):
        """If a button click raises, _dismiss_overlays continues gracefully."""
        from app.browser_fallback import _dismiss_overlays

        broken_btn = AsyncMock()
        broken_btn.is_visible.side_effect = Exception("Element detached")

        mock_page = AsyncMock()
        mock_page.locator = lambda sel: AsyncMock(first=broken_btn)
        mock_page.get_by_role = lambda role, **kw: AsyncMock(first=broken_btn)
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.url = "https://broken.com"

        # Should not raise
        actions = await _dismiss_overlays(mock_page)
        assert isinstance(actions, list)


class TestChallengeRetry:
    """Tests for _navigate_with_challenge_retry."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        """Page with enough content succeeds immediately."""
        from app.browser_fallback import _navigate_with_challenge_retry

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=500)  # body length > 200
        mock_page.reload = AsyncMock()

        await _navigate_with_challenge_retry(mock_page, "https://example.com")

        mock_page.goto.assert_awaited_once()
        mock_page.reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_on_thin_content(self):
        """Page with thin content triggers retry."""
        from app.browser_fallback import _navigate_with_challenge_retry

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        # First check: 0 chars (challenge), second check after reload: 500 chars (resolved)
        mock_page.evaluate = AsyncMock(side_effect=[0, 500])
        mock_page.reload = AsyncMock()
        mock_page.url = "https://blocked.com"

        await _navigate_with_challenge_retry(mock_page, "https://blocked.com", max_retries=2)

        assert mock_page.reload.await_count == 1

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        """After max retries with thin content, function returns without raising."""
        from app.browser_fallback import _navigate_with_challenge_retry

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=0)  # always thin
        mock_page.reload = AsyncMock()
        mock_page.url = "https://anti-bot.com"

        # Should not raise
        await _navigate_with_challenge_retry(mock_page, "https://anti-bot.com", max_retries=1)

        assert mock_page.reload.await_count == 1

    @pytest.mark.asyncio
    async def test_navigation_failure_retries(self):
        """If goto fails, retries before raising."""
        from app.browser_fallback import _navigate_with_challenge_retry

        mock_page = AsyncMock()
        # First goto: networkidle fails, domcontentloaded also fails
        # Second goto: succeeds
        call_count = 0

        async def goto_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Timeout")

        mock_page.goto = AsyncMock(side_effect=goto_side_effect)
        mock_page.evaluate = AsyncMock(return_value=500)
        mock_page.reload = AsyncMock()

        await _navigate_with_challenge_retry(mock_page, "https://slow.com", max_retries=2)


class TestAntiBot:
    """Tests for anti-bot blank page detection in /screenshot API response."""

    @pytest.fixture
    def _blank_screenshot_result(self):
        """Screenshot result for a page blocked by anti-bot (blank)."""
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=="
        )
        return {
            "screenshot": base64.b64decode(png_b64),
            "title": "",
            "description": "",
            "og_image": None,
            "image_urls": [],
            "html": "<html><body></body></html>",
            "page_text": "",
            "overlay_actions": [],
        }

    @pytest.mark.asyncio
    async def test_blank_page_detected(self, _blank_screenshot_result):
        """Blank screenshot (no title, no text) is flagged in response."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_blank_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://blocked-site.com"})

        data = resp.json()
        assert data["ok"] is True
        assert data["page_text"] == ""
        assert data["title"] == ""

    @pytest.mark.asyncio
    async def test_non_blank_page_has_content(self, _mock_screenshot_result):
        """Normal page has title and page_text."""
        with (
            patch("app.browser_fallback.screenshot_page", new_callable=AsyncMock, return_value=_mock_screenshot_result),
            patch("app.thumbnail.create_thumbnails", new_callable=AsyncMock, return_value=[]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/screenshot", json={"url": "https://example.com"})

        data = resp.json()
        assert data["ok"] is True
        assert data["title"] == "Test Page"
        assert len(data["page_text"]) > 0


class TestURLNormalization:
    """Tests for _normalize_url in the tool."""

    def test_bare_domain(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("www.lemonde.fr") == "https://www.lemonde.fr"

    def test_already_https(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("https://example.com") == "https://example.com"

    def test_already_http(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("http://example.com") == "http://example.com"

    def test_with_path(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("example.com/page") == "https://example.com/page"

    def test_empty(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("") == ""

    def test_strips_whitespace(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("  www.example.com  ") == "https://www.example.com"

    def test_leading_slashes_stripped(self):
        from app.openwebui_tool import _normalize_url

        assert _normalize_url("//example.com") == "https://example.com"
