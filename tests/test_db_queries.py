from __future__ import annotations

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base
from superpower_workflow.db.queries import (
    create_coverage_result,
    create_event,
    create_gap_report,
    create_milestone,
    create_phase,
    create_quality_gate,
    create_run,
    get_milestone_by_name,
    get_or_create_project,
    get_project_by_name,
    get_run_by_run_id,
    list_events,
    list_runs,
    update_milestone_status,
    update_run_status,
)


@pytest.fixture
def db_session():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    yield session
    session.close()


class TestProjectQueries:
    def test_get_or_create_new(self, db_session):
        proj = get_or_create_project(db_session, "myapp", "/p/myapp")
        assert proj.name == "myapp"
        assert proj.id is not None

    def test_get_or_create_existing(self, db_session):
        p1 = get_or_create_project(db_session, "app", "/p/1")
        p2 = get_or_create_project(db_session, "app", "/p/2")
        assert p1.id == p2.id
        assert p2.path == "/p/2"

    def test_get_by_name(self, db_session):
        get_or_create_project(db_session, "app", "/p")
        result = get_project_by_name(db_session, "app")
        assert result is not None
        assert result.name == "app"

    def test_get_by_name_missing(self, db_session):
        assert get_project_by_name(db_session, "nope") is None


class TestRunQueries:
    def test_create_run(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(
            db_session,
            project_id=proj.id,
            run_id="20260525-120000",
            model="opus",
            milestone_count=5,
        )
        assert run.run_id == "20260525-120000"
        assert run.status == "running"

    def test_get_run_by_run_id(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        result = get_run_by_run_id(db_session, proj.id, "r1")
        assert result is not None
        assert result.run_id == "r1"

    def test_list_runs_paginated(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        for i in range(5):
            create_run(db_session, project_id=proj.id, run_id=f"r{i}", model="opus")
        page = list_runs(db_session, project_id=proj.id, limit=2, offset=0)
        assert len(page) == 2

    def test_update_run_status(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        update_run_status(
            db_session,
            run.id,
            status="complete",
            total_cost_usd=10.0,
            completed_count=3,
            failed_count=1,
        )
        db_session.refresh(run)
        assert run.status == "complete"
        assert run.total_cost_usd == 10.0


class TestMilestoneQueries:
    def test_create_milestone(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="sp1-quality-gates")
        assert ms.name == "sp1-quality-gates"

    def test_get_milestone_by_name(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        create_milestone(db_session, run_id=run.id, name="m1")
        result = get_milestone_by_name(db_session, run.id, "m1")
        assert result is not None

    def test_update_milestone_status(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        update_milestone_status(db_session, ms.id, status="completed", cost_usd=5.0)
        db_session.refresh(ms)
        assert ms.status == "completed"
        assert ms.cost_usd == 5.0


class TestEventQueries:
    def test_create_event(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        evt = create_event(
            db_session,
            run_id=run.id,
            milestone_name="m1",
            event_type="phase_completed",
            data_json={"phase": "plan"},
        )
        assert evt.event_type == "phase_completed"

    def test_list_events_filtered(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        create_event(db_session, run_id=run.id, event_type="phase_started", data_json={})
        create_event(db_session, run_id=run.id, event_type="phase_completed", data_json={})
        create_event(db_session, run_id=run.id, event_type="phase_started", data_json={})
        results = list_events(db_session, run_id=run.id, event_type="phase_started")
        assert len(results) == 2


class TestAuxQueries:
    def test_create_phase(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        phase = create_phase(db_session, milestone_id=ms.id, phase_type="plan", model="opus")
        assert phase.phase_type == "plan"

    def test_create_quality_gate(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        gate = create_quality_gate(
            db_session,
            milestone_id=ms.id,
            checkpoint="qcb",
            gate_name="lint",
            passed=True,
        )
        assert gate.passed is True

    def test_create_coverage_result(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        cov = create_coverage_result(
            db_session,
            milestone_id=ms.id,
            coverage_pct=85.0,
            threshold=80.0,
            passed=True,
        )
        assert cov.coverage_pct == 85.0

    def test_create_gap_report(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        gap = create_gap_report(
            db_session,
            milestone_id=ms.id,
            pass_num=1,
            critical=0,
            architectural=1,
            important=2,
            minor=3,
        )
        assert gap.important == 2
