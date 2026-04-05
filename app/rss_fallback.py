"""RSS feed fallback for sites blocked by anti-bot protection."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# Well-known RSS paths, tried in order
_COMMON_RSS_PATHS = [
    "/rss",
    "/rss.xml",
    "/feed",
    "/feed.xml",
    "/atom.xml",
    "/rss/une.xml",               # Le Monde
    "/rss/figaro_une.xml",        # Le Figaro
    "/feeds/rss-une.xml",         # 20 Minutes
    "/titres.rss",                # France TV Info
    "/rss/news-24-7/",            # BFM TV
    "/arc/outboundfeeds/rss/",    # Arc Publishing (Libération, Le Parisien, etc.)
]

_RSS_UA = (
    "Mozilla/5.0 (compatible; WebSnap/1.0; +https://github.com/websnap) "
    "RSS-Reader"
)

# Namespaces used in RSS/Atom feeds
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}


async def discover_rss_url(url: str, html: str = "") -> str | None:
    """Try to find an RSS feed URL for a given site.

    1. Parse <link rel="alternate" type="application/rss+xml"> from HTML
    2. Probe common RSS paths
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"

    # Method 1: HTML autodiscovery
    if html:
        match = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)',
            html,
            re.IGNORECASE,
        )
        if match:
            rss_url = urljoin(url, match.group(1))
            logger.info("RSS discovered via HTML link tag: %s", rss_url)
            return rss_url

    # Method 2: probe common paths
    async with httpx.AsyncClient(
        timeout=10,
        headers={"User-Agent": _RSS_UA},
        follow_redirects=True,
    ) as client:
        for path in _COMMON_RSS_PATHS:
            candidate = base + path
            try:
                resp = await client.head(candidate)
                ct = resp.headers.get("content-type", "")
                if resp.status_code == 200 and (
                    "xml" in ct or "rss" in ct or "atom" in ct
                ):
                    logger.info("RSS discovered via probe: %s", candidate)
                    return candidate
            except Exception:
                continue

    return None


async def fetch_and_parse_rss(rss_url: str, max_items: int = 15) -> dict:
    """Fetch an RSS/Atom feed and return structured content.

    Returns:
        {
            "ok": True/False,
            "feed_title": str,
            "feed_url": str,
            "items": [
                {
                    "title": str,
                    "link": str,
                    "description": str,
                    "author": str,
                    "pub_date": str,
                    "image_url": str | None,
                },
                ...
            ],
            "error": str | None,
        }
    """
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": _RSS_UA},
            follow_redirects=True,
        ) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
            xml_bytes = resp.content
    except Exception as exc:
        return {"ok": False, "feed_title": "", "feed_url": rss_url, "items": [], "error": str(exc)}

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        return {"ok": False, "feed_title": "", "feed_url": rss_url, "items": [], "error": f"XML parse error: {exc}"}

    # Detect RSS 2.0 vs Atom
    if root.tag == "rss" or root.find("channel") is not None:
        return _parse_rss2(root, rss_url, max_items)
    elif root.tag.endswith("feed") or root.find("{http://www.w3.org/2005/Atom}entry") is not None:
        return _parse_atom(root, rss_url, max_items)
    else:
        return {"ok": False, "feed_title": "", "feed_url": rss_url, "items": [], "error": "Unknown feed format"}


def _parse_rss2(root: ET.Element, feed_url: str, max_items: int) -> dict:
    channel = root.find("channel")
    if channel is None:
        return {"ok": False, "feed_title": "", "feed_url": feed_url, "items": [], "error": "No <channel> in RSS"}

    feed_title = _text(channel, "title")
    items = []

    for item_el in channel.findall("item")[:max_items]:
        # Try media:content for image
        image_url = None
        media_content = item_el.find("media:content", _NS)
        if media_content is not None:
            image_url = media_content.get("url")

        # Try content:encoded for full text, fall back to description
        description = _text(item_el, "content:encoded", _NS) or _text(item_el, "description")
        # Strip HTML tags from description
        description = _strip_html(description)

        items.append({
            "title": _text(item_el, "title"),
            "link": _text(item_el, "link"),
            "description": description[:1000],
            "author": _text(item_el, "dc:creator", _NS) or _text(item_el, "author"),
            "pub_date": _text(item_el, "pubDate"),
            "image_url": image_url,
        })

    return {"ok": True, "feed_title": feed_title, "feed_url": feed_url, "items": items, "error": None}


def _parse_atom(root: ET.Element, feed_url: str, max_items: int) -> dict:
    ns = "http://www.w3.org/2005/Atom"
    feed_title = _text(root, f"{{{ns}}}title")
    items = []

    for entry in root.findall(f"{{{ns}}}entry")[:max_items]:
        link_el = entry.find(f"{{{ns}}}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{{{ns}}}link")
        link = link_el.get("href", "") if link_el is not None else ""

        summary = _text(entry, f"{{{ns}}}summary") or _text(entry, f"{{{ns}}}content")
        summary = _strip_html(summary)

        items.append({
            "title": _text(entry, f"{{{ns}}}title"),
            "link": link,
            "description": summary[:1000],
            "author": _text(entry, f"{{{ns}}}author/{{{ns}}}name"),
            "pub_date": _text(entry, f"{{{ns}}}published") or _text(entry, f"{{{ns}}}updated"),
            "image_url": None,
        })

    return {"ok": True, "feed_title": feed_title, "feed_url": feed_url, "items": items, "error": None}


def rss_to_markdown(feed: dict, source_url: str) -> str:
    """Convert parsed RSS feed to markdown."""
    if not feed["ok"]:
        return ""

    parts = [f"# {feed['feed_title']}\n"]
    parts.append(f"*Source : {source_url} — via flux RSS*\n")

    for item in feed["items"]:
        parts.append(f"## [{item['title']}]({item['link']})\n")
        if item["author"]:
            parts.append(f"*{item['author']}*")
        if item["pub_date"]:
            parts.append(f" — {item['pub_date']}")
        if item["author"] or item["pub_date"]:
            parts.append("\n")
        if item["description"]:
            parts.append(f"\n{item['description']}\n")
        parts.append("")

    return "\n".join(parts)


def _text(el: ET.Element, tag: str, ns: dict | None = None) -> str:
    child = el.find(tag, ns) if ns else el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()
