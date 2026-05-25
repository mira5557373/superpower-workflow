from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SwProject(Base):
    __tablename__ = "sw_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    runs: Mapped[list[SwRun]] = relationship("SwRun", back_populates="project")


class SwRun(Base):
    __tablename__ = "sw_runs"
    __table_args__ = (Index("ix_sw_runs_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_projects.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    model: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    spec_sha: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    milestone_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[SwProject] = relationship("SwProject", back_populates="runs")
    milestones: Mapped[list[SwMilestone]] = relationship("SwMilestone", back_populates="run")
    events: Mapped[list[SwEvent]] = relationship("SwEvent", back_populates="run")


class SwMilestone(Base):
    __tablename__ = "sw_milestones"
    __table_args__ = (Index("ix_sw_milestones_run_name", "run_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    tests_added: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[SwRun] = relationship("SwRun", back_populates="milestones")
    phases: Mapped[list[SwPhase]] = relationship("SwPhase", back_populates="milestone")
    quality_gates: Mapped[list[SwQualityGate]] = relationship(
        "SwQualityGate",
        back_populates="milestone",
    )
    coverage_results: Mapped[list[SwCoverageResult]] = relationship(
        "SwCoverageResult",
        back_populates="milestone",
    )
    gap_reports: Mapped[list[SwGapReport]] = relationship(
        "SwGapReport",
        back_populates="milestone",
    )


class SwPhase(Base):
    __tablename__ = "sw_phases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    phase_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    session_id: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="phases")


class SwEvent(Base):
    __tablename__ = "sw_events"
    __table_args__ = (Index("ix_sw_events_run_type", "run_id", "event_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_runs.id"), nullable=False)
    milestone_name: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[SwRun] = relationship("SwRun", back_populates="events")


class SwQualityGate(Base):
    __tablename__ = "sw_quality_gates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(50), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(50), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="quality_gates")


class SwCoverageResult(Base):
    __tablename__ = "sw_coverage_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="coverage_results")


class SwGapReport(Base):
    __tablename__ = "sw_gap_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    pass_num: Mapped[int] = mapped_column(Integer, nullable=False)
    critical: Mapped[int] = mapped_column(Integer, default=0)
    architectural: Mapped[int] = mapped_column(Integer, default=0)
    important: Mapped[int] = mapped_column(Integer, default=0)
    minor: Mapped[int] = mapped_column(Integer, default=0)
    deferred: Mapped[int] = mapped_column(Integer, default=0)
    converged: Mapped[bool] = mapped_column(Boolean, default=False)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="gap_reports")
