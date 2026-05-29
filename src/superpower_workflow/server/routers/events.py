from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/v1", tags=["events"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory

    return get_session_factory(engine)()


@router.get("/events")
def list_events(
    request: Request,
    run_id: str | None = None,
    event_type: str | None = Query(default=None, alias="event_type"),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwRun
        from superpower_workflow.db.queries import list_events as db_list_events

        rid: uuid.UUID | None = None
        if run_id:
            try:
                rid = uuid.UUID(run_id)
            except ValueError:
                run_obj = session.query(SwRun).filter(SwRun.run_id == run_id).first()
                if run_obj is None:
                    return []
                rid = run_obj.id
        events = db_list_events(
            session, run_id=rid, event_type=event_type, limit=limit, offset=offset
        )
        return [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "milestone_name": e.milestone_name,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "data": e.data_json,
            }
            for e in events
        ]
    finally:
        session.close()
