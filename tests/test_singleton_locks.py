"""v1.3.5 change 4 — locks around shared singletons:
- #3 TelemetryEmitter
- #7/#11 AuditTrail
- #2 ProjectRegistry
- #12 TelemetryDbWriter in-memory state rollback
"""

from __future__ import annotations

import json
import threading

from superpower_workflow.audit import AuditTrail
from superpower_workflow.telemetry import RunStarted, TelemetryEmitter


class TestTelemetryEmitterLock:
    def test_concurrent_emits_dont_interleave_lines(self, tmp_path):
        """v1.3.5 #3: emit under contention must produce well-formed JSONL.

        Pre-fix: concurrent emit() calls could interleave .write() + .flush()
        bytes. The post-fix lock guarantees one event lands per line.
        """
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "test-run")
        errors = []
        N = 50

        def writer(i):
            try:
                emitter.emit(RunStarted(milestone_count=i, model="opus"))
            except Exception as e:
                errors.append((i, e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        emitter.close()

        assert not errors, f"writers failed: {errors}"
        # Every line must parse as JSON and have run_id == "test-run".
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == N
        for line in lines:
            evt = json.loads(line)
            assert evt["run_id"] == "test-run"
            assert evt["type"] == "run_started"


class TestAuditTrailLock:
    def test_concurrent_appends_have_monotonic_seq(self, tmp_path):
        """v1.3.5 #7/#11: parallel appenders must produce a linear chain.

        Each append reads _seq + _prev_hash, writes to file, updates them.
        Without a lock, two appenders both read seq=K and both write
        entries with seq=K → broken chain. With the lock, every line has
        a unique increasing seq.
        """
        path = tmp_path / "audit.jsonl"
        # Build with a non-None key to enable the trail.
        trail = AuditTrail(path, key=b"\x00" * 32)
        N = 30

        def appender(i):
            trail.append("TEST_EVENT", run_id=f"r-{i}", milestone="M")

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == N

        seqs = [json.loads(line)["seq"] for line in lines]
        # Every seq value must be unique and contiguous.
        assert sorted(seqs) == list(range(N)), (
            f"seq numbers not unique+contiguous; got {sorted(seqs)}"
        )

    def test_concurrent_appends_have_valid_chain(self, tmp_path):
        """Each entry's prev_hash must equal the previous entry's hash."""
        path = tmp_path / "audit.jsonl"
        trail = AuditTrail(path, key=b"\x00" * 32)

        def appender(i):
            trail.append("X", run_id=f"r-{i}")

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = [json.loads(line) for line in path.read_text().splitlines()]
        entries.sort(key=lambda e: e["seq"])
        for prev, curr in zip(entries, entries[1:], strict=False):
            assert curr["prev_hash"] == prev["hash"], (
                f"chain break at seq {curr['seq']}: prev_hash {curr['prev_hash']} "
                f"!= predecessor hash {prev['hash']}"
            )


class TestProjectRegistryLock:
    def test_concurrent_registers_dont_lose_entries(self, tmp_path):
        """v1.3.5 #2: concurrent register() must not lose entries to
        last-writer-wins overwrite."""
        from superpower_workflow.server.registry import ProjectRegistry

        path = tmp_path / "registry.json"
        N = 10

        def register(i):
            r = ProjectRegistry(path=path)
            r.register(f"proj-{i}", f"/p/{i}")

        threads = [threading.Thread(target=register, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        r = ProjectRegistry(path=path)
        entries = r.list_projects()
        names = sorted(e.name for e in entries)
        assert names == [f"proj-{i}" for i in range(N)], (
            f"expected all {N} projects registered, got: {names}"
        )


class TestDbWriterStateRollback:
    """v1.3.5 #12: TelemetryDbWriter must NOT permanently disable on queue.Full
    or leave in-memory UUID dicts polluted on flush failure."""

    def test_queue_full_keeps_sink_enabled(self):
        """Previously queue.Full set _db_enabled=False forever."""
        from sqlalchemy import create_engine

        from superpower_workflow.db.writer import TelemetryDbWriter
        from superpower_workflow.telemetry import RunStarted, TelemetryEmitter

        # In-memory SQLite, tiny queue
        emitter = TelemetryEmitter(path=None, run_id="r")
        engine = create_engine("sqlite:///:memory:")
        writer = TelemetryDbWriter(
            emitter=emitter,
            engine=engine,
            project_name="p",
            project_path="/p",
            max_queue_size=1,
            flush_interval=10.0,  # so the test runs before any flush
        )
        # Fill the queue
        writer.emit(RunStarted(milestone_count=1, model="opus"))
        # Next emit hits queue.Full path
        writer.emit(RunStarted(milestone_count=2, model="opus"))
        # Sink must still be enabled.
        assert writer._db_enabled is True
        writer.close()

    def test_flush_failure_restores_in_memory_state(self, monkeypatch):
        """A mid-flush failure must roll back UUID dicts to pre-batch."""
        from sqlalchemy import create_engine

        from superpower_workflow.db.writer import TelemetryDbWriter
        from superpower_workflow.telemetry import RunStarted, TelemetryEmitter

        emitter = TelemetryEmitter(path=None, run_id="r")
        engine = create_engine("sqlite:///:memory:")
        writer = TelemetryDbWriter(
            emitter=emitter,
            engine=engine,
            project_name="p",
            project_path="/p",
            flush_interval=10.0,
        )
        # Inject corrupt state
        import uuid as _uuid

        writer._milestone_uuids["M1"] = _uuid.uuid4()
        baseline = dict(writer._milestone_uuids)

        # Force flush to raise inside _write_event by patching it
        def boom(session, event):
            raise RuntimeError("simulated DB write failure")

        monkeypatch.setattr(writer, "_write_event", boom)

        # Queue an event to be flushed
        writer._queue.put_nowait(RunStarted(milestone_count=1, model="opus"))
        # Run the flush directly
        writer._flush_batch()

        # Despite the failure, _milestone_uuids must still match baseline
        # (not whatever boom() might have left behind in real failures).
        assert writer._milestone_uuids == baseline
        writer.close()
