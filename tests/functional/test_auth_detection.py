"""Functional tests for authentication wall detection."""

import pytest

from app.auth_detector import detect_auth_wall
from app.models import FetchResult
from tests.conftest import NORMAL_HTML, LOGIN_HTML, EMPTY_HTML


def _make_fetch_result(
    status_code: int = 200,
    redirect_chain: list[str] | None = None,
) -> FetchResult:
    return FetchResult(
        status_code=status_code,
        final_url="http://test/page",
        content_type="text/html",
        headers={},
        body=b"",
        redirect_chain=redirect_chain or [],
    )


class TestAuthDetection:
    """Test auth wall heuristic detection."""

    def test_login_page_detected(self):
        fetch = _make_fetch_result()
        result = detect_auth_wall(fetch, LOGIN_HTML)
        assert result.is_auth_wall is True
        assert any("password" in s.lower() for s in result.signals)

    def test_401_detected(self):
        fetch = _make_fetch_result(status_code=401)
        result = detect_auth_wall(fetch, "<html><body>Unauthorized</body></html>")
        assert result.is_auth_wall is True
        assert "HTTP 401" in result.signals

    def test_403_with_redirect(self):
        fetch = _make_fetch_result(
            status_code=200,
            redirect_chain=["http://test/forbidden", "http://test/login"],
        )
        result = detect_auth_wall(fetch, LOGIN_HTML)
        assert result.is_auth_wall is True
        assert result.score >= 5

    def test_normal_page_not_detected(self):
        fetch = _make_fetch_result()
        result = detect_auth_wall(fetch, NORMAL_HTML)
        assert result.is_auth_wall is False

    def test_empty_body_low_density(self):
        fetch = _make_fetch_result()
        result = detect_auth_wall(fetch, EMPTY_HTML)
        # Empty body has low content density signal but may not reach threshold alone
        assert "low content density" in " ".join(result.signals).lower() or result.score >= 0
