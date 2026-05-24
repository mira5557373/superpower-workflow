import json

from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
    RunCompleted,
    RunStarted,
    TelemetryEvent,
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
