from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1", tags=["projects"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory

    return get_session_factory(engine)()


@router.get("/projects")
def list_projects(request: Request):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwProject

        projects = session.query(SwProject).all()
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "path": p.path,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in projects
        ]
    finally:
        session.close()


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import SwProject, SwRun

        proj = session.query(SwProject).filter(SwProject.id == uuid.UUID(project_id)).first()
        if proj is None:
            raise HTTPException(404, "Project not found")
        latest_run = (
            session.query(SwRun)
            .filter(SwRun.project_id == proj.id)
            .order_by(SwRun.started_at.desc())
            .first()
        )
        return {
            "id": str(proj.id),
            "name": proj.name,
            "path": proj.path,
            "created_at": proj.created_at.isoformat() if proj.created_at else None,
            "latest_run": {
                "id": str(latest_run.id),
                "run_id": latest_run.run_id,
                "status": latest_run.status,
                "model": latest_run.model,
            }
            if latest_run
            else None,
        }
    finally:
        session.close()


@router.post("/projects/sync")
def sync_project(request: Request, body: dict | None = None):
    body = body or {}
    path = body.get("path", "")
    if not path:
        raise HTTPException(400, "path required")
    return {"status": "accepted", "path": path}
