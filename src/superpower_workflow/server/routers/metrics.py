from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory

    return get_session_factory(engine)()


@router.get("/costs")
def cost_metrics(request: Request, project_id: str | None = None):
    session = _get_session(request)
    if session is None:
        return {"total_cost": 0.0, "cost_by_run": []}
    try:
        from superpower_workflow.db.models import SwRun

        q = session.query(SwRun)
        if project_id:
            q = q.filter(SwRun.project_id == uuid.UUID(project_id))
        runs = q.all()
        total = sum(r.total_cost_usd for r in runs)
        by_run = [{"run_id": r.run_id, "cost": r.total_cost_usd, "status": r.status} for r in runs]
        return {"total_cost": total, "cost_by_run": by_run}
    finally:
        session.close()


@router.get("/quality")
def quality_metrics(request: Request, project_id: str | None = None):
    session = _get_session(request)
    if session is None:
        return {"rework_rate": 0.0, "gap_reports": []}
    try:
        from superpower_workflow.db.models import SwGapReport, SwMilestone, SwRun

        q = session.query(SwGapReport)
        if project_id:
            q = q.join(SwMilestone).join(SwRun).filter(SwRun.project_id == uuid.UUID(project_id))
        gaps = q.all()
        return {
            "rework_rate": 0.0,
            "gap_reports": [
                {
                    "pass_num": g.pass_num,
                    "critical": g.critical,
                    "important": g.important,
                    "converged": g.converged,
                }
                for g in gaps
            ],
        }
    finally:
        session.close()


@router.get("/models")
def model_metrics(request: Request):
    session = _get_session(request)
    if session is None:
        return {"models": []}
    try:
        from sqlalchemy import func

        from superpower_workflow.db.models import SwRun

        rows = (
            session.query(
                SwRun.model,
                func.count(SwRun.id),
                func.sum(SwRun.total_cost_usd),
            )
            .group_by(SwRun.model)
            .all()
        )
        return {
            "models": [
                {"model": row[0], "run_count": row[1], "total_cost": float(row[2] or 0)}
                for row in rows
            ],
        }
    finally:
        session.close()
