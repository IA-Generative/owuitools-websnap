"""Tests for the RSS feed fallback module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.rss_fallback import (
    discover_rss_url,
    fetch_and_parse_rss,
    rss_to_markdown,
    _strip_html,
)


SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Test Feed</title>
  <link>https://example.com</link>
  <item>
    <title>Article One</title>
    <link>https://example.com/article-1</link>
    <description>&lt;p&gt;First article &lt;b&gt;content&lt;/b&gt;&lt;/p&gt;</description>
    <dc:creator>Alice</dc:creator>
    <pubDate>Mon, 01 Apr 2026 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Article Two</title>
    <link>https://example.com/article-2</link>
    <description>Second article plain text</description>
    <dc:creator>Bob</dc:creator>
    <pubDate>Tue, 02 Apr 2026 12:00:00 +0000</pubDate>
  </item>
</channel>
</rss>"""

SAMPLE_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Entry One</title>
    <link rel="alternate" href="https://example.com/entry-1"/>
    <summary>Summary of entry one</summary>
    <author><name>Charlie</name></author>
    <published>2026-04-01T10:00:00Z</published>
  </entry>
</feed>"""

HTML_WITH_RSS_LINK = """\
<html><head>
<link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS">
</head><body></body></html>"""


class TestRSSDiscovery:
    """Tests for discover_rss_url."""

    @pytest.mark.asyncio
    async def test_discover_from_html_link_tag(self):
        """RSS URL found via <link rel=alternate> in HTML."""
        url = await discover_rss_url("https://example.com", html=HTML_WITH_RSS_LINK)
        assert url == "https://example.com/feed.xml"

    @pytest.mark.asyncio
    async def test_discover_from_html_atom_link(self):
        html = '<html><head><link rel="alternate" type="application/atom+xml" href="/atom.xml"></head></html>'
        url = await discover_rss_url("https://example.com", html=html)
        assert url == "https://example.com/atom.xml"

    @pytest.mark.asyncio
    async def test_no_rss_in_html_probes_common_paths(self):
        """When HTML has no link tag, probe common paths."""
        import httpx

        # Mock httpx to return 200 for /rss.xml and 404 for everything else
        async def mock_head(self, url, **kwargs):
            resp = httpx.Response(
                status_code=200 if url.endswith("/rss.xml") else 404,
                headers={"content-type": "application/rss+xml" if url.endswith("/rss.xml") else "text/html"},
                request=httpx.Request("HEAD", url),
            )
            return resp

        with patch("httpx.AsyncClient.head", mock_head):
            url = await discover_rss_url("https://example.com", html="<html></html>")

        assert url is not None
        assert "/rss.xml" in url

    @pytest.mark.asyncio
    async def test_no_rss_found_returns_none(self):
        """When no RSS feed is found, return None."""
        import httpx

        async def mock_head(self, url, **kwargs):
            return httpx.Response(
                status_code=404,
                headers={"content-type": "text/html"},
                request=httpx.Request("HEAD", url),
            )

        with patch("httpx.AsyncClient.head", mock_head):
            url = await discover_rss_url("https://example.com", html="<html></html>")

        assert url is None


class TestRSSParsing:
    """Tests for fetch_and_parse_rss."""

    @pytest.mark.asyncio
    async def test_parse_rss2(self):
        """Parse a standard RSS 2.0 feed."""
        import httpx

        async def mock_get(self, url, **kwargs):
            return httpx.Response(
                status_code=200,
                content=SAMPLE_RSS.encode(),
                headers={"content-type": "application/rss+xml"},
                request=httpx.Request("GET", url),
            )

        with patch("httpx.AsyncClient.get", mock_get):
            feed = await fetch_and_parse_rss("https://example.com/rss.xml")

        assert feed["ok"] is True
        assert feed["feed_title"] == "Test Feed"
        assert len(feed["items"]) == 2
        assert feed["items"][0]["title"] == "Article One"
        assert feed["items"][0]["author"] == "Alice"
        assert "First article content" in feed["items"][0]["description"]
        assert feed["items"][1]["title"] == "Article Two"

    @pytest.mark.asyncio
    async def test_parse_atom(self):
        """Parse an Atom feed."""
        import httpx

        async def mock_get(self, url, **kwargs):
            return httpx.Response(
                status_code=200,
                content=SAMPLE_ATOM.encode(),
                headers={"content-type": "application/atom+xml"},
                request=httpx.Request("GET", url),
            )

        with patch("httpx.AsyncClient.get", mock_get):
            feed = await fetch_and_parse_rss("https://example.com/atom.xml")

        assert feed["ok"] is True
        assert feed["feed_title"] == "Atom Feed"
        assert len(feed["items"]) == 1
        assert feed["items"][0]["title"] == "Entry One"
        assert feed["items"][0]["author"] == "Charlie"
        assert feed["items"][0]["link"] == "https://example.com/entry-1"

    @pytest.mark.asyncio
    async def test_fetch_failure(self):
        """Network error returns ok=False."""
        import httpx

        async def mock_get(self, url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient.get", mock_get):
            feed = await fetch_and_parse_rss("https://example.com/rss.xml")

        assert feed["ok"] is False
        assert "Connection refused" in feed["error"]

    @pytest.mark.asyncio
    async def test_invalid_xml(self):
        """Malformed XML returns ok=False."""
        import httpx

        async def mock_get(self, url, **kwargs):
            return httpx.Response(
                status_code=200,
                content=b"<not valid xml",
                headers={"content-type": "application/rss+xml"},
                request=httpx.Request("GET", url),
            )

        with patch("httpx.AsyncClient.get", mock_get):
            feed = await fetch_and_parse_rss("https://example.com/rss.xml")

        assert feed["ok"] is False
        assert "XML" in feed["error"]

    @pytest.mark.asyncio
    async def test_max_items_respected(self):
        """Feed parsing respects max_items limit."""
        import httpx

        async def mock_get(self, url, **kwargs):
            return httpx.Response(
                status_code=200,
                content=SAMPLE_RSS.encode(),
                headers={"content-type": "application/rss+xml"},
                request=httpx.Request("GET", url),
            )

        with patch("httpx.AsyncClient.get", mock_get):
            feed = await fetch_and_parse_rss("https://example.com/rss.xml", max_items=1)

        assert feed["ok"] is True
        assert len(feed["items"]) == 1


class TestRSSToMarkdown:
    """Tests for rss_to_markdown."""

    def test_basic_conversion(self):
        feed = {
            "ok": True,
            "feed_title": "My Feed",
            "feed_url": "https://example.com/rss",
            "items": [
                {
                    "title": "Test Article",
                    "link": "https://example.com/article",
                    "description": "Article description",
                    "author": "Author",
                    "pub_date": "Mon, 01 Apr 2026",
                    "image_url": None,
                },
            ],
            "error": None,
        }
        md = rss_to_markdown(feed, "https://example.com")
        assert "# My Feed" in md
        assert "via flux RSS" in md
        assert "[Test Article]" in md
        assert "Author" in md
        assert "Article description" in md

    def test_empty_feed(self):
        feed = {"ok": False, "feed_title": "", "feed_url": "", "items": [], "error": "fail"}
        md = rss_to_markdown(feed, "https://example.com")
        assert md == ""


class TestStripHTML:
    """Tests for _strip_html helper."""

    def test_strips_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"
