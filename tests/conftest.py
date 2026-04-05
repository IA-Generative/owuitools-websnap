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

COOKIE_BANNER_HTML = """<!DOCTYPE html>
<html lang="fr">
<head><title>Page avec bandeau cookies</title>
<meta name="description" content="Page de test avec cookie consent">
</head>
<body>
<h1>Contenu principal</h1>
<p>Ceci est le contenu reel de la page, visible une fois le bandeau ferme.</p>
<p>Deuxieme paragraphe avec des informations utiles pour le test.</p>

<!-- TarteAuCitron-style cookie banner -->
<div id="tarteaucitronRoot" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:10000;background:rgba(0,0,0,0.5)">
  <div id="tarteaucitronAlertBig">
    <span>Ce site utilise des cookies</span>
    <button id="tarteaucitronPersonalize2">Tout refuser</button>
    <button id="tarteaucitronAllDenied2">Tout accepter</button>
  </div>
</div>
</body>
</html>"""

DIDOMI_BANNER_HTML = """<!DOCTYPE html>
<html lang="fr">
<head><title>Page avec Didomi</title></head>
<body>
<h1>Article principal</h1>
<p>Texte de l'article qui devrait etre visible apres fermeture du bandeau.</p>

<!-- Didomi-style consent -->
<div id="didomi-popup" role="dialog" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:99999;background:rgba(0,0,0,0.7)">
  <button class="didomi-components-button--first">Accepter et fermer</button>
  <button id="didomi-notice-disagree-button">Refuser</button>
</div>

<style>body { overflow: hidden; }</style>
</body>
</html>"""

GENERIC_POPUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Page with generic popup</title></head>
<body>
<h1>Main content</h1>
<p>This is the real page content below the overlay.</p>

<!-- Generic overlay with text-based button -->
<div id="cookie-overlay" style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:50000;background:rgba(0,0,0,0.8)">
  <div role="dialog">
    <p>We use cookies to improve your experience</p>
    <button aria-label="Accept cookies">Accept all</button>
  </div>
</div>

<style>body.no-scroll { overflow: hidden; } </style>
<script>document.body.classList.add('no-scroll');</script>
</body>
</html>"""


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

    # Cookie banner pages
    httpserver.expect_request("/cookie-tarteaucitron").respond_with_data(
        COOKIE_BANNER_HTML, content_type="text/html; charset=utf-8"
    )
    httpserver.expect_request("/cookie-didomi").respond_with_data(
        DIDOMI_BANNER_HTML, content_type="text/html; charset=utf-8"
    )
    httpserver.expect_request("/cookie-generic").respond_with_data(
        GENERIC_POPUP_HTML, content_type="text/html; charset=utf-8"
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
