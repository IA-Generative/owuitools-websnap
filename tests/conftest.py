"""Shared test fixtures — synthetic HTTP server and PDF fixtures."""

from __future__ import annotations

import pytest
import httpx
from fastapi.testclient import TestClient
from pytest_httpserver import HTTPServer

from app.main import app


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests against real URLs",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="need --run-integration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def test_client():
    """Synchronous FastAPI test client."""
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def async_client():
    """Async httpx client for FastAPI."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---- Synthetic HTML pages ----

NORMAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Test Page Title</title></head>
<body>
<h1>Main Heading</h1>
<p>This is a normal test page with enough content to pass the extraction threshold.
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt
ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation.</p>
<img src="/images/photo.jpg" alt="Test photo" width="400" height="300">
<img src="/images/logo.png" alt="Logo" width="200" height="150">
<a href="/page1">Link 1</a>
<a href="/page2">Link 2</a>
<a href="https://example.com/external">External Link</a>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Login - Sign In</title></head>
<body>
<h1>Sign In</h1>
<form action="/login" method="post" class="login-form" id="auth-form">
<input type="text" name="username" placeholder="Username">
<input type="password" name="password" placeholder="Password">
<button type="submit">Log In</button>
</form>
</body>
</html>"""

EMPTY_HTML = """<!DOCTYPE html>
<html><head><title>Empty</title></head>
<body></body>
</html>"""

JS_HEAVY_HTML = """<!DOCTYPE html>
<html><head><title>SPA App</title></head>
<body>
<div id="root"></div>
<noscript>You need to enable JavaScript to run this app.</noscript>
<script src="/bundle.js"></script>
</body>
</html>"""

NON_UTF8_CONTENT = "Contenu en français avec des accents: é, è, ê, ë, à, ç, ù".encode("iso-8859-1")


@pytest.fixture(scope="session")
def synthetic_server(httpserver: HTTPServer):
    """Set up all synthetic endpoints on the test HTTP server."""
    # Normal HTML page
    httpserver.expect_request("/normal").respond_with_data(
        NORMAL_HTML, content_type="text/html; charset=utf-8"
    )

    # Login page
    httpserver.expect_request("/login-page").respond_with_data(
        LOGIN_HTML, content_type="text/html; charset=utf-8"
    )

    # 401 response
    httpserver.expect_request("/protected").respond_with_data(
        "<html><body>Unauthorized</body></html>",
        status=401,
        content_type="text/html",
    )

    # 403 with redirect to /login
    httpserver.expect_request("/forbidden").respond_with_data(
        "", status=403, headers={"Location": "/login-page"},
        content_type="text/html",
    )

    # Empty body
    httpserver.expect_request("/empty").respond_with_data(
        EMPTY_HTML, content_type="text/html; charset=utf-8"
    )

    # JS-heavy page
    httpserver.expect_request("/spa").respond_with_data(
        JS_HEAVY_HTML, content_type="text/html; charset=utf-8"
    )

    # Non-UTF-8 encoding
    httpserver.expect_request("/iso-8859").respond_with_data(
        NON_UTF8_CONTENT,
        content_type="text/html; charset=iso-8859-1",
    )

    # 429 rate limited
    httpserver.expect_request("/rate-limited").respond_with_data(
        "<html><body>Too Many Requests</body></html>",
        status=429,
        content_type="text/html",
    )

    # Test PDF (generated inline with pymupdf)
    pdf_bytes = _generate_test_pdf()
    httpserver.expect_request("/test.pdf").respond_with_data(
        pdf_bytes, content_type="application/pdf"
    )

    return httpserver


def _generate_test_pdf() -> bytes:
    """Generate a small 2-page test PDF with known text."""
    import fitz

    doc = fitz.open()

    # Page 1
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 72), "Test PDF Page 1", fontsize=16)
    page1.insert_text((72, 120), "This is the content of the first page of the test PDF.")

    # Page 2
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 72), "Test PDF Page 2", fontsize=16)
    page2.insert_text((72, 120), "This is the content of the second page of the test PDF.")

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
