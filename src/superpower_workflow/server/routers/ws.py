from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])

_connections: list[WebSocket] = []


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket, key: str = "", project_id: str = ""):
    config = ws.app.state.config
    if config.api_key and key != config.api_key:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    _connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _connections:
            _connections.remove(ws)


async def broadcast_event(data: dict) -> None:
    for ws in list(_connections):
        try:
            await ws.send_json(data)
        except Exception:
            if ws in _connections:
                _connections.remove(ws)
