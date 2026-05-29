from __future__ import annotations

import json

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwMilestone, SwPhase, SwProject, SwRun
from superpower_workflow.db.sync_adapter import DbSyncAdapter


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def jsonl_file(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    events = [
        {
            "type": "run_started",
            "run_id": "20260525-120000",
            "timestamp": "2026-05-25T12:00:00Z",
            "model": "opus",
            "spec_sha": "abc123",
            "milestone_count": 2,
        },
        {
            "type": "milestone_started",
            "run_id": "20260525-120000",
            "timestamp": "2026-05-25T12:00:01Z",
            "milestone": "m1",
            "index": 0,
        },
        {
            "type": "phase_completed",
            "run_id": "20260525-120000",
            "timestamp": "2026-05-25T12:00:02Z",
            "milestone": "m1",
            "phase": "plan",
            "cost_usd": 2.5,
            "duration_ms": 30000,
        },
        {
            "type": "milestone_completed",
            "run_id": "20260525-120000",
            "timestamp": "2026-05-25T12:00:03Z",
            "milestone": "m1",
            "cost_usd": 10.0,
            "duration_seconds": 120.0,
        },
        {
            "type": "run_completed",
            "run_id": "20260525-120000",
            "timestamp": "2026-05-25T12:00:04Z",
            "status": "complete",
            "total_cost_usd": 10.0,
            "completed_count": 1,
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in events))
    return path


class TestDbSyncAdapter:
    def test_sync_creates_project(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        projects = session.query(SwProject).all()
        assert len(projects) == 1
        assert projects[0].name == "app"
        session.close()

    def test_sync_creates_run(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        assert runs[0].run_id == "20260525-120000"
        session.close()

    def test_sync_creates_events(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) == 5
        session.close()

    def test_sync_idempotent(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        session.close()

    def test_sync_empty_file(self, db_engine, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        factory = get_session_factory(db_engine)
        session = factory()
        assert session.query(SwRun).count() == 0
        session.close()

    def test_sync_missing_file(self, db_engine, tmp_path):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=tmp_path / "nope.jsonl")

    def test_sync_materializes_milestones_per_run(self, db_engine, tmp_path):
        """Regression for soak bug #3: shared milestone_uuids dict undercounted."""
        events = [
            {"type": "run_started", "run_id": "r1", "model": "opus", "milestone_count": 1},
            {"type": "milestone_started", "run_id": "r1", "milestone": "shared-name"},
            {"type": "run_started", "run_id": "r2", "model": "opus", "milestone_count": 1},
            {"type": "milestone_started", "run_id": "r2", "milestone": "shared-name"},
        ]
        path = tmp_path / "two-runs.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events))
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        session = get_session_factory(db_engine)()
        try:
            milestones = session.query(SwMilestone).all()
            assert len(milestones) == 2, (
                "Each run must materialize its own milestone, even with shared name"
            )
            runs = {m.run_id for m in milestones}
            assert len(runs) == 2
        finally:
            session.close()

    def test_sync_materializes_phases(self, db_engine, jsonl_file):
        """Regression for soak bug #2: phase_started events did not produce sw_phases rows."""
        events = [
            {"type": "run_started", "run_id": "rP", "model": "opus", "milestone_count": 1},
            {"type": "milestone_started", "run_id": "rP", "milestone": "mP"},
            {
                "type": "phase_started",
                "run_id": "rP",
                "milestone": "mP",
                "phase": "plan",
                "model": "opus",
            },
            {
                "type": "phase_completed",
                "run_id": "rP",
                "milestone": "mP",
                "phase": "plan",
                "status": "completed",
                "cost_usd": 1.5,
                "duration_ms": 5000,
                "input_tokens": 1000,
                "output_tokens": 500,
            },
        ]
        path = jsonl_file.parent / "phases.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events))
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        session = get_session_factory(db_engine)()
        try:
            phases = session.query(SwPhase).all()
            assert len(phases) == 1
            p = phases[0]
            assert p.phase_type == "plan"
            assert p.status == "completed"
            assert p.cost_usd == 1.5
            assert p.duration_ms == 5000
            assert p.input_tokens == 1000
            assert p.output_tokens == 500
        finally:
            session.close()

    def test_sync_corrupt_lines_skipped(self, db_engine, tmp_path):
        path = tmp_path / "corrupt.jsonl"
        path.write_text(
            "not json\n{bad\n"
            + json.dumps(
                {
                    "type": "run_started",
                    "run_id": "r1",
                    "timestamp": "2026-05-25T12:00:00Z",
                    "model": "opus",
                    "milestone_count": 1,
                }
            )
        )
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) == 1
        session.close()
