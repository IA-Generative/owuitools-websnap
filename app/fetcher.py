"""HTTP fetcher with SSRF-safe redirect handling and streaming size limits."""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from app.config import settings
from app.models import ExtractionError, ExtractionStage, FetchResult
from app.security import check_redirect_url, check_url_ssrf

logger = logging.getLogger(__name__)

USER_AGENT = "BrowserUse/1.0 (+https://github.com/browser-use)"


async def fetch_url(
    url: str,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch a URL with SSRF protection and streaming size enforcement."""
    validated_url = check_url_ssrf(url)

    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)

    redirect_chain: list[str] = []
    current_url = validated_url

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.HTTP_CONNECT_TIMEOUT,
            read=settings.HTTP_READ_TIMEOUT,
            write=settings.HTTP_READ_TIMEOUT,
            pool=settings.HTTP_READ_TIMEOUT,
        ),
        follow_redirects=False,
        cookies=cookies,
    ) as client:
        for hop in range(settings.MAX_REDIRECTS + 1):
            response = await client.get(current_url, headers=request_headers)

            if response.is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    raise ValueError("Redirect with no Location header")

                # Resolve relative redirects
                next_url = urljoin(current_url, location)
                redirect_chain.append(current_url)

                # SSRF check on each hop
                next_url = check_redirect_url(next_url)
                current_url = next_url

                if hop == settings.MAX_REDIRECTS:
                    raise ValueError(
                        f"Exceeded maximum redirects ({settings.MAX_REDIRECTS})"
                    )
                continue

            # Non-redirect response: read body with size limit
            body = await _read_body_with_limit(response)

            content_type = response.headers.get("content-type", "")

            return FetchResult(
                status_code=response.status_code,
                final_url=str(response.url),
                content_type=content_type,
                headers=dict(response.headers),
                body=body,
                redirect_chain=redirect_chain,
            )

    raise ValueError("Unexpected end of redirect loop")


async def _read_body_with_limit(response: httpx.Response) -> bytes:
    """Read response body, aborting if it exceeds MAX_RESPONSE_SIZE."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(chunk_size=65536):
        total += len(chunk)
        if total > settings.MAX_RESPONSE_SIZE:
            raise ValueError(
                f"Response body exceeds {settings.MAX_RESPONSE_SIZE} bytes limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)
