"""Functional tests for the FastAPI API endpoints."""

import pytest


class TestHealthEndpoint:
    """Test /healthz endpoint."""

    def test_healthz_returns_200(self, test_client):
        response = test_client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "unhealthy")
        assert "features" in data

    def test_healthz_has_features(self, test_client):
        response = test_client.get("/healthz")
        data = response.json()
        assert isinstance(data["features"], list)
        assert "extraction" in data["features"]


class TestExtractEndpoint:
    """Test /extract endpoint."""

    def test_extract_ssrf_rejected(self, test_client):
        response = test_client.post(
            "/extract",
            json={"url": "http://127.0.0.1/admin"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert len(data["errors"]) > 0
        assert data["errors"][0]["stage"] == "fetch"

    def test_extract_invalid_url(self, test_client):
        response = test_client.post(
            "/extract",
            json={"url": "not-a-url"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert len(data["errors"]) > 0

    def test_extract_empty_url(self, test_client):
        response = test_client.post(
            "/extract",
            json={"url": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False

    def test_request_id_header(self, test_client):
        response = test_client.get("/healthz")
        assert "x-request-id" in response.headers
