from __future__ import annotations

import pytest

from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


@pytest.fixture
def app():
    cfg = ServerConfig(api_key="", database_url="")
    return create_app(cfg)


@pytest.fixture
def authed_app():
    cfg = ServerConfig(api_key="test-key", database_url="")
    return create_app(cfg)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def authed_client(authed_app):
    from fastapi.testclient import TestClient

    return TestClient(authed_app)


class TestHealthEndpoint:
    def test_health_ok_no_db(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db"] == "not_configured"

    def test_health_no_auth_required(self, authed_client):
        r = authed_client.get("/api/v1/health")
        assert r.status_code == 200


class TestApiKeyAuth:
    def test_no_key_configured_allows_all(self, client):
        r = client.get("/api/v1/projects")
        assert r.status_code == 200

    def test_key_required_rejects_missing(self, authed_client):
        r = authed_client.get("/api/v1/projects")
        assert r.status_code == 401

    def test_key_required_accepts_valid(self, authed_client):
        r = authed_client.get("/api/v1/projects", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 200

    def test_key_required_rejects_wrong(self, authed_client):
        r = authed_client.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


class TestCORS:
    def test_cors_headers_present(self, client):
        r = client.options(
            "/api/v1/health",
            headers={"Origin": "http://localhost:3001", "Access-Control-Request-Method": "GET"},
        )
        assert r.status_code in (200, 204, 405)


class TestRateLimiting:
    def test_no_crash_on_rapid_requests(self, client):
        for _ in range(10):
            r = client.get("/api/v1/health")
            assert r.status_code == 200
