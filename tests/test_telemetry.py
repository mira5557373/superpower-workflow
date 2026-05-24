import json

from superpower_workflow.telemetry import TelemetryEvent


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
