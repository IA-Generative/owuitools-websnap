"""Central configuration via Pydantic Settings."""

from __future__ import annotations

import logging
import sys

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # LLM credentials
    SCW_SECRET_KEY_LLM: str = ""
    SCW_LLM_BASE_URL: str = "https://api.scaleway.ai/v1"
    SCW_LLM_MODEL: str = "gpt-oss-120b"
    SCW_LLM_VISION_MODEL: str = "mistral/pixtral-12b-2409"

    # Feature flags
    FEATURES_ENABLED: str = "extraction"

    # HTTP tuning
    HTTP_CONNECT_TIMEOUT: int = 10
    HTTP_READ_TIMEOUT: int = 30
    MAX_RESPONSE_SIZE: int = 52_428_800  # 50 MB
    MAX_REDIRECTS: int = 5

    # Concurrency
    MAX_BROWSER_SESSIONS: int = 3
    MAX_CONCURRENT_IMAGE_ANALYSES: int = 5

    # Cache
    CACHE_MAX_ENTRIES: int = 100
    CACHE_TTL_SECONDS: int = 300

    # CORS
    CORS_ORIGINS: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def enabled_features(self) -> set[str]:
        return {f.strip() for f in self.FEATURES_ENABLED.split(",") if f.strip()}

    def validate_features(self) -> list[str]:
        """Return list of missing variables required by enabled features."""
        missing: list[str] = []
        features = self.enabled_features
        if "vision" in features:
            if not self.SCW_SECRET_KEY_LLM:
                missing.append("SCW_SECRET_KEY_LLM (required by vision)")
            if not self.SCW_LLM_VISION_MODEL:
                missing.append("SCW_LLM_VISION_MODEL (required by vision)")
        if "enrichment" in features:
            if not self.SCW_SECRET_KEY_LLM:
                missing.append("SCW_SECRET_KEY_LLM (required by enrichment)")
            if not self.SCW_LLM_MODEL:
                missing.append("SCW_LLM_MODEL (required by enrichment)")
        return missing


settings = Settings()
