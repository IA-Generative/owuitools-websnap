"""Redirect chain security tests."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.security import check_redirect_url


class TestRedirectSecurity:
    """Test redirect validation."""

    def test_reject_redirect_to_localhost(self):
        with pytest.raises(ValueError):
            check_redirect_url("http://127.0.0.1/admin")

    def test_reject_redirect_to_metadata(self):
        with pytest.raises(ValueError):
            check_redirect_url("http://169.254.169.254/latest/meta-data/")

    def test_accept_redirect_to_valid_host(self):
        result = check_redirect_url("https://example.com/redirected")
        assert "example.com" in result

    def test_reject_redirect_to_private_range(self):
        with pytest.raises(ValueError):
            check_redirect_url("http://10.0.0.1/internal")

    def test_reject_redirect_scheme_change(self):
        with pytest.raises(ValueError, match="not allowed"):
            check_redirect_url("file:///etc/passwd")
