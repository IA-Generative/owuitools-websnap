"""Response size and timeout limit tests."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.config import settings


class TestResponseLimits:
    """Test response size enforcement."""

    def test_max_response_size_configured(self):
        assert settings.MAX_RESPONSE_SIZE == 52_428_800  # 50MB

    def test_connect_timeout_configured(self):
        assert settings.HTTP_CONNECT_TIMEOUT == 10

    def test_read_timeout_configured(self):
        assert settings.HTTP_READ_TIMEOUT == 30

    def test_max_redirects_configured(self):
        assert settings.MAX_REDIRECTS == 5
