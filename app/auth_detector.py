"""Heuristic detection of login/authentication walls."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from app.models import AuthDetectionResult, FetchResult

logger = logging.getLogger(__name__)

_AUTH_URL_PATTERNS = re.compile(
    r"/(login|log-in|signin|sign-in|auth|authentication|connexion|sso|oidc|oauth)",
    re.IGNORECASE,
)

_AUTH_FORM_PATTERNS = re.compile(
    r"(login|log-in|signin|sign-in|auth|authentication|connexion|sso|oidc|oauth)",
    re.IGNORECASE,
)

_AUTH_TITLE_PATTERNS = re.compile(
    r"(login|sign\s*in|connexion|authentification)",
    re.IGNORECASE,
)


def detect_auth_wall(fetch_result: FetchResult, html: str) -> AuthDetectionResult:
    """Detect whether the page is behind an authentication wall."""
    signals: list[str] = []
    score = 0

    # HTTP 401 or 403 — strong signal (weight 3)
    if fetch_result.status_code == 401:
        signals.append("HTTP 401")
        score += 3
    elif fetch_result.status_code == 403:
        signals.append("HTTP 403")
        score += 3

    soup = BeautifulSoup(html, "lxml")

    # Password field — strong signal (weight 3)
    if soup.find("input", {"type": "password"}):
        signals.append("password field")
        score += 3

    # Form action or CSS class matching auth patterns (weight 2 each, max 2)
    auth_form_score = 0
    for form in soup.find_all("form"):
        action = form.get("action", "")
        css_class = " ".join(form.get("class", []))
        form_id = form.get("id", "")
        combined = f"{action} {css_class} {form_id}"
        if _AUTH_FORM_PATTERNS.search(combined):
            if auth_form_score < 2:
                signals.append(f"auth form pattern: {combined[:80]}")
                score += 2
                auth_form_score += 1

    # Redirect chain contains auth URLs (weight 2)
    for redirect_url in fetch_result.redirect_chain:
        if _AUTH_URL_PATTERNS.search(redirect_url):
            signals.append(f"redirect to auth URL: {redirect_url[:120]}")
            score += 2
            break

    # Low content density (weight 1)
    body = soup.find("body")
    if body:
        visible_text = body.get_text(strip=True)
        if len(visible_text) < 500:
            signals.append(f"low content density ({len(visible_text)} chars)")
            score += 1

    # Page title contains auth keywords (weight 1)
    title_tag = soup.find("title")
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        if _AUTH_TITLE_PATTERNS.search(title_text):
            signals.append(f"auth keyword in title: {title_text[:80]}")
            score += 1

    is_auth_wall = score >= 3

    if is_auth_wall:
        logger.info("Auth wall detected (score=%d): %s", score, signals)

    return AuthDetectionResult(
        is_auth_wall=is_auth_wall,
        signals=signals,
        score=score,
    )
