from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory

    return get_session_factory(engine)()


@router.get("/runs")
def list_runs(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.queries import list_runs as db_list_runs

        pid = uuid.UUID(project_id) if project_id else None
        runs = db_list_runs(session, project_id=pid, status=status, limit=limit, offset=offset)
        return [
            {
                "id": str(r.id),
                "run_id": r.run_id,
                "status": r.status,
                "model": r.model,
                "total_cost_usd": r.total_cost_usd,
                "milestone_count": r.milestone_count,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in runs
        ]
    finally:
        session.close()


def _resolve_run_ids(session, raw_ids: list[str]) -> list[uuid.UUID]:
    from superpower_workflow.db.models import SwRun

    resolved: list[uuid.UUID] = []
    for raw in raw_ids:
        raw = raw.strip()
        if not raw:
            continue
        try:
            resolved.append(uuid.UUID(raw))
            continue
        except ValueError:
            run = session.query(SwRun).filter(SwRun.run_id == raw).first()
            if run is not None:
                resolved.append(run.id)
    return resolved


@router.get("/runs/compare")
def compare_runs(request: Request, ids: str = Query(...)):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwRun

        raw_ids = [i for i in ids.split(",") if i.strip()]
        run_ids = _resolve_run_ids(session, raw_ids)
        if not run_ids:
            return []
        runs = session.query(SwRun).filter(SwRun.id.in_(run_ids)).all()
        return [
            {
                "id": str(r.id),
                "run_id": r.run_id,
                "status": r.status,
                "total_cost_usd": r.total_cost_usd,
                "milestone_count": r.milestone_count,
                "completed_count": r.completed_count,
                "failed_count": r.failed_count,
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ]
    finally:
        session.close()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import SwMilestone, SwRun

        try:
            run = session.query(SwRun).filter(SwRun.id == uuid.UUID(run_id)).first()
        except ValueError:
            run = session.query(SwRun).filter(SwRun.run_id == run_id).first()
        if run is None:
            raise HTTPException(404, "Run not found")
        milestones = (
            session.query(SwMilestone)
            .filter(SwMilestone.run_id == run.id)
            .order_by(SwMilestone.started_at.asc())
            .all()
        )
        return {
            "id": str(run.id),
            "run_id": run.run_id,
            "status": run.status,
            "model": run.model,
            "total_cost_usd": run.total_cost_usd,
            "milestone_count": run.milestone_count,
            "milestones": [
                {
                    "id": str(m.id),
                    "name": m.name,
                    "status": m.status,
                    "cost_usd": m.cost_usd,
                    "duration_seconds": m.duration_seconds,
                }
                for m in milestones
            ],
        }
    finally:
        session.close()
