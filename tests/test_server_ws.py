from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

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


class TestWebSocket:
    def test_ws_connect_no_auth(self, app):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        with client.websocket_connect("/ws/live") as ws:
            ws.close()

    def test_ws_rejects_wrong_key(self, authed_app):
        from fastapi.testclient import TestClient

        client = TestClient(authed_app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/live?key=wrong"):
            pass

    def test_ws_accepts_correct_key(self, authed_app):
        from fastapi.testclient import TestClient

        client = TestClient(authed_app)
        with client.websocket_connect("/ws/live?key=test-key") as ws:
            ws.close()
