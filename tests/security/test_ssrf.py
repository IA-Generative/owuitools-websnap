"""SSRF protection tests."""

import pytest

from app.security import check_url_ssrf, validate_url


class TestSSRFRejection:
    """Test that SSRF-dangerous URLs are rejected."""

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "data:text/html,<h1>hi</h1>",
        "javascript:alert(1)",
    ])
    def test_reject_dangerous_schemes(self, url: str):
        with pytest.raises(ValueError, match="not allowed"):
            validate_url(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://[::1]/admin",
        "http://10.0.0.1/internal",
        "http://172.16.0.1/internal",
        "http://192.168.1.1/internal",
        "http://100.64.0.1/cgnat",
        "http://169.254.169.254/latest/meta-data/",
    ])
    def test_reject_private_ips(self, url: str):
        with pytest.raises(ValueError):
            check_url_ssrf(url)

    def test_reject_metadata_google(self):
        with pytest.raises(ValueError, match="blocked"):
            check_url_ssrf("http://metadata.google.internal/")

    def test_reject_credentials_in_url(self):
        with pytest.raises(ValueError, match="credentials"):
            validate_url("http://user:pass@example.com/page")

    @pytest.mark.parametrize("url", [
        "",
        "   ",
        "  \t\n  ",
    ])
    def test_reject_empty_whitespace(self, url: str):
        with pytest.raises(ValueError):
            validate_url(url)

    def test_reject_non_string(self):
        with pytest.raises(ValueError):
            validate_url(None)  # type: ignore

        with pytest.raises(ValueError):
            validate_url(123)  # type: ignore

    def test_reject_very_long_url(self):
        url = "http://example.com/" + "a" * 9000
        with pytest.raises(ValueError, match="maximum length"):
            validate_url(url)


class TestSSRFAcceptance:
    """Test that legitimate URLs are accepted."""

    def test_accept_example_com(self):
        result = validate_url("http://example.com/")
        assert "example.com" in result

    def test_accept_https(self):
        result = validate_url("https://fr.wikipedia.org/wiki/Test")
        assert "wikipedia.org" in result

    def test_strip_fragment(self):
        result = validate_url("https://example.com/page#section")
        assert "#" not in result

    def test_normalize_scheme(self):
        result = validate_url("HTTP://EXAMPLE.COM/path")
        assert result.startswith("http://")
