from __future__ import annotations

import pytest

from superpower_workflow.db.engine import (
    create_engine_from_url,
    ensure_schema_current,
    get_session_factory,
)
from superpower_workflow.db.models import Base, SwEvent, SwPhase, SwProject, SwRun
from superpower_workflow.db.writer import TelemetryDbWriter
from superpower_workflow.telemetry import (
    MilestoneStarted,
    PhaseCompleted,
    PhaseStarted,
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


class TestCacheTokenPersistenceV1314:
    """v1.3.14 closes the v1.1.6 silent bug — SwPhase had no columns for
    cache_creation_input_tokens, cache_read_input_tokens, cache_hit_rate
    despite PhaseCompleted carrying them. The writer's phase_completed
    branch dropped them on the floor. These tests pin the bug fixed.
    """

    def _round_trip(self, mock_emitter, db_engine, **phase_completed_kwargs):
        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseStarted(milestone="m1", phase="plan"))
        writer.emit(
            PhaseCompleted(
                milestone="m1",
                phase="plan",
                cost_usd=2.0,
                duration_ms=5000,
                **phase_completed_kwargs,
            )
        )
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        try:
            phases = session.query(SwPhase).all()
            assert len(phases) == 1, f"expected one SwPhase row; got {len(phases)}"
            return phases[0]
        finally:
            session.close()

    def test_cache_creation_input_tokens_persisted(self, mock_emitter, db_engine):
        phase = self._round_trip(
            mock_emitter,
            db_engine,
            input_tokens=1000,
            output_tokens=500,
            cache_creation_input_tokens=29000,
            cache_read_input_tokens=12000,
            cache_hit_rate=0.293,
        )
        assert phase.cache_creation_input_tokens == 29000
        assert phase.cache_read_input_tokens == 12000
        # Float comparison with a small tolerance.
        assert abs(phase.cache_hit_rate - 0.293) < 1e-6

    def test_legacy_input_output_still_persist(self, mock_emitter, db_engine):
        phase = self._round_trip(
            mock_emitter,
            db_engine,
            input_tokens=1234,
            output_tokens=567,
        )
        assert phase.input_tokens == 1234
        assert phase.output_tokens == 567
        # New fields default to zero, not None.
        assert phase.cache_creation_input_tokens == 0
        assert phase.cache_read_input_tokens == 0
        assert phase.cache_hit_rate == 0.0

    def test_cache_fields_fall_back_to_usage_dict(self, mock_emitter, db_engine):
        """Legacy event dicts pass the claude envelope through as `usage`.
        Writer must read cache fields from there when top-level is absent.
        """
        from superpower_workflow.db.writer import TelemetryDbWriter

        writer = TelemetryDbWriter(
            emitter=mock_emitter,
            engine=db_engine,
            project_name="app",
            project_path="/p",
        )
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseStarted(milestone="m1", phase="plan"))

        # Craft an event whose to_dict() returns a usage envelope only.
        class LegacyPhaseCompleted(PhaseCompleted):
            def to_dict(self):
                d = super().to_dict()
                d["usage"] = {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 7777,
                    "cache_read_input_tokens": 8888,
                }
                # Wipe top-level cache fields to force the fallback path.
                d.pop("cache_creation_input_tokens", None)
                d.pop("cache_read_input_tokens", None)
                return d

        writer.emit(LegacyPhaseCompleted(milestone="m1", phase="plan", cost_usd=1.0))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        try:
            phase = session.query(SwPhase).first()
            assert phase is not None
            assert phase.cache_creation_input_tokens == 7777
            assert phase.cache_read_input_tokens == 8888
        finally:
            session.close()


class TestSchemaMigrationV1314:
    """v1.3.14 ensure_schema_current is idempotent and brings forward
    DBs created against the pre-v1.3.14 SwPhase schema (input_tokens +
    output_tokens only).
    """

    def test_create_all_then_ensure_is_noop(self, tmp_path):
        engine = create_engine_from_url(f"sqlite:///{tmp_path / 'db.sqlite'}")
        Base.metadata.create_all(engine)
        added = ensure_schema_current(engine)
        assert added == [], f"fresh create_all should leave nothing to migrate; got {added}"

    def test_legacy_schema_gets_cache_columns(self, tmp_path):
        """Simulate a pre-v1.3.14 DB: sw_phases without cache_* columns."""
        from sqlalchemy import text

        db_path = tmp_path / "legacy.sqlite"
        engine = create_engine_from_url(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE sw_phases (id BLOB PRIMARY KEY, milestone_id BLOB NOT NULL, "
                    "phase_type VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', "
                    "cost_usd FLOAT DEFAULT 0.0, duration_ms INTEGER DEFAULT 0, "
                    "session_id VARCHAR(100), model VARCHAR(50), "
                    "input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, "
                    "started_at DATETIME, completed_at DATETIME)"
                )
            )
        added = ensure_schema_current(engine)
        added_columns = {a.split(".", 1)[1] for a in added}
        assert added_columns == {
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "cache_hit_rate",
        }, f"expected 3 cache columns added; got {added}"

        # Idempotent: second call is a no-op.
        assert ensure_schema_current(engine) == []
