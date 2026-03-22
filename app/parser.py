"""HTML parsing chain: trafilatura → BeautifulSoup → raw text."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from app.models import ParsedContent

logger = logging.getLogger(__name__)


def parse_html(html: str, url: str) -> ParsedContent:
    """Parse HTML using a three-level fallback chain."""
    result = _try_trafilatura(html, url)
    if result and len(result.content) >= 100:
        return result

    result_bs = _try_beautifulsoup(html, url)
    if result_bs and len(result_bs.content) >= 50:
        # Merge metadata from trafilatura if available
        if result and result.title != "Untitled":
            result_bs.title = result.title
        if result and result.language != "unknown":
            result_bs.language = result.language
        return result_bs

    result_raw = _try_raw_text(html, url)
    if result and result.title != "Untitled":
        result_raw.title = result.title
    if result and result.language != "unknown":
        result_raw.language = result.language
    return result_raw


def _try_trafilatura(html: str, url: str) -> ParsedContent | None:
    """Level 1: trafilatura extraction."""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            url=url,
            include_links=True,
            include_images=True,
            include_tables=True,
            output_format="txt",
        )
        if not extracted:
            return None

        # Get metadata
        metadata = trafilatura.extract_metadata(html, default_url=url)
        title = "Untitled"
        language = "unknown"
        if metadata:
            title = metadata.title or "Untitled"
            if hasattr(metadata, "language") and metadata.language:
                language = metadata.language

        soup = BeautifulSoup(html, "lxml")
        images = _extract_images(soup, url)
        links = _extract_links(soup, url)
        headings = _extract_headings(soup)

        return ParsedContent(
            title=title,
            content=extracted,
            headings=headings,
            links=links,
            images=images,
            language=language,
            method="trafilatura",
        )
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return None


def _try_beautifulsoup(html: str, url: str) -> ParsedContent | None:
    """Level 2: BeautifulSoup structured DOM cleanup."""
    try:
        soup = BeautifulSoup(html, "lxml")

        # Remove script, style, nav, footer, header
        for tag in soup.find_all(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # Try to find main content area
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            return None

        content = main.get_text(separator="\n", strip=True)
        if not content:
            return None

        images = _extract_images(soup, url)
        links = _extract_links(soup, url)
        headings = _extract_headings(soup)

        return ParsedContent(
            title=title,
            content=content,
            headings=headings,
            links=links,
            images=images,
            language="unknown",
            method="beautifulsoup",
        )
    except Exception as exc:
        logger.warning("BeautifulSoup extraction failed: %s", exc)
        return None


def _try_raw_text(html: str, url: str) -> ParsedContent:
    """Level 3: strip all tags, collapse whitespace."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"

    raw = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    raw = re.sub(r"\s+", " ", raw).strip()

    return ParsedContent(
        title=title,
        content=raw,
        method="raw_text",
    )


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """Extract image tags with src and alt."""
    from urllib.parse import urljoin

    images: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue

        # Skip tiny tracking pixels
        width = img.get("width", "")
        height = img.get("height", "")
        try:
            if width and height and int(width) < 100 and int(height) < 100:
                continue
        except (ValueError, TypeError):
            pass

        # Skip common tracking patterns
        src_lower = src.lower()
        if any(p in src_lower for p in ("/pixel", "/beacon", "/1x1", "/track")):
            continue

        abs_url = urljoin(base_url, src)
        alt = img.get("alt", "")
        images.append({"url": abs_url, "alt": alt})
    return images


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """Extract anchor tags with href and text."""
    from urllib.parse import urljoin

    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        text = a.get_text(strip=True) or abs_url
        links.append({"url": abs_url, "text": text})
    return links


def _extract_headings(soup: BeautifulSoup) -> list[str]:
    """Extract heading text from h1-h6."""
    headings: list[str] = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        text = tag.get_text(strip=True)
        if text:
            headings.append(text)
    return headings
