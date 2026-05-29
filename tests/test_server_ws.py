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

    def test_ws_pushes_new_events(self, tmp_path):
        """Regression for soak bug #1: WS must push events that land after connection."""
        import queue as _q
        import threading
        import time

        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from superpower_workflow.db.engine import get_session_factory
        from superpower_workflow.db.models import Base
        from superpower_workflow.db.queries import (
            create_event,
            create_run,
            get_or_create_project,
        )
        from superpower_workflow.server.routers import ws as ws_module

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)

        s = get_session_factory(engine)()
        proj = get_or_create_project(s, "ws-test", "/p")
        run = create_run(s, project_id=proj.id, run_id="ws-r1", model="opus")
        s.close()

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = engine

        original_interval = ws_module.POLL_INTERVAL_SECONDS
        ws_module.POLL_INTERVAL_SECONDS = 0.05
        try:
            client = TestClient(app)
            with client.websocket_connect("/ws/live") as ws:
                # inject event in a background thread so the WS server has a chance to poll
                def _inject():
                    time.sleep(0.1)
                    s2 = get_session_factory(engine)()
                    create_event(
                        s2,
                        run_id=run.id,
                        event_type="soak_injection",
                        data_json={"injected": True, "tag": "abc123"},
                    )
                    s2.close()

                threading.Thread(target=_inject, daemon=True).start()

                # receive via thread to support timeout
                result: _q.Queue = _q.Queue()

                def _recv():
                    try:
                        result.put(ws.receive_json())
                    except Exception as e:
                        result.put(e)

                threading.Thread(target=_recv, daemon=True).start()
                payload = result.get(timeout=5.0)
                assert not isinstance(payload, Exception), f"recv failed: {payload!r}"
                assert payload["event_type"] == "soak_injection"
                assert payload["data"]["injected"] is True
                assert payload["data"]["tag"] == "abc123"
        finally:
            ws_module.POLL_INTERVAL_SECONDS = original_interval
