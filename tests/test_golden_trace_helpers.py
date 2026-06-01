"""Unit tests for the golden-trace recorder helpers.

These tests verify the recorder infrastructure works correctly BEFORE we
build the full _run_milestone parity oracle on top of it. If the
recorder itself has bugs (e.g., subscriber wraps emit incorrectly,
subprocess dispatcher returns wrong rc, accumulate_cost wrapper double-
charges), the oracle gives false signal.

Each test class corresponds to one piece of the recorder API.
"""

from __future__ import annotations

import json

import pytest

from tests.golden_trace_helpers import (
    CALL_COSTS,
    DETERMINISTIC_SHA,
    TOKEN_SHAPES,
    TraceRecorder,
    assert_trace_matches_fixture,
    make_accumulate_cost_wrapper,
    make_run_claude_stub,
    make_save_state_recorder,
    make_subprocess_dispatcher,
    make_telemetry_subscriber,
)


class TestTraceRecorderArrivalOrder:
    def test_call_index_increments_monotonically(self):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        r.record("accumulate_cost", delta=1.0, new_local=1.0, new_state_total=1.0)
        r.record("event", event_type="phase_completed")
        assert [rec.call_index for rec in r.records] == [0, 1, 2]

    def test_records_are_threadsafe(self):
        import threading

        r = TraceRecorder()

        def worker(n):
            for _ in range(50):
                r.record("event", event_type=f"w{n}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 200 records total, every call_index unique.
        assert len(r.records) == 200
        assert len({rec.call_index for rec in r.records}) == 200

    def test_event_types_view(self):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        r.record("save_state", claude_dir=".claude", current_step="plan", total_cost_usd=0.0)
        r.record("event", event_type="phase_completed")
        assert r.event_types == ["phase_started", "phase_completed"]

    def test_per_kind_views(self):
        r = TraceRecorder()
        r.record("event", event_type="x")
        r.record("accumulate_cost", delta=1.0, new_local=1.0, new_state_total=1.0)
        r.record("save_state", claude_dir=".c", current_step="plan", total_cost_usd=0.0)
        r.record("subprocess", head="git", cmd="git rev-parse HEAD", shell=False)
        r.record("run_claude", call_index_local=0, cost=1.0, session_id="s0", usage={})

        assert len(r.events) == 1
        assert len(r.accumulate_cost_calls) == 1
        assert len(r.save_state_calls) == 1
        assert len(r.subprocess_calls) == 1
        assert len(r.run_claude_calls) == 1


class TestTraceRecorderSerialization:
    def test_to_dict_is_json_safe(self, tmp_path):
        r = TraceRecorder()
        path = tmp_path / ".claude"
        r.record("save_state", claude_dir=path, current_step="plan", total_cost_usd=0.0)
        r.record("subprocess", head="git", cmd_set={"git", "rev-parse"}, shell=False)

        d = r.to_dict()
        # Must not raise.
        s = json.dumps(d)
        # Path → str round-trip (platform-native separators are OK; we
        # only care that it serialises as the same string the OS uses).
        re_loaded = json.loads(s)
        assert re_loaded["records"][0]["payload"]["claude_dir"] == str(path)
        # Set → sorted list.
        assert re_loaded["records"][1]["payload"]["cmd_set"] == ["git", "rev-parse"]


class TestSubprocessDispatcher:
    def test_git_rev_parse_returns_deterministic_sha(self):
        r = TraceRecorder()
        dispatcher = make_subprocess_dispatcher(r)
        result = dispatcher(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        assert result.returncode == 0
        assert result.stdout.strip() == DETERMINISTIC_SHA

    def test_git_tag_returns_rc_zero(self):
        r = TraceRecorder()
        dispatcher = make_subprocess_dispatcher(r)
        result = dispatcher(["git", "tag", "pre-impl/M1"], capture_output=True)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_gate_command_returns_configured_rc(self):
        r = TraceRecorder()
        dispatcher_pass = make_subprocess_dispatcher(r, gate_returncode=0)
        dispatcher_fail = make_subprocess_dispatcher(r, gate_returncode=1)
        assert dispatcher_pass("ruff check .", shell=True).returncode == 0
        assert dispatcher_fail("ruff check .", shell=True).returncode == 1

    def test_dispatcher_records_each_call(self):
        r = TraceRecorder()
        dispatcher = make_subprocess_dispatcher(r)
        dispatcher(["git", "rev-parse", "HEAD"])
        dispatcher(["git", "tag", "v1"])
        dispatcher("ruff check .", shell=True)
        assert len(r.subprocess_calls) == 3
        assert r.subprocess_calls[0].payload["head"] == "git"
        assert r.subprocess_calls[2].payload["head"] == "ruff"
        assert r.subprocess_calls[2].payload["shell"] is True

    def test_shell_string_git_command_is_recognised(self):
        """`subprocess.run("git push", shell=True)` should still be treated
        as a git command, not a gate command."""
        r = TraceRecorder()
        dispatcher = make_subprocess_dispatcher(r, gate_returncode=1)
        result = dispatcher("git push origin master", shell=True)
        assert result.returncode == 0  # git path, not the gate-fail rc


class TestRunClaudeStub:
    def test_per_call_token_variation(self):
        r = TraceRecorder()
        stub = make_run_claude_stub(r)
        results = [stub(prompt=f"p{i}") for i in range(3)]

        # Three distinct token shapes captured.
        assert results[0].raw["usage"] == TOKEN_SHAPES[0]
        assert results[1].raw["usage"] == TOKEN_SHAPES[1]
        assert results[2].raw["usage"] == TOKEN_SHAPES[2]
        # Costs from the table.
        assert results[0].cost_usd == CALL_COSTS[0]
        assert results[1].cost_usd == CALL_COSTS[1]
        assert results[2].cost_usd == CALL_COSTS[2]

    def test_session_ids_are_distinct_and_deterministic(self):
        r = TraceRecorder()
        stub = make_run_claude_stub(r)
        sessions = [stub(prompt=f"p{i}").session_id for i in range(3)]
        assert sessions == ["sess-00", "sess-01", "sess-02"]

    def test_stub_records_each_call(self):
        r = TraceRecorder()
        stub = make_run_claude_stub(r)
        stub(prompt="p0")
        stub(prompt="p1")
        assert len(r.run_claude_calls) == 2
        assert r.run_claude_calls[0].payload["cost"] == CALL_COSTS[0]
        assert r.run_claude_calls[1].payload["usage"] == TOKEN_SHAPES[1]

    def test_beyond_table_repeats_last_entry(self):
        r = TraceRecorder()
        stub = make_run_claude_stub(r)
        # 12 calls — table is length 11; calls 10-11 should reuse index 10.
        for i in range(12):
            stub(prompt=f"p{i}")
        last_shape = TOKEN_SHAPES[-1]
        last_cost = CALL_COSTS[-1]
        assert r.run_claude_calls[10].payload["usage"] == last_shape
        assert r.run_claude_calls[11].payload["usage"] == last_shape
        assert r.run_claude_calls[10].payload["cost"] == last_cost
        assert r.run_claude_calls[11].payload["cost"] == last_cost


class TestAccumulateCostWrapper:
    def test_records_delta_and_resulting_total(self):
        r = TraceRecorder()

        class FakeOrch:
            class _S:
                total_cost_usd = 0.0

            state = _S()

            def _accumulate_cost(self, local, delta):
                self.state.total_cost_usd += delta
                return local + delta

        original = FakeOrch._accumulate_cost
        wrapped = make_accumulate_cost_wrapper(r, original)
        orch = FakeOrch()
        new = wrapped(orch, 0.0, 1.50)
        assert new == 1.50
        assert orch.state.total_cost_usd == 1.50

        assert len(r.accumulate_cost_calls) == 1
        payload = r.accumulate_cost_calls[0].payload
        assert payload["delta"] == 1.5
        assert payload["new_local"] == 1.5
        assert payload["new_state_total"] == 1.5

    def test_rounds_to_six_dp(self):
        """Float noise above 6dp should not generate fixture instability."""
        r = TraceRecorder()

        class FakeOrch:
            class _S:
                total_cost_usd = 0.0

            state = _S()

            def _accumulate_cost(self, local, delta):
                self.state.total_cost_usd += delta
                return local + delta

        wrapped = make_accumulate_cost_wrapper(r, FakeOrch._accumulate_cost)
        orch = FakeOrch()
        wrapped(orch, 0.0, 1.1234567890)
        assert r.accumulate_cost_calls[0].payload["delta"] == 1.123457


class TestSaveStateRecorder:
    def test_records_path_basename_and_state_fields(self, tmp_path):
        r = TraceRecorder()

        called = []

        def original(claude_dir, state):
            called.append((claude_dir, state.current_step, state.total_cost_usd))

        wrapped = make_save_state_recorder(r, original)

        class FakeState:
            current_step = "plan"
            total_cost_usd = 1.5

        wrapped(tmp_path / ".claude", FakeState())
        assert len(r.save_state_calls) == 1
        p = r.save_state_calls[0].payload
        assert p["claude_dir"] == ".claude"
        assert p["current_step"] == "plan"
        assert p["total_cost_usd"] == 1.5
        # Original was still invoked.
        assert len(called) == 1


class TestTelemetrySubscriber:
    def test_subscriber_records_event_type_and_key_fields(self):
        r = TraceRecorder()

        class FakeEvent:
            def to_dict(self):
                return {
                    "type": "phase_completed",
                    "milestone": "M1",
                    "phase": "plan",
                    "cost_usd": 1.5,
                    "duration_ms": 1000,
                    "input_tokens": 50,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 400,
                    "cache_hit_rate": 0.7273,
                    # noise fields the recorder must ignore:
                    "timestamp": "2026-06-01T00:00:00Z",
                    "seq": 42,
                }

        emit_calls = []

        def emit_orig(ev):
            emit_calls.append(ev)

        sub = make_telemetry_subscriber(r)
        sub(emit_orig, FakeEvent())

        assert len(r.events) == 1
        payload = r.events[0].payload
        assert payload["event_type"] == "phase_completed"
        fields = payload["fields"]
        assert fields["cache_creation_input_tokens"] == 100
        assert fields["cache_read_input_tokens"] == 400
        assert fields["cache_hit_rate"] == 0.7273
        # Noise filtered out.
        assert "timestamp" not in fields
        assert "seq" not in fields
        # Original emit still ran.
        assert len(emit_calls) == 1

    def test_subscriber_records_unknown_event_with_empty_fields(self):
        """Defensive: events without registered key fields still get
        recorded so the trace doesn't silently drop them."""
        r = TraceRecorder()

        class UnknownEvent:
            def to_dict(self):
                return {"type": "future_event_type_v2", "foo": "bar"}

        sub = make_telemetry_subscriber(r)
        sub(lambda e: None, UnknownEvent())
        assert r.events[0].payload["event_type"] == "future_event_type_v2"
        assert r.events[0].payload["fields"] == {}


class TestFixtureMatching:
    def test_update_mode_requires_rationale(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        monkeypatch.setenv("GOLDEN_TRACE_UPDATE", "1")
        monkeypatch.delenv("GOLDEN_TRACE_RATIONALE", raising=False)
        with pytest.raises(RuntimeError, match="GOLDEN_TRACE_RATIONALE"):
            assert_trace_matches_fixture(r, tmp_path / "fixture.json")

    def test_update_mode_writes_fixture_and_rationale_sidecar(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        monkeypatch.setenv("GOLDEN_TRACE_UPDATE", "1")
        monkeypatch.setenv("GOLDEN_TRACE_RATIONALE", "v1.2.0-real intentional reorder")
        fixture = tmp_path / "fixture.json"
        assert_trace_matches_fixture(r, fixture)
        assert fixture.exists()
        rationale = fixture.with_suffix(".json.rationale.txt")
        assert rationale.exists()
        assert "v1.2.0-real" in rationale.read_text()

    def test_missing_fixture_raises_helpful_error(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        monkeypatch.delenv("GOLDEN_TRACE_UPDATE", raising=False)
        monkeypatch.delenv("GOLDEN_TRACE_RATIONALE", raising=False)
        with pytest.raises(AssertionError, match="GOLDEN_TRACE_UPDATE"):
            assert_trace_matches_fixture(r, tmp_path / "missing.json")

    def test_match_passes_on_deep_equal(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        # First, write a fixture in update mode.
        monkeypatch.setenv("GOLDEN_TRACE_UPDATE", "1")
        monkeypatch.setenv("GOLDEN_TRACE_RATIONALE", "initial capture")
        fixture = tmp_path / "fix.json"
        assert_trace_matches_fixture(r, fixture)
        # Now compare a fresh recorder of identical shape.
        monkeypatch.delenv("GOLDEN_TRACE_UPDATE")
        monkeypatch.delenv("GOLDEN_TRACE_RATIONALE")
        r2 = TraceRecorder()
        r2.record("event", event_type="phase_started")
        # Must not raise.
        assert_trace_matches_fixture(r2, fixture)

    def test_mismatch_surfaces_first_divergence_index(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        r.record("event", event_type="phase_completed")
        monkeypatch.setenv("GOLDEN_TRACE_UPDATE", "1")
        monkeypatch.setenv("GOLDEN_TRACE_RATIONALE", "init")
        fixture = tmp_path / "fix.json"
        assert_trace_matches_fixture(r, fixture)
        monkeypatch.delenv("GOLDEN_TRACE_UPDATE")
        monkeypatch.delenv("GOLDEN_TRACE_RATIONALE")
        r2 = TraceRecorder()
        r2.record("event", event_type="phase_started")
        r2.record("event", event_type="something_else")  # divergence at index 1
        with pytest.raises(AssertionError, match="Trace divergence at index 1"):
            assert_trace_matches_fixture(r2, fixture)

    def test_length_mismatch_surfaces_extra_or_missing(self, tmp_path, monkeypatch):
        r = TraceRecorder()
        r.record("event", event_type="phase_started")
        monkeypatch.setenv("GOLDEN_TRACE_UPDATE", "1")
        monkeypatch.setenv("GOLDEN_TRACE_RATIONALE", "init")
        fixture = tmp_path / "fix.json"
        assert_trace_matches_fixture(r, fixture)
        monkeypatch.delenv("GOLDEN_TRACE_UPDATE")
        monkeypatch.delenv("GOLDEN_TRACE_RATIONALE")
        r2 = TraceRecorder()
        r2.record("event", event_type="phase_started")
        r2.record("event", event_type="phase_completed")  # extra
        with pytest.raises(AssertionError, match="Trace length differs"):
            assert_trace_matches_fixture(r2, fixture)
