from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from superpower_workflow.db.models import (
    SwCoverageResult,
    SwEvent,
    SwGapReport,
    SwMilestone,
    SwPhase,
    SwProject,
    SwQualityGate,
    SwRun,
)


def get_or_create_project(session: Session, name: str, path: str) -> SwProject:
    proj = session.query(SwProject).filter(SwProject.name == name).first()
    if proj is not None:
        proj.path = path
        proj.updated_at = datetime.now(UTC)
        session.commit()
        return proj
    proj = SwProject(id=uuid.uuid4(), name=name, path=path)
    session.add(proj)
    session.commit()
    return proj


def get_project_by_name(session: Session, name: str) -> SwProject | None:
    return session.query(SwProject).filter(SwProject.name == name).first()


def create_run(
    session: Session,
    project_id: uuid.UUID,
    run_id: str,
    model: str,
    milestone_count: int = 0,
    spec_sha: str | None = None,
) -> SwRun:
    run = SwRun(
        id=uuid.uuid4(),
        project_id=project_id,
        run_id=run_id,
        model=model,
        milestone_count=milestone_count,
        spec_sha=spec_sha,
        status="running",
    )
    session.add(run)
    session.commit()
    return run


def get_run_by_run_id(session: Session, project_id: uuid.UUID, run_id: str) -> SwRun | None:
    return (
        session.query(SwRun)
        .filter(
            SwRun.project_id == project_id,
            SwRun.run_id == run_id,
        )
        .first()
    )


def list_runs(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SwRun]:
    q = session.query(SwRun)
    if project_id is not None:
        q = q.filter(SwRun.project_id == project_id)
    if status is not None:
        q = q.filter(SwRun.status == status)
    return q.order_by(SwRun.started_at.desc()).offset(offset).limit(limit).all()


def update_run_status(
    session: Session,
    run_uuid: uuid.UUID,
    status: str,
    total_cost_usd: float = 0.0,
    completed_count: int = 0,
    failed_count: int = 0,
    skipped_count: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    run = session.query(SwRun).filter(SwRun.id == run_uuid).first()
    if run is None:
        return
    run.status = status
    run.total_cost_usd = total_cost_usd
    run.completed_count = completed_count
    run.failed_count = failed_count
    run.skipped_count = skipped_count
    run.duration_seconds = duration_seconds
    run.completed_at = datetime.now(UTC)
    session.commit()


def create_milestone(
    session: Session,
    run_id: uuid.UUID,
    name: str,
    status: str = "pending",
) -> SwMilestone:
    ms = SwMilestone(id=uuid.uuid4(), run_id=run_id, name=name, status=status)
    session.add(ms)
    session.commit()
    return ms


def get_milestone_by_name(session: Session, run_id: uuid.UUID, name: str) -> SwMilestone | None:
    return (
        session.query(SwMilestone)
        .filter(
            SwMilestone.run_id == run_id,
            SwMilestone.name == name,
        )
        .first()
    )


def update_milestone_status(
    session: Session,
    milestone_id: uuid.UUID,
    status: str,
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
) -> None:
    ms = session.query(SwMilestone).filter(SwMilestone.id == milestone_id).first()
    if ms is None:
        return
    ms.status = status
    ms.cost_usd = cost_usd
    ms.duration_seconds = duration_seconds
    if status in ("completed", "failed"):
        ms.completed_at = datetime.now(UTC)
    session.commit()


def create_event(
    session: Session,
    run_id: uuid.UUID,
    event_type: str,
    data_json: dict,
    milestone_name: str | None = None,
) -> SwEvent:
    evt = SwEvent(
        id=uuid.uuid4(),
        run_id=run_id,
        milestone_name=milestone_name,
        event_type=event_type,
        data_json=data_json,
    )
    session.add(evt)
    session.commit()
    return evt


def list_events(
    session: Session,
    run_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SwEvent]:
    q = session.query(SwEvent)
    if run_id is not None:
        q = q.filter(SwEvent.run_id == run_id)
    if event_type is not None:
        q = q.filter(SwEvent.event_type == event_type)
    return q.order_by(SwEvent.timestamp.desc()).offset(offset).limit(limit).all()


def create_phase(
    session: Session,
    milestone_id: uuid.UUID,
    phase_type: str,
    model: str | None = None,
    status: str = "pending",
) -> SwPhase:
    phase = SwPhase(
        id=uuid.uuid4(),
        milestone_id=milestone_id,
        phase_type=phase_type,
        model=model,
        status=status,
    )
    session.add(phase)
    session.commit()
    return phase


def create_quality_gate(
    session: Session,
    milestone_id: uuid.UUID,
    checkpoint: str,
    gate_name: str,
    passed: bool,
    detail: str | None = None,
) -> SwQualityGate:
    gate = SwQualityGate(
        id=uuid.uuid4(),
        milestone_id=milestone_id,
        checkpoint=checkpoint,
        gate_name=gate_name,
        passed=passed,
        detail=detail,
    )
    session.add(gate)
    session.commit()
    return gate


def create_coverage_result(
    session: Session,
    milestone_id: uuid.UUID,
    coverage_pct: float,
    threshold: float,
    passed: bool,
) -> SwCoverageResult:
    cov = SwCoverageResult(
        id=uuid.uuid4(),
        milestone_id=milestone_id,
        coverage_pct=coverage_pct,
        threshold=threshold,
        passed=passed,
    )
    session.add(cov)
    session.commit()
    return cov


def create_gap_report(
    session: Session,
    milestone_id: uuid.UUID,
    pass_num: int,
    critical: int = 0,
    architectural: int = 0,
    important: int = 0,
    minor: int = 0,
    deferred: int = 0,
    converged: bool = False,
) -> SwGapReport:
    gap = SwGapReport(
        id=uuid.uuid4(),
        milestone_id=milestone_id,
        pass_num=pass_num,
        critical=critical,
        architectural=architectural,
        important=important,
        minor=minor,
        deferred=deferred,
        converged=converged,
    )
    session.add(gap)
    session.commit()
    return gap
