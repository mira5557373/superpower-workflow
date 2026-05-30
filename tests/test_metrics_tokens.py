"""Tests for sw metrics token analytics (T1.7.3 / v1.1.7.3)."""

from __future__ import annotations

import json

from superpower_workflow.cli import _aggregate_token_stats, _cmd_metrics


def _phase_event(run_id="r1", phase="plan", **tokens):
    return {
        "type": "phase_completed",
        "run_id": run_id,
        "phase": phase,
        "milestone": "m1",
        "cost_usd": 1.0,
        **tokens,
    }


class TestAggregateTokenStats:
    def test_sums_across_phases(self):
        events = [
            _phase_event(
                phase="plan",
                input_tokens=10,
                output_tokens=20,
                cache_creation_input_tokens=100,
                cache_read_input_tokens=900,
            ),
            _phase_event(
                phase="implement",
                input_tokens=5,
                output_tokens=50,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=3000,
            ),
        ]
        s = _aggregate_token_stats(events, "r1")
        assert s["total_input"] == 15
        assert s["total_output"] == 70
        assert s["total_cache_creation"] == 300
        assert s["total_cache_read"] == 3900

    def test_computes_cache_hit_rate(self):
        # Per-phase: 10 input + 100 creation + 900 read = 1010 denom; hit = 900/1010 ≈ 0.891
        # Per-phase: 5 input + 200 creation + 3000 read = 3205 denom; hit = 3000/3205 ≈ 0.936
        # Aggregate: 15 + 300 + 3900 = 4215 denom; hit = 3900/4215 ≈ 0.9253
        events = [
            _phase_event(
                phase="plan",
                input_tokens=10,
                cache_creation_input_tokens=100,
                cache_read_input_tokens=900,
            ),
            _phase_event(
                phase="implement",
                input_tokens=5,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=3000,
            ),
        ]
        s = _aggregate_token_stats(events, "r1")
        assert 0.92 < s["cache_hit_rate"] < 0.93

    def test_computes_tokens_per_dollar(self):
        # (15 + 70) / (1.0 + 1.0) = 42.5 -> rounded
        events = [
            _phase_event(phase="plan", input_tokens=10, output_tokens=20),
            _phase_event(phase="implement", input_tokens=5, output_tokens=50),
        ]
        s = _aggregate_token_stats(events, "r1")
        assert s["tokens_per_dollar"] in (42, 43)  # rounding tolerance

    def test_per_phase_breakdown(self):
        events = [
            _phase_event(
                phase="plan",
                input_tokens=10,
                cache_creation_input_tokens=100,
                cache_read_input_tokens=900,
            ),
            _phase_event(
                phase="implement",
                input_tokens=5,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=3000,
            ),
        ]
        s = _aggregate_token_stats(events, "r1")
        assert "plan" in s["per_phase"]
        assert "implement" in s["per_phase"]
        assert 0.88 < s["per_phase"]["plan"] < 0.90

    def test_filters_by_run_id(self):
        events = [
            _phase_event(run_id="r1", input_tokens=10),
            _phase_event(run_id="r2", input_tokens=999),
        ]
        s = _aggregate_token_stats(events, "r1")
        assert s["total_input"] == 10

    def test_zero_denom_returns_zero_rate(self):
        s = _aggregate_token_stats([], "")
        assert s["cache_hit_rate"] == 0.0
        assert s["tokens_per_dollar"] == 0

    def test_handles_missing_token_fields(self):
        """Legacy events from before v1.1.6 had no token fields. Don't crash."""
        events = [{"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 1.0}]
        s = _aggregate_token_stats(events, "r1")
        assert s["total_input"] == 0


class TestMetricsCommandOutput:
    def test_text_output_includes_tokens_section(self, tmp_path, capsys):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "workflow.json").write_text(
            json.dumps({"telemetry": {"path": ".claude/telemetry.jsonl"}})
        )
        events = [
            {"type": "run_started", "run_id": "r1", "model": "opus"},
            _phase_event(
                phase="plan",
                input_tokens=100,
                output_tokens=500,
                cache_creation_input_tokens=1000,
                cache_read_input_tokens=9000,
            ),
            {"type": "run_completed", "run_id": "r1", "status": "complete"},
        ]
        (claude_dir / "telemetry.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        _cmd_metrics(tmp_path, json_output=False)
        out = capsys.readouterr().out
        assert "Tokens" in out
        assert "cache_hit_rate" in out

    def test_json_output_includes_tokens(self, tmp_path, capsys):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "workflow.json").write_text(
            json.dumps({"telemetry": {"path": ".claude/telemetry.jsonl"}})
        )
        events = [
            {"type": "run_started", "run_id": "r1", "model": "opus"},
            _phase_event(phase="plan", input_tokens=100, cache_read_input_tokens=9000),
            {"type": "run_completed", "run_id": "r1", "status": "complete"},
        ]
        (claude_dir / "telemetry.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        _cmd_metrics(tmp_path, json_output=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "tokens" in data
        assert "cache_hit_rate" in data["tokens"]
