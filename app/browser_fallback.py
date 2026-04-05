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


# JS injected before page load to mask headless signals
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};
Object.defineProperty(navigator, 'permissions', {get: () => ({
  query: (p) => Promise.resolve({state: p.name === 'notifications' ? 'denied' : 'prompt'})
})});
"""

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


async def _navigate_with_challenge_retry(page, url: str, max_retries: int = 2) -> None:
    """Navigate to a URL, retrying if an anti-bot challenge blocks the page.

    Some sites (liberation.fr, etc.) serve a JS challenge that redirects after
    a few seconds.  We detect this by checking visible body text length after
    load — if it's very short, we wait and let the challenge resolve.
    """
    for attempt in range(max_retries + 1):
        try:
            await page.goto(url, wait_until="networkidle", timeout=20_000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            except Exception as exc:
                if attempt == max_retries:
                    raise RuntimeError(f"Playwright failed to load {url}: {exc}") from exc
                continue

        # Check if the page has meaningful content
        body_len = await page.evaluate(
            "(document.body && document.body.innerText || '').trim().length"
        )
        if body_len > 200:
            return  # page loaded successfully

        if attempt < max_retries:
            logger.info(
                "Challenge detected on %s (body=%d chars), waiting before retry %d/%d",
                url, body_len, attempt + 1, max_retries,
            )
            # Wait for challenge JS to resolve (redirect, cookie set, etc.)
            await asyncio.sleep(4)
            # Some challenges set cookies then need a fresh navigation
            try:
                await page.reload(wait_until="networkidle", timeout=15_000)
            except Exception:
                pass

    logger.warning("Page %s still thin after %d retries (anti-bot?)", url, max_retries)


# ---------------------------------------------------------------------------
# Overlay / cookie-wall / ad-wall dismissal
# ---------------------------------------------------------------------------

# CSS selectors for common consent / cookie banners (CMP frameworks + custom)
_CONSENT_BUTTON_SELECTORS = [
    # ---- Specific CMP frameworks ----
    "#tarteaucitronPersonalize2",                          # TarteAuCitron (FR gov)
    "#tarteaucitronAllDenied2",
    "button.didomi-components-button--first",              # Didomi
    "#didomi-notice-agree-button",
    "#didomi-notice-disagree-button",
    ".sd-cmp-3Y1YG",                                       # Sirdata CMP
    "#axeptio_btn_acceptAll",                               # Axeptio
    "#axeptio_btn_dismiss",
    "#onetrust-accept-btn-handler",                         # OneTrust
    "#onetrust-reject-all-handler",
    ".onetrust-close-btn-handler",
    "#CybsAccessibilityConsentAccept",                      # CybsAccessibility
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "#CybotCookiebotDialogBodyButtonDecline",
    ".cc-btn.cc-dismiss",                                   # Cookie Consent (Osano)
    "#cookies-eu-accept",                                   # cookies-eu-banner
    # ---- Generic patterns (attribute-based) ----
    "button[data-testid='cookie-accept']",
    "button[data-testid='cookie-reject']",
    "button[data-action='accept']",
    "[data-gdpr-consent='accept']",
    "[data-cookie-accept]",
    # ---- Broad aria / role patterns ----
    "div[role='dialog'] button[aria-label*='ccept']",
    "div[role='dialog'] button[aria-label*='onsentir']",
    "div[role='dialog'] button[aria-label*='ermer']",
    "div[role='dialog'] button[aria-label*='lose']",
]

# Text patterns to match on visible button text (case-insensitive substrings).
# Tried only inside elements that look like overlays / banners.
_CONSENT_BUTTON_TEXTS_FR = [
    "tout accepter", "accepter tout", "accepter et fermer",
    "accepter les cookies", "j'accepte", "j'ai compris",
    "continuer sans accepter", "tout refuser", "refuser tout",
    "refuser et fermer", "fermer",
]
_CONSENT_BUTTON_TEXTS_EN = [
    "accept all", "accept cookies", "allow all", "allow cookies",
    "i agree", "got it", "ok", "okay",
    "reject all", "deny all", "decline all",
    "close", "dismiss", "continue without accepting",
]
_CONSENT_BUTTON_TEXTS = _CONSENT_BUTTON_TEXTS_FR + _CONSENT_BUTTON_TEXTS_EN

# JS snippet to nuke overlay / fixed-position elements that block the page
_JS_REMOVE_OVERLAYS = """
(() => {
    const removed = [];

    // 1. Remove common overlay containers by ID / class patterns
    const overlayPatterns = [
        /cookie/i, /consent/i, /gdpr/i, /banner/i, /overlay/i,
        /popup/i, /modal/i, /tarteaucitron/i, /didomi/i, /onetrust/i,
        /axeptio/i, /cookiebot/i, /cc-window/i, /cmp/i,
    ];
    for (const el of document.querySelectorAll('div, section, aside, dialog')) {
        const sig = (el.id || '') + ' ' + (el.className || '');
        if (overlayPatterns.some(p => p.test(sig))) {
            const style = getComputedStyle(el);
            if (['fixed', 'sticky'].includes(style.position) ||
                parseInt(style.zIndex) > 999) {
                removed.push(el.tagName + '#' + el.id + '.' + el.className);
                el.remove();
            }
        }
    }

    // 2. Remove any remaining full-viewport fixed overlay (z-index > 999)
    for (const el of document.querySelectorAll('*')) {
        const style = getComputedStyle(el);
        if (style.position === 'fixed' && parseInt(style.zIndex) > 9999) {
            const rect = el.getBoundingClientRect();
            if (rect.width > window.innerWidth * 0.5 &&
                rect.height > window.innerHeight * 0.3) {
                removed.push('fullscreen:' + el.tagName);
                el.remove();
            }
        }
    }

    // 3. Restore scroll on body/html
    for (const tag of [document.body, document.documentElement]) {
        if (tag) {
            tag.style.overflow = '';
            tag.style.position = '';
            tag.classList.remove('no-scroll', 'modal-open', 'noscroll');
        }
    }

    return removed;
})()
"""


async def _scroll_for_lazy_load(page, pause: float = 0.4, max_scrolls: int = 10) -> None:
    """Scroll down progressively to trigger lazy-loaded content."""
    try:
        prev_height = 0
        for _ in range(max_scrolls):
            height = await page.evaluate("document.body.scrollHeight")
            if height == prev_height:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(pause)
            prev_height = height
        # Scroll back to top for the screenshot
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.2)
    except Exception as exc:
        logger.debug("Scroll for lazy load failed: %s", exc)


async def _dismiss_overlays(page) -> list[str]:
    """Try to dismiss cookie / ad / GDPR overlays on the page.

    Returns a list of actions taken (for logging).
    """
    actions: list[str] = []

    # Phase 1: click known consent buttons by CSS selector
    for selector in _CONSENT_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=200):
                await btn.click(timeout=1000)
                actions.append(f"clicked:{selector}")
                await page.wait_for_timeout(500)
                break  # one click is usually enough
        except Exception:
            continue

    # Phase 2: if no known selector matched, try text-based matching
    if not actions:
        for text in _CONSENT_BUTTON_TEXTS:
            try:
                btn = page.get_by_role("button", name=text, exact=False).first
                if await btn.is_visible(timeout=200):
                    await btn.click(timeout=1000)
                    actions.append(f"clicked-text:'{text}'")
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                continue

    # Phase 3: if no clickable button found, try links (<a>) with consent text
    if not actions:
        for text in _CONSENT_BUTTON_TEXTS:
            try:
                link = page.get_by_role("link", name=text, exact=False).first
                if await link.is_visible(timeout=200):
                    await link.click(timeout=1000)
                    actions.append(f"clicked-link:'{text}'")
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                continue

    # Phase 4: JS nuclear option — remove remaining overlay DOM elements
    try:
        removed = await page.evaluate(_JS_REMOVE_OVERLAYS)
        if removed:
            actions.append(f"js-removed:{len(removed)} overlays")
    except Exception as exc:
        logger.debug("JS overlay removal failed: %s", exc)

    if actions:
        logger.info("Overlay dismissal on %s: %s", page.url, actions)

    return actions


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
            launch_opts = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if settings.PROXY_URL:
                launch_opts["proxy"] = {"server": settings.PROXY_URL}
            browser = await p.chromium.launch(**launch_opts)
            try:
                context = await browser.new_context(
                    user_agent=_CHROME_UA,
                    extra_http_headers=headers or {},
                )
                await context.add_init_script(_STEALTH_JS)

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
                await _navigate_with_challenge_retry(page, url)
                await _dismiss_overlays(page)
                await _scroll_for_lazy_load(page)

                html = await page.content()
                await context.close()
                return html
            finally:
                await browser.close()


async def screenshot_page(
    url: str,
    full_page: bool = True,
    width: int = 1280,
    height: int = 800,
    wait_seconds: float = 2.0,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """Capture screenshot + extract metadata from a page using Playwright.

    Returns:
        {
            "screenshot": bytes,          # PNG screenshot
            "title": str,
            "description": str,
            "og_image": str | None,       # Open Graph image URL
            "image_urls": list[dict],     # Significant images found
            "html": str,                  # Rendered HTML
        }

    Raises ImportError if Playwright is not installed.
    Raises RuntimeError on browser errors.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError(
            "Playwright is not installed. Use the websnap-full image."
        )

    semaphore = _get_semaphore()

    async with semaphore:
        async with async_playwright() as p:
            launch_opts = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if settings.PROXY_URL:
                launch_opts["proxy"] = {"server": settings.PROXY_URL}
            browser = await p.chromium.launch(**launch_opts)
            try:
                context = await browser.new_context(
                    viewport={"width": width, "height": height},
                    user_agent=_CHROME_UA,
                    extra_http_headers=headers or {},
                )
                await context.add_init_script(_STEALTH_JS)

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
                await _navigate_with_challenge_retry(page, url)

                # Extra wait for JS/animations/lazy load
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # Dismiss cookie banners, ad walls, GDPR popups
                overlay_actions = await _dismiss_overlays(page)

                # Scroll down to trigger lazy-loaded content
                await _scroll_for_lazy_load(page)

                # Small pause for animations to settle
                await asyncio.sleep(0.3)

                # Take screenshot
                screenshot_bytes = await page.screenshot(
                    full_page=full_page, type="png", timeout=20_000,
                )

                # Extract metadata via JS
                title = await page.title()

                description = await page.evaluate(
                    "document.querySelector('meta[name=\"description\"]')?.content || ''"
                )

                og_image = await page.evaluate(
                    "document.querySelector('meta[property=\"og:image\"]')?.content || ''"
                )

                image_urls = await page.evaluate("""
                    Array.from(document.querySelectorAll('img'))
                        .filter(img => img.naturalWidth > 100 && img.naturalHeight > 100)
                        .slice(0, 20)
                        .map(img => ({
                            url: img.src,
                            alt: img.alt || '',
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                        }))
                """)

                # Extract visible text content from the page
                page_text = await page.evaluate("""
                    (() => {
                        const skip = new Set([
                            'SCRIPT','STYLE','NOSCRIPT','SVG','HEAD','META','LINK',
                            'IFRAME','OBJECT','EMBED','TEMPLATE',
                        ]);
                        function walk(node) {
                            if (node.nodeType === 3) return node.textContent;
                            if (node.nodeType !== 1) return '';
                            if (skip.has(node.tagName)) return '';
                            const s = getComputedStyle(node);
                            if (s.display === 'none' || s.visibility === 'hidden') return '';
                            const parts = [];
                            for (const c of node.childNodes) parts.push(walk(c));
                            let text = parts.join(' ');
                            const block = ['DIV','P','H1','H2','H3','H4','H5','H6',
                                           'LI','TR','BLOCKQUOTE','SECTION','ARTICLE',
                                           'HEADER','FOOTER','NAV','MAIN','FIGCAPTION'];
                            if (block.includes(node.tagName)) text = '\\n' + text + '\\n';
                            return text;
                        }
                        let raw = walk(document.body || document.documentElement);
                        // collapse whitespace
                        return raw.replace(/[ \\t]+/g, ' ')
                                  .replace(/\\n{3,}/g, '\\n\\n')
                                  .trim()
                                  .slice(0, 8000);
                    })()
                """)

                html = await page.content()
                await context.close()

                return {
                    "screenshot": screenshot_bytes,
                    "title": title,
                    "description": description or "",
                    "og_image": og_image or None,
                    "image_urls": image_urls or [],
                    "html": html,
                    "page_text": page_text or "",
                    "overlay_actions": overlay_actions,
                }
            finally:
                await browser.close()


def _extract_domain(url: str) -> str:
    """Extract domain from URL for cookie setting."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or ""
