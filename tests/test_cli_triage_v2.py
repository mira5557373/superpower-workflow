"""CLI tests for v1.3.27 deferred triage flags: --reclassify, --explain, --health."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from superpower_workflow import cli as cli_module


@pytest.fixture
def project_with_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "workflow.json").write_text(
        json.dumps({"model": "claude-haiku-4-5"}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str, str]]:
    def _run(*args: str) -> tuple[int, str, str]:
        monkeypatch.setattr(sys, "argv", ["sw", *args])
        code = 0
        try:
            cli_module.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def _seed_failures(project: Path, n: int = 5) -> None:
    """Seed n MilestoneFailed events that will classify as QUALITY_GATE_FAIL."""
    tel = project / ".claude" / "sw-telemetry.jsonl"
    events = []
    for i in range(n):
        events.append(
            {
                "type": "milestone_started",
                "run_id": "r1",
                "milestone": f"M{i}",
                "index": i,
            }
        )
        events.append(
            {
                "type": "quality_gate_result",
                "run_id": "r1",
                "milestone": f"M{i}",
                "gate": "lint",
                "checkpoint": "QG2",
                "passed": False,
            }
        )
        events.append(
            {
                "type": "milestone_failed",
                "run_id": "r1",
                "milestone": f"M{i}",
                "phase": "review",
                "reason": "quality gate failed",
            }
        )
    tel.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


class TestTriageExplain:
    def test_known_class_prints_rule_and_recommendation(
        self, project_with_workflow: Path, run_cli
    ) -> None:
        code, out, _ = run_cli("triage", "--explain", "quality_gate_fail")
        assert code == 0
        assert "quality_gate_fail" in out
        assert "Recommendation:" in out
        assert "rule_" in out.lower() or "Rule:" in out

    def test_unknown_class_exits_3(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("triage", "--explain", "not_a_real_class")
        assert code == 3
        assert "Valid values:" in out

    def test_explain_json(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("triage", "--explain", "policy_violation", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["class"] == "policy_violation"
        assert payload["recommendation"]
        assert "rule_id" in payload
        # POLICY_VIOLATION subsumes QUALITY_GATE_FAIL per IMPLIES graph.
        assert "quality_gate_fail" in payload["implies_subsumes"]


class TestTriageReclassify:
    def test_no_telemetry_exits_2(self, project_with_workflow: Path, run_cli) -> None:
        code, _, _ = run_cli("triage", "--reclassify")
        assert code == 2

    def test_writes_sidecar(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failures(project_with_workflow, n=3)
        code, out, _ = run_cli("triage", "--reclassify")
        assert code == 0
        sidecar = project_with_workflow / ".claude" / ".triage-replay.jsonl"
        assert sidecar.exists()
        lines = sidecar.read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            payload = json.loads(line)
            assert payload["type"] == "failure_triaged"
            assert payload["primary_class"] == "quality_gate_fail"

    def test_does_not_mutate_telemetry(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failures(project_with_workflow, n=2)
        tel = project_with_workflow / ".claude" / "sw-telemetry.jsonl"
        before = tel.read_bytes()
        run_cli("triage", "--reclassify")
        after = tel.read_bytes()
        assert before == after

    def test_json_output(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failures(project_with_workflow, n=2)
        code, out, _ = run_cli("triage", "--reclassify", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["replayed_count"] == 2
        assert payload["triage_version"] == 1


class TestTriageHealth:
    def test_no_telemetry_exits_2(self, project_with_workflow: Path, run_cli) -> None:
        code, _, _ = run_cli("triage", "--health")
        assert code == 2

    def test_healthy_low_unknown_rate(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failures(project_with_workflow, n=5)
        code, out, _ = run_cli("triage", "--health")
        assert code == 0
        assert "OK" in out
        assert "0/5" in out or "0.0%" in out

    def test_health_json(self, project_with_workflow: Path, run_cli) -> None:
        _seed_failures(project_with_workflow, n=3)
        code, out, _ = run_cli("triage", "--health", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["window_size"] == 3
        assert payload["healthy"] is True
        assert payload["unknown_count"] == 0
        assert payload["class_distribution"]["quality_gate_fail"] == 3


class TestBreakerStatus:
    def test_empty_window(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("breaker", "status")
        assert code == 0
        assert "Circuit Breaker" in out
        assert "No failures" in out

    def test_status_json(self, project_with_workflow: Path, run_cli) -> None:
        code, out, _ = run_cli("breaker", "status", "--json")
        assert code == 0
        payload = json.loads(out)
        assert payload["enabled"] is True
        assert payload["observation_only"] is True
        assert payload["window"] == []
        assert payload["counter"] == {}
        assert "policy_violation" in payload["same_class_thresholds"]

    def test_status_with_entries(self, project_with_workflow: Path, run_cli) -> None:
        # Seed state with breaker entries.
        from superpower_workflow.state import load_state, save_state

        state = load_state(project_with_workflow / ".claude")
        state.breaker_window = [
            {
                "milestone_name": "M1",
                "primary_class": "policy_violation",
                "confidence": 1.0,
                "triage_event_id": "ev1",
                "ts": "2026-06-02T00:00:00Z",
            },
            {
                "milestone_name": "M2",
                "primary_class": "policy_violation",
                "confidence": 1.0,
                "triage_event_id": "ev2",
                "ts": "2026-06-02T01:00:00Z",
            },
        ]
        save_state(project_with_workflow / ".claude", state)
        code, out, _ = run_cli("breaker", "status")
        assert code == 0
        assert "policy_violation" in out
        # Threshold for policy_violation = 2, count = 2 → TRIP
        assert "TRIP" in out


class TestBreakerReset:
    def test_dry_run_does_not_clear(self, project_with_workflow: Path, run_cli) -> None:
        from superpower_workflow.state import load_state, save_state

        state = load_state(project_with_workflow / ".claude")
        state.breaker_window = [
            {
                "milestone_name": "M1",
                "primary_class": "policy_violation",
                "confidence": 1.0,
                "triage_event_id": "ev1",
                "ts": "2026-06-02T00:00:00Z",
            }
        ]
        save_state(project_with_workflow / ".claude", state)
        code, out, _ = run_cli("breaker", "reset")
        assert code == 0
        assert "DRY-RUN" in out
        # Window still has the entry.
        reloaded = load_state(project_with_workflow / ".claude")
        assert len(reloaded.breaker_window) == 1

    def test_confirm_clears_window(self, project_with_workflow: Path, run_cli) -> None:
        from superpower_workflow.state import load_state, save_state

        state = load_state(project_with_workflow / ".claude")
        state.breaker_window = [
            {
                "milestone_name": "M1",
                "primary_class": "policy_violation",
                "confidence": 1.0,
                "triage_event_id": "ev1",
                "ts": "2026-06-02T00:00:00Z",
            }
        ]
        save_state(project_with_workflow / ".claude", state)
        code, out, _ = run_cli("breaker", "reset", "--confirm")
        assert code == 0
        assert "Reset" in out
        reloaded = load_state(project_with_workflow / ".claude")
        assert reloaded.breaker_window == []
