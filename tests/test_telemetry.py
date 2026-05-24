import json

from superpower_workflow.telemetry import (
    CoverageResult,
    GapReport,
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
    PhaseCompleted,
    PhaseStarted,
    QualityGateResult,
    RetryAttempt,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
    TelemetryEvent,
    TelemetryReader,
)


class TestTelemetryEventBase:
    def test_auto_timestamp(self):
        e = TelemetryEvent(run_id="r1")
        assert e.timestamp != ""
        assert "T" in e.timestamp
        assert e.timestamp.endswith("Z")

    def test_explicit_timestamp(self):
        e = TelemetryEvent(timestamp="2026-01-01T00:00:00Z", run_id="r1")
        assert e.timestamp == "2026-01-01T00:00:00Z"

    def test_to_dict_includes_type(self):
        e = TelemetryEvent(run_id="r1")
        d = e.to_dict()
        assert d["type"] == "base"
        assert d["run_id"] == "r1"
        assert "timestamp" in d

    def test_to_json_line_valid_json(self):
        e = TelemetryEvent(run_id="r1")
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "base"
        assert "\n" not in line

    def test_to_json_line_no_trailing_newline(self):
        e = TelemetryEvent(run_id="r1")
        line = e.to_json_line()
        assert not line.endswith("\n")


class TestRunEvents:
    def test_run_started_type(self):
        e = RunStarted(
            run_id="r1",
            spec_sha="abc123",
            model="opus",
            milestone_count=5,
            max_budget_usd=500.0,
        )
        d = e.to_dict()
        assert d["type"] == "run_started"
        assert d["spec_sha"] == "abc123"
        assert d["model"] == "opus"
        assert d["milestone_count"] == 5
        assert d["max_budget_usd"] == 500.0

    def test_run_completed_type(self):
        e = RunCompleted(
            run_id="r1",
            status="complete",
            completed_count=3,
            failed_count=1,
            skipped_count=0,
            total_cost_usd=42.50,
            duration_seconds=1200.0,
            test_file_count=10,
        )
        d = e.to_dict()
        assert d["type"] == "run_completed"
        assert d["status"] == "complete"
        assert d["completed_count"] == 3
        assert d["total_cost_usd"] == 42.50
        assert d["test_file_count"] == 10

    def test_run_events_serialize_to_valid_jsonl(self):
        for event in [
            RunStarted(run_id="r1", model="opus"),
            RunCompleted(run_id="r1", status="complete"),
        ]:
            parsed = json.loads(event.to_json_line())
            assert "type" in parsed
            assert "run_id" in parsed


class TestMilestoneEvents:
    def test_milestone_started(self):
        e = MilestoneStarted(run_id="r1", milestone="m1", index=0)
        d = e.to_dict()
        assert d["type"] == "milestone_started"
        assert d["milestone"] == "m1"
        assert d["index"] == 0

    def test_milestone_completed(self):
        e = MilestoneCompleted(run_id="r1", milestone="m1", cost_usd=15.0, duration_seconds=300.0)
        d = e.to_dict()
        assert d["type"] == "milestone_completed"
        assert d["cost_usd"] == 15.0
        assert d["duration_seconds"] == 300.0

    def test_milestone_failed(self):
        e = MilestoneFailed(
            run_id="r1", milestone="m1", phase="Phase B", reason="timeout", attempts=3
        )
        d = e.to_dict()
        assert d["type"] == "milestone_failed"
        assert d["phase"] == "Phase B"
        assert d["attempts"] == 3

    def test_milestone_skipped(self):
        e = MilestoneSkipped(run_id="r1", milestone="m2", reason="depends on failed: ['m1']")
        d = e.to_dict()
        assert d["type"] == "milestone_skipped"
        assert "m1" in d["reason"]


class TestPhaseEvents:
    def test_phase_started(self):
        e = PhaseStarted(run_id="r1", milestone="m1", phase="plan")
        d = e.to_dict()
        assert d["type"] == "phase_started"
        assert d["milestone"] == "m1"
        assert d["phase"] == "plan"

    def test_phase_completed(self):
        e = PhaseCompleted(
            run_id="r1",
            milestone="m1",
            phase="implement",
            cost_usd=25.0,
            duration_ms=60000,
            session_id="s1",
            input_tokens=5000,
            output_tokens=3000,
        )
        d = e.to_dict()
        assert d["type"] == "phase_completed"
        assert d["cost_usd"] == 25.0
        assert d["duration_ms"] == 60000
        assert d["session_id"] == "s1"
        assert d["input_tokens"] == 5000
        assert d["output_tokens"] == 3000

    def test_phase_completed_defaults_tokens_to_zero(self):
        e = PhaseCompleted(run_id="r1", milestone="m1", phase="plan")
        d = e.to_dict()
        assert d["input_tokens"] == 0
        assert d["output_tokens"] == 0


class TestQualityEvents:
    def test_quality_gate_result(self):
        e = QualityGateResult(
            run_id="r1",
            milestone="m1",
            checkpoint="quality_check_b",
            gate="lint",
            passed=False,
            detail="E501 line too long",
        )
        d = e.to_dict()
        assert d["type"] == "quality_gate_result"
        assert d["passed"] is False
        assert d["gate"] == "lint"

    def test_coverage_result(self):
        e = CoverageResult(
            run_id="r1",
            milestone="m1",
            coverage_pct=85.0,
            threshold=80.0,
            passed=True,
        )
        d = e.to_dict()
        assert d["type"] == "coverage_result"
        assert d["coverage_pct"] == 85.0

    def test_retry_attempt(self):
        e = RetryAttempt(
            run_id="r1",
            milestone="m1",
            phase="Phase B",
            attempt=2,
            reason="timeout",
            delay_seconds=120,
        )
        d = e.to_dict()
        assert d["type"] == "retry_attempt"
        assert d["attempt"] == 2
        assert d["delay_seconds"] == 120

    def test_gap_report(self):
        e = GapReport(
            run_id="r1",
            milestone="m1",
            phase="plan",
            critical_gaps=0,
            important_gaps=3,
            total_gaps_found=12,
            converged=True,
        )
        d = e.to_dict()
        assert d["type"] == "gap_report"
        assert d["critical_gaps"] == 0
        assert d["total_gaps_found"] == 12
        assert d["converged"] is True


class TestTelemetryEmitter:
    def test_emit_creates_file(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert path.exists()

    def test_emit_writes_valid_jsonl(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.emit(RunCompleted(status="complete", total_cost_usd=10.0))
        emitter.close()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert parsed["run_id"] == "r1"

    def test_emit_sets_run_id(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "run-42")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        parsed = json.loads(path.read_text().strip())
        assert parsed["run_id"] == "run-42"

    def test_emit_appends_to_existing(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        path.write_text('{"type":"old","run_id":"r0"}\n')
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["run_id"] == "r0"
        assert json.loads(lines[1])["run_id"] == "r1"

    def test_disabled_emitter_writes_nothing(self, tmp_path):
        emitter = TelemetryEmitter.disabled()
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert not (tmp_path / "telemetry.jsonl").exists()

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert path.exists()

    def test_close_is_idempotent(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        emitter.close()


def _write_events(path, events):
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


class TestTelemetryReader:
    def test_reads_all_events(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        assert len(reader.events()) == 2

    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        path.write_text("")
        reader = TelemetryReader(path)
        assert reader.events() == []

    def test_missing_file_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.events() == []

    def test_filter_by_type(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "phase_completed", "run_id": "r1", "phase": "plan"},
                {"type": "phase_completed", "run_id": "r1", "phase": "implement"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        phases = reader.events_by_type("phase_completed")
        assert len(phases) == 2

    def test_filter_by_run_id(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_started", "run_id": "r2"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        r1_events = reader.events_for_run("r1")
        assert len(r1_events) == 2

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        path.write_text(
            '{"type":"run_started","run_id":"r1"}\nnot-json\n{"type":"run_completed","run_id":"r1"}\n'
        )
        reader = TelemetryReader(path)
        assert len(reader.events()) == 2

    def test_latest_run_id(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_completed", "run_id": "r1"},
                {"type": "run_started", "run_id": "r2"},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.latest_run_id() == "r2"

    def test_latest_run_id_empty(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.latest_run_id() is None


class TestCostMetrics:
    def test_cost_by_milestone(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {
                    "type": "milestone_completed",
                    "run_id": "r1",
                    "milestone": "m1",
                    "cost_usd": 15.0,
                },
                {
                    "type": "milestone_completed",
                    "run_id": "r1",
                    "milestone": "m2",
                    "cost_usd": 25.0,
                },
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_milestone()
        assert costs == {"m1": 15.0, "m2": 25.0}

    def test_cost_by_phase(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 5.0},
                {"type": "phase_completed", "run_id": "r1", "phase": "implement", "cost_usd": 20.0},
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 3.0},
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_phase()
        assert costs == {"plan": 8.0, "implement": 20.0}

    def test_cost_per_successful_task(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {
                    "type": "run_completed",
                    "run_id": "r1",
                    "total_cost_usd": 50.0,
                    "completed_count": 5,
                },
            ],
        )
        reader = TelemetryReader(path)
        assert reader.cost_per_successful_task() == 10.0

    def test_cost_per_successful_task_no_completions(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {
                    "type": "run_completed",
                    "run_id": "r1",
                    "total_cost_usd": 50.0,
                    "completed_count": 0,
                },
            ],
        )
        reader = TelemetryReader(path)
        assert reader.cost_per_successful_task() == 0.0

    def test_total_cost(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {"type": "run_completed", "run_id": "r1", "total_cost_usd": 30.0},
                {"type": "run_completed", "run_id": "r2", "total_cost_usd": 20.0},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.total_cost() == 50.0

    def test_cost_by_milestone_filtered_by_run(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        _write_events(
            path,
            [
                {
                    "type": "milestone_completed",
                    "run_id": "r1",
                    "milestone": "m1",
                    "cost_usd": 10.0,
                },
                {
                    "type": "milestone_completed",
                    "run_id": "r2",
                    "milestone": "m1",
                    "cost_usd": 15.0,
                },
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_milestone(run_id="r2")
        assert costs == {"m1": 15.0}
