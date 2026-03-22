"""Optional Playwright-based browser fallback for JS-heavy pages."""

from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_browser_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _browser_semaphore
    if _browser_semaphore is None:
        _browser_semaphore = asyncio.Semaphore(settings.MAX_BROWSER_SESSIONS)
    return _browser_semaphore


async def fetch_with_browser(
    url: str,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """Fetch a page using headless Chromium and return rendered HTML.

    Raises ImportError if Playwright is not installed.
    Raises RuntimeError on browser errors.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError(
            "Playwright is not installed. Install it with: "
            "pip install playwright && playwright install chromium"
        )

    semaphore = _get_semaphore()

    async with semaphore:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="BrowserUse/1.0 (Playwright)",
                    extra_http_headers=headers or {},
                )

                if cookies:
                    cookie_list = [
                        {
                            "name": k,
                            "value": v,
                            "domain": _extract_domain(url),
                            "path": "/",
                        }
                        for k, v in cookies.items()
                    ]
                    await context.add_cookies(cookie_list)

                page = await context.new_page()

                try:
                    await page.goto(url, wait_until="networkidle", timeout=15_000)
                except Exception as exc:
                    logger.warning(
                        "Playwright networkidle timeout for %s, using domcontentloaded: %s",
                        url, exc,
                    )
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    except Exception as exc2:
                        raise RuntimeError(
                            f"Playwright failed to load {url}: {exc2}"
                        ) from exc2

                html = await page.content()
                await context.close()
                return html
            finally:
                await browser.close()


def _extract_domain(url: str) -> str:
    """Extract domain from URL for cookie setting."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or ""
