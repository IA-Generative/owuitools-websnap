"""Main extraction orchestrator — coordinates the full pipeline."""

from __future__ import annotations

import logging

from app.auth_detector import detect_auth_wall
from app.config import settings
from app.fetcher import fetch_url
from app.image_handler import analyze_images, filter_images
from app.markdown_builder import build_markdown
from app.models import ExtractionError, ExtractionResult, ExtractionStage
from app.parser import parse_html
from app.pdf_handler import extract_pdf, is_pdf
from app.utils import extraction_cache

logger = logging.getLogger(__name__)


async def browse_and_extract(
    url: str,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    use_browser_fallback: bool = False,
    force_browser: bool = False,
) -> ExtractionResult:
    """Orchestrate the full extraction pipeline. Return structured result."""
    errors: list[ExtractionError] = []
    metadata: dict = {}

    # Check cache first (skip for PDFs — determined later)
    cache_key = extraction_cache.make_key(url, cookies, headers)
    cached = await extraction_cache.get(cache_key)
    if cached is not None:
        logger.info("Cache hit for %s", url)
        return cached

    # Step 1-3: Fetch
    try:
        fetch_result = await fetch_url(url, cookies=cookies, headers=headers)
    except ValueError as exc:
        errors.append(ExtractionError(
            stage=ExtractionStage.FETCH,
            message=str(exc),
            recoverable=False,
        ))
        return ExtractionResult(ok=False, markdown="", metadata=metadata, errors=errors)
    except Exception as exc:
        errors.append(ExtractionError(
            stage=ExtractionStage.FETCH,
            message=f"Unexpected fetch error: {exc}",
            recoverable=False,
        ))
        return ExtractionResult(ok=False, markdown="", metadata=metadata, errors=errors)

    metadata["status_code"] = fetch_result.status_code
    metadata["final_url"] = fetch_result.final_url
    metadata["content_type"] = fetch_result.content_type

    # Handle non-success status codes
    if fetch_result.status_code == 429:
        errors.append(ExtractionError(
            stage=ExtractionStage.FETCH,
            message="Rate limited (HTTP 429)",
            recoverable=True,
        ))

    # Step 4-5: PDF detection and extraction
    if is_pdf(fetch_result.content_type, fetch_result.final_url):
        pdf_markdown, pdf_meta, pdf_errors = extract_pdf(
            fetch_result.body, fetch_result.final_url
        )
        errors.extend(pdf_errors)
        metadata.update(pdf_meta)

        md = build_markdown(
            original_url=url,
            final_url=fetch_result.final_url,
            content_type=fetch_result.content_type,
            pdf_markdown=pdf_markdown,
            pdf_metadata=pdf_meta,
            errors=errors,
            extraction_method="pdf",
        )
        result = ExtractionResult(
            ok=bool(pdf_markdown),
            markdown=md,
            metadata=metadata,
            errors=errors,
        )
        # Don't cache PDFs (too large)
        return result

    # Step 6: Parse HTML
    html = _decode_body(fetch_result.body, fetch_result.content_type)
    extraction_method = "http"
    parsed = None
    auth_result = None

    try:
        parsed = parse_html(html, fetch_result.final_url)
    except Exception as exc:
        errors.append(ExtractionError(
            stage=ExtractionStage.PARSE,
            message=f"Parsing failed: {exc}",
            recoverable=True,
        ))

    # Auth detection
    try:
        auth_result = detect_auth_wall(fetch_result, html)
        if auth_result.is_auth_wall:
            extraction_method = "authenticated-http"
            metadata["auth_wall"] = True
            metadata["auth_signals"] = auth_result.signals
    except Exception as exc:
        logger.warning("Auth detection failed: %s", exc)

    # Step 7: Image analysis
    images_analysis = None
    if parsed and parsed.images:
        filtered = filter_images(parsed.images)
        if filtered:
            try:
                images_analysis, img_errors = await analyze_images(filtered)
                errors.extend(img_errors)
            except Exception as exc:
                errors.append(ExtractionError(
                    stage=ExtractionStage.IMAGE_ANALYSIS,
                    message=f"Image analysis failed: {exc}",
                    recoverable=True,
                ))

    # Step 8: Browser fallback
    # Trigger on: explicit flag + thin content, OR auth wall / 403 / 401, OR force_browser
    _thin_content = not parsed or not parsed.content or len(parsed.content) < 100
    _auth_blocked = (
        metadata.get("auth_wall")
        or fetch_result.status_code in (401, 403)
    )
    if (use_browser_fallback and _thin_content) or _auth_blocked or force_browser:
        try:
            from app.browser_fallback import fetch_with_browser

            browser_html = await fetch_with_browser(url, cookies=cookies, headers=headers)
            parsed = parse_html(browser_html, fetch_result.final_url)
            extraction_method = "browser-fallback"

            # Re-analyze images from browser-rendered content
            if parsed.images:
                filtered = filter_images(parsed.images)
                if filtered:
                    images_analysis, img_errors = await analyze_images(filtered)
                    errors.extend(img_errors)

        except ImportError:
            errors.append(ExtractionError(
                stage=ExtractionStage.BROWSER,
                message="Playwright not installed — browser fallback unavailable",
                recoverable=False,
            ))
        except Exception as exc:
            errors.append(ExtractionError(
                stage=ExtractionStage.BROWSER,
                message=f"Browser fallback failed: {exc}",
                recoverable=True,
            ))

    # Step 8b: RSS fallback — if still thin after browser fallback
    _still_thin = not parsed or not parsed.content or len(parsed.content) < 100
    if _still_thin and _auth_blocked:
        try:
            from app.rss_fallback import discover_rss_url, fetch_and_parse_rss, rss_to_markdown

            rss_url = await discover_rss_url(url, html)
            if rss_url:
                feed = await fetch_and_parse_rss(rss_url)
                if feed["ok"] and feed["items"]:
                    rss_md = rss_to_markdown(feed, url)
                    extraction_method = "rss-fallback"
                    metadata["rss_url"] = rss_url
                    metadata["rss_items"] = len(feed["items"])
                    logger.info("RSS fallback succeeded for %s (%d items)", url, len(feed["items"]))

                    result = ExtractionResult(
                        ok=True,
                        markdown=rss_md,
                        metadata=metadata,
                        errors=errors,
                    )
                    await extraction_cache.set(cache_key, result)
                    return result
        except Exception as exc:
            logger.warning("RSS fallback failed for %s: %s", url, exc)
            errors.append(ExtractionError(
                stage=ExtractionStage.BROWSER,
                message=f"RSS fallback failed: {exc}",
                recoverable=True,
            ))

    # Step 9: Build Markdown
    md = build_markdown(
        original_url=url,
        final_url=fetch_result.final_url,
        content_type=fetch_result.content_type,
        parsed=parsed,
        auth_result=auth_result,
        images=images_analysis,
        errors=errors,
        extraction_method=extraction_method,
    )

    ok = bool(parsed and parsed.content)
    result = ExtractionResult(ok=ok, markdown=md, metadata=metadata, errors=errors)

    # Cache the result
    await extraction_cache.set(cache_key, result)

    return result


def _decode_body(body: bytes, content_type: str) -> str:
    """Decode response body to string, handling charset detection."""
    # Try to extract charset from content-type
    charset = "utf-8"
    if "charset=" in content_type.lower():
        parts = content_type.lower().split("charset=")
        if len(parts) > 1:
            charset = parts[1].split(";")[0].strip()

    try:
        return body.decode(charset)
    except (UnicodeDecodeError, LookupError):
        # Fallback: try utf-8, then latin-1
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            return body.decode("latin-1", errors="replace")
