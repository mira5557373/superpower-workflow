from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

_connections: list[WebSocket] = []

POLL_INTERVAL_SECONDS = 2.0
MAX_EVENTS_PER_TICK = 50


@router.websocket("/ws/live")
async def websocket_live(
    ws: WebSocket,
    key: str = "",
    project_id: str = "",
    run_id: str = "",
):
    config = ws.app.state.config
    if config.api_key and key != config.api_key:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    _connections.append(ws)

    engine = ws.app.state.engine
    session_factory = None
    filter_run_uuid: uuid.UUID | None = None
    last_seen: datetime | None = None

    if engine is not None:
        from superpower_workflow.db.engine import get_session_factory
        from superpower_workflow.db.models import SwRun

        session_factory = get_session_factory(engine)
        last_seen = datetime.now(UTC)

        if run_id:
            tmp = session_factory()
            try:
                try:
                    filter_run_uuid = uuid.UUID(run_id)
                except ValueError:
                    run_obj = tmp.query(SwRun).filter(SwRun.run_id == run_id).first()
                    if run_obj is not None:
                        filter_run_uuid = run_obj.id
            finally:
                tmp.close()

    try:
        while True:
            if session_factory is not None and last_seen is not None:
                last_seen = await _push_new_events(ws, session_factory, last_seen, filter_run_uuid)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _connections:
            _connections.remove(ws)


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def _push_new_events(
    ws: WebSocket,
    session_factory,
    last_seen: datetime,
    filter_run_uuid: uuid.UUID | None,
) -> datetime:
    from superpower_workflow.db.models import SwEvent

    session = session_factory()
    try:
        # SQLite returns naive datetimes; strip tzinfo for the query filter.
        cutoff = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
        q = session.query(SwEvent).filter(SwEvent.timestamp > cutoff)
        if filter_run_uuid is not None:
            q = q.filter(SwEvent.run_id == filter_run_uuid)
        events = q.order_by(SwEvent.timestamp.asc()).limit(MAX_EVENTS_PER_TICK).all()
        if len(events) >= MAX_EVENTS_PER_TICK:
            logger.warning(
                "ws live-feed falling behind: tick at cap (%d events); "
                "backlog will drain over subsequent ticks. Consider raising "
                "MAX_EVENTS_PER_TICK or shortening POLL_INTERVAL_SECONDS.",
                MAX_EVENTS_PER_TICK,
            )
        for evt in events:
            payload = {
                "id": str(evt.id),
                "run_id": str(evt.run_id),
                "event_type": evt.event_type,
                "milestone_name": evt.milestone_name,
                "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                "data": evt.data_json,
            }
            await ws.send_json(payload)
            if evt.timestamp:
                ts_aware = _as_aware(evt.timestamp)
                if ts_aware > last_seen:
                    last_seen = ts_aware
        return last_seen
    finally:
        session.close()


async def broadcast_event(data: dict) -> None:
    for ws in list(_connections):
        try:
            await ws.send_json(data)
        except Exception:
            if ws in _connections:
                _connections.remove(ws)
