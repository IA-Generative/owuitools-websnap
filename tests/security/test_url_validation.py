"""URL validation edge case tests."""

import pytest

from app.security import validate_url


class TestURLValidation:
    """Test various malformed and edge-case URLs."""

    def test_missing_scheme_auto_prefixed(self):
        """Bare domain with a dot gets auto-prefixed with https://."""
        result = validate_url("example.com/page")
        assert result == "https://example.com/page"

    def test_missing_scheme_www_auto_prefixed(self):
        result = validate_url("www.lemonde.fr")
        assert result == "https://www.lemonde.fr/"

    def test_missing_scheme_no_dot_rejected(self):
        """A bare word without a dot is not a valid domain — still rejected."""
        with pytest.raises(ValueError):
            validate_url("notadomain")

    def test_double_slashes(self):
        # Should still be valid if scheme is present
        result = validate_url("http://example.com//path//to//page")
        assert "example.com" in result

    def test_fragment_stripped(self):
        result = validate_url("https://example.com/page#section")
        assert "#" not in result

    def test_very_long_url_rejected(self):
        url = "https://example.com/" + "x" * 8200
        with pytest.raises(ValueError, match="maximum length"):
            validate_url(url)

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_url("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError):
            validate_url("   ")

    def test_none_input(self):
        with pytest.raises(ValueError):
            validate_url(None)  # type: ignore

    @pytest.mark.parametrize("url", [
        "http://example.com/path?q=1&r=2",
        "https://sub.domain.example.com/page",
        "https://example.com:8080/path",
    ])
    def test_valid_urls_accepted(self, url: str):
        result = validate_url(url)
        assert result  # non-empty
