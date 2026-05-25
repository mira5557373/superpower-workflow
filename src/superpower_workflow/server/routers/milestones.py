from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1", tags=["milestones"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory

    return get_session_factory(engine)()


@router.get("/milestones")
def list_milestones(
    request: Request,
    run_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwMilestone

        q = session.query(SwMilestone)
        if run_id:
            q = q.filter(SwMilestone.run_id == uuid.UUID(run_id))
        milestones = q.offset(offset).limit(limit).all()
        return [
            {
                "id": str(m.id),
                "name": m.name,
                "status": m.status,
                "cost_usd": m.cost_usd,
                "duration_seconds": m.duration_seconds,
            }
            for m in milestones
        ]
    finally:
        session.close()


@router.get("/milestones/{milestone_id}")
def get_milestone(milestone_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import (
            SwGapReport,
            SwMilestone,
            SwPhase,
            SwQualityGate,
        )

        ms = session.query(SwMilestone).filter(SwMilestone.id == uuid.UUID(milestone_id)).first()
        if ms is None:
            raise HTTPException(404, "Milestone not found")
        phases = session.query(SwPhase).filter(SwPhase.milestone_id == ms.id).all()
        gates = session.query(SwQualityGate).filter(SwQualityGate.milestone_id == ms.id).all()
        gaps = session.query(SwGapReport).filter(SwGapReport.milestone_id == ms.id).all()
        return {
            "id": str(ms.id),
            "name": ms.name,
            "status": ms.status,
            "cost_usd": ms.cost_usd,
            "duration_seconds": ms.duration_seconds,
            "phases": [
                {
                    "id": str(p.id),
                    "phase_type": p.phase_type,
                    "status": p.status,
                    "cost_usd": p.cost_usd,
                    "model": p.model,
                }
                for p in phases
            ],
            "quality_gates": [
                {"gate_name": g.gate_name, "passed": g.passed, "checkpoint": g.checkpoint}
                for g in gates
            ],
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
