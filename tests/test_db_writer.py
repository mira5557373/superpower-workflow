from __future__ import annotations

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwProject, SwRun
from superpower_workflow.db.writer import TelemetryDbWriter
from superpower_workflow.telemetry import (
    MilestoneStarted,
    PhaseCompleted,
    RunStarted,
    TelemetryEmitter,
)


@pytest.fixture
def mock_emitter(tmp_path):
    return TelemetryEmitter(tmp_path / "telemetry.jsonl", run_id="test-run")


@pytest.fixture
def db_engine(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine_from_url(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


class TestDuckTyping:
    def test_has_emit_method(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        assert hasattr(writer, "emit")
        writer.close()

    def test_has_close_method(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        assert hasattr(writer, "close")
        writer.close()


class TestEmitPassthrough:
    def test_forwards_to_emitter(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        event = RunStarted(spec_sha="abc123", model="opus", milestone_count=3)
        writer.emit(event)
        writer.close()
        content = mock_emitter._path.read_text()
        assert "run_started" in content

    def test_close_flushes_queue(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        event = RunStarted(spec_sha="abc", model="opus", milestone_count=1)
        writer.emit(event)
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) >= 1
        session.close()


class TestDbWrites:
    def test_writes_run_started_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=3))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        projects = session.query(SwProject).all()
        assert len(projects) == 1
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        session.close()

    def test_writes_milestone_started_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        types = [e.event_type for e in events]
        assert "milestone_started" in types
        session.close()

    def test_writes_phase_completed_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseCompleted(milestone="m1", phase="plan", cost_usd=2.0, duration_ms=5000))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).filter(SwEvent.event_type == "phase_completed").all()
        assert len(events) == 1
        session.close()


class TestFailsafe:
    def test_continues_after_db_disabled(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer._db_enabled = False
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.close()
        content = mock_emitter._path.read_text()
        assert "milestone_started" in content

    def test_emitter_always_writes(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.close()
        assert mock_emitter._path.exists()
