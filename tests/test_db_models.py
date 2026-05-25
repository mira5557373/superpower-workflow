from __future__ import annotations

import uuid

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import (
    Base,
    SwCoverageResult,
    SwEvent,
    SwGapReport,
    SwMilestone,
    SwPhase,
    SwProject,
    SwQualityGate,
    SwRun,
)


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    yield session
    session.close()


class TestEngineFactory:
    def test_creates_sqlite_engine(self):
        engine = create_engine_from_url("sqlite:///:memory:")
        assert engine is not None

    def test_creates_with_pool_config(self):
        engine = create_engine_from_url(
            "sqlite:///:memory:", pool_size=3, max_overflow=5, pool_timeout=10
        )
        assert engine is not None

    def test_session_factory_returns_session(self, db_engine):
        factory = get_session_factory(db_engine)
        session = factory()
        assert session is not None
        session.close()


class TestSwProjectModel:
    def test_create_project(self, db_session):
        p = SwProject(id=uuid.uuid4(), name="myapp", path="/home/user/myapp")
        db_session.add(p)
        db_session.commit()
        result = db_session.query(SwProject).first()
        assert result.name == "myapp"
        assert result.path == "/home/user/myapp"

    def test_project_name_unique(self, db_session):
        from sqlalchemy.exc import IntegrityError

        p1 = SwProject(id=uuid.uuid4(), name="app", path="/p/1")
        p2 = SwProject(id=uuid.uuid4(), name="app", path="/p/2")
        db_session.add(p1)
        db_session.commit()
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_project_timestamps_auto(self, db_session):
        p = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)
        assert p.created_at is not None


class TestSwRunModel:
    def test_create_run_with_project(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(
            id=uuid.uuid4(),
            project_id=proj.id,
            run_id="20260525-120000",
            status="running",
            model="opus",
        )
        db_session.add(run)
        db_session.commit()
        result = db_session.query(SwRun).first()
        assert result.run_id == "20260525-120000"
        assert result.project_id == proj.id

    def test_run_fields(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(
            id=uuid.uuid4(),
            project_id=proj.id,
            run_id="r1",
            status="complete",
            model="opus",
            total_cost_usd=12.50,
            milestone_count=5,
            completed_count=4,
            failed_count=1,
        )
        db_session.add(run)
        db_session.commit()
        r = db_session.query(SwRun).first()
        assert r.total_cost_usd == 12.50
        assert r.milestone_count == 5


class TestSwMilestoneModel:
    def test_create_milestone(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        db_session.add(run)
        db_session.commit()
        ms = SwMilestone(
            id=uuid.uuid4(), run_id=run.id, name="sp1-quality-gates", status="completed"
        )
        db_session.add(ms)
        db_session.commit()
        result = db_session.query(SwMilestone).first()
        assert result.name == "sp1-quality-gates"


class TestSwPhaseModel:
    def test_create_phase(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        phase = SwPhase(
            id=uuid.uuid4(),
            milestone_id=ms.id,
            phase_type="plan",
            status="completed",
            cost_usd=2.50,
            duration_ms=30000,
            model="opus",
            input_tokens=5000,
            output_tokens=2000,
        )
        db_session.add(phase)
        db_session.commit()
        result = db_session.query(SwPhase).first()
        assert result.phase_type == "plan"
        assert result.cost_usd == 2.50


class TestSwEventModel:
    def test_create_event(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        db_session.add_all([proj, run])
        db_session.commit()
        evt = SwEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            milestone_name="m1",
            event_type="phase_completed",
            data_json={"phase": "plan"},
        )
        db_session.add(evt)
        db_session.commit()
        result = db_session.query(SwEvent).first()
        assert result.event_type == "phase_completed"
        assert result.data_json["phase"] == "plan"


class TestAuxiliaryModels:
    def test_quality_gate(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        gate = SwQualityGate(
            id=uuid.uuid4(),
            milestone_id=ms.id,
            checkpoint="quality_check_b",
            gate_name="lint",
            passed=True,
        )
        db_session.add(gate)
        db_session.commit()
        assert db_session.query(SwQualityGate).first().passed is True

    def test_coverage_result(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        cov = SwCoverageResult(
            id=uuid.uuid4(),
            milestone_id=ms.id,
            coverage_pct=85.5,
            threshold=80.0,
            passed=True,
        )
        db_session.add(cov)
        db_session.commit()
        assert db_session.query(SwCoverageResult).first().coverage_pct == 85.5

    def test_gap_report(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(
            id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus"
        )
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        gap = SwGapReport(
            id=uuid.uuid4(),
            milestone_id=ms.id,
            pass_num=1,
            critical=0,
            architectural=1,
            important=2,
            minor=3,
            deferred=0,
            converged=True,
        )
        db_session.add(gap)
        db_session.commit()
        assert db_session.query(SwGapReport).first().converged is True


class TestAllTablesExist:
    def test_eight_tables(self, db_engine):
        from sqlalchemy import inspect

        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        expected = [
            "sw_projects",
            "sw_runs",
            "sw_milestones",
            "sw_phases",
            "sw_events",
            "sw_quality_gates",
            "sw_coverage_results",
            "sw_gap_reports",
        ]
        for t in expected:
            assert t in tables, f"Missing table: {t}"
