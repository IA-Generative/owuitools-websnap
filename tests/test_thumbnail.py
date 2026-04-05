"""Tests for the thumbnail creation module."""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock, patch

import pytest


class TestCreateThumbnails:
    """Tests for thumbnail.create_thumbnails()."""

    @staticmethod
    def _make_test_image(width: int = 800, height: int = 600, fmt: str = "PNG") -> bytes:
        """Create a test image of given dimensions."""
        from PIL import Image

        img = Image.new("RGB", (width, height), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()

    @pytest.mark.asyncio
    async def test_basic_thumbnail(self):
        """Downloads an image and creates a JPEG thumbnail."""
        from app.thumbnail import create_thumbnails

        image_bytes = self._make_test_image(800, 600)

        mock_response = AsyncMock()
        mock_response.content = image_bytes
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [{"url": "https://example.com/photo.jpg", "alt": "Photo", "width": 800, "height": 600}],
                max_images=5,
                thumbnail_width=400,
            )

        assert len(results) == 1
        assert results[0]["alt"] == "Photo"
        assert results[0]["thumbnail_base64"].startswith("data:image/jpeg;base64,")
        # Verify it's valid base64
        b64_data = results[0]["thumbnail_base64"].split(",", 1)[1]
        decoded = base64.b64decode(b64_data)
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_thumbnail_respects_aspect_ratio(self):
        """Thumbnail maintains aspect ratio when resizing."""
        from PIL import Image

        from app.thumbnail import create_thumbnails

        image_bytes = self._make_test_image(1600, 800)  # 2:1 ratio

        mock_response = AsyncMock()
        mock_response.content = image_bytes
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [{"url": "https://example.com/wide.jpg", "alt": "Wide", "width": 1600, "height": 800}],
                thumbnail_width=400,
            )

        assert len(results) == 1
        # Width should be <= 400, height should be proportional (200)
        assert results[0]["width"] <= 400
        assert results[0]["height"] <= 200

    @pytest.mark.asyncio
    async def test_max_images_limit(self):
        """Only processes up to max_images images."""
        from app.thumbnail import create_thumbnails

        image_bytes = self._make_test_image(200, 200)

        mock_response = AsyncMock()
        mock_response.content = image_bytes
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        images = [
            {"url": f"https://example.com/img{i}.jpg", "alt": f"Image {i}", "width": 200, "height": 200}
            for i in range(10)
        ]

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(images, max_images=3, thumbnail_width=100)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_inaccessible_image_skipped(self):
        """Images that fail to download are silently skipped."""
        from app.thumbnail import create_thumbnails

        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock(side_effect=Exception("404 Not Found"))

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [{"url": "https://example.com/missing.jpg", "alt": "Missing", "width": 400, "height": 300}],
            )

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_oversized_image_skipped(self):
        """Images larger than 5 MB are skipped."""
        from app.thumbnail import create_thumbnails

        mock_response = AsyncMock()
        mock_response.content = b"\x00" * (6 * 1024 * 1024)  # 6 MB
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [{"url": "https://example.com/huge.jpg", "alt": "Huge", "width": 4000, "height": 3000}],
            )

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_rgba_image_converted(self):
        """RGBA images (PNG with transparency) are converted to RGB for JPEG output."""
        from PIL import Image

        from app.thumbnail import create_thumbnails

        # Create RGBA image
        img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        mock_response = AsyncMock()
        mock_response.content = image_bytes
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [{"url": "https://example.com/transparent.png", "alt": "Transparent", "width": 200, "height": 200}],
            )

        assert len(results) == 1
        assert results[0]["thumbnail_base64"].startswith("data:image/jpeg;base64,")

    @pytest.mark.asyncio
    async def test_invalid_url_scheme_skipped(self):
        """Non-HTTP URLs are skipped."""
        from app.thumbnail import create_thumbnails

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.thumbnail.httpx.AsyncClient", return_value=mock_client):
            results = await create_thumbnails(
                [
                    {"url": "data:image/png;base64,abc", "alt": "Data URI", "width": 100, "height": 100},
                    {"url": "", "alt": "Empty", "width": 100, "height": 100},
                    {"url": "file:///etc/passwd", "alt": "File", "width": 100, "height": 100},
                ],
            )

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_pillow_not_installed(self):
        """Returns empty list when Pillow is not installed."""
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            # Need to reload to trigger the ImportError
            import importlib
            import app.thumbnail

            importlib.reload(app.thumbnail)

            # Pillow import fails inside the function
            from app.thumbnail import create_thumbnails

            results = await create_thumbnails(
                [{"url": "https://example.com/img.jpg", "alt": "Test", "width": 200, "height": 200}],
            )
            assert results == []

            # Restore
            importlib.reload(app.thumbnail)
