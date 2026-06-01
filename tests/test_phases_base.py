"""v1.2.0-real Task 2: unit tests for PhaseBase + PhaseContext + PhaseResult.

These tests pin the contract before any concrete Phase class lands
(Tasks 4-7). If a subsequent refactor weakens the abstract base or
removes the extras-drift guard, these tests fail loudly — before any
phase implementation depends on the loosened invariant.

Covers:
- PhaseContext frozen-ness (assignment fails)
- PhaseContext.update(**kwargs) returns a new instance
- PhaseContext.update with unknown key raises TypeError (Finding 3 fix)
- PhaseResult shape and defaults
- PhaseBase cannot be instantiated without implementing run()
- PhaseBase ClassVar contract (name, log_event_start, log_event_complete)
- Shared helpers delegate to the right orchestrator methods
- Error protocol: PluginVetoError → _PhaseError translation
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from superpower_workflow.phases import PhaseBase, PhaseContext, PhaseResult
from superpower_workflow.runner import ClaudeResult

# ---- PhaseContext ----


class TestPhaseContextFrozen:
    def test_required_fields_construct(self):
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={"name": "M1"},
            spec="spec.md",
            sections="",
            model="opus",
            budgets={"plan": 25},
        )
        assert ctx.milestone_name == "M1"
        assert ctx.model == "opus"
        # Defaults fill in.
        assert ctx.fallback_model is None
        assert ctx.accumulated_cost == 0.0
        assert ctx.compliance_report is None

    def test_assignment_raises_frozen(self):
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        with pytest.raises(FrozenInstanceError):
            ctx.milestone_name = "M2"
        with pytest.raises(FrozenInstanceError):
            ctx.accumulated_cost = 5.0

    def test_dict_field_defaults_are_per_instance(self):
        """field(default_factory=dict) avoids the classic shared-mutable-default trap."""
        a = PhaseContext(
            milestone_name="a",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        b = PhaseContext(
            milestone_name="b",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        assert a.effort is not b.effort, "default dict fields must not be shared"


class TestPhaseContextUpdate:
    def test_update_returns_new_instance(self):
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        new_ctx = ctx.update(accumulated_cost=5.0)
        assert new_ctx is not ctx
        assert ctx.accumulated_cost == 0.0  # original unchanged
        assert new_ctx.accumulated_cost == 5.0
        # Identity fields preserved.
        assert new_ctx.milestone_name == "M1"

    def test_update_with_multiple_fields(self):
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        new_ctx = ctx.update(
            accumulated_cost=10.0,
            plan_commit_sha="abc123",
            compliance_report={"missing": []},
        )
        assert new_ctx.accumulated_cost == 10.0
        assert new_ctx.plan_commit_sha == "abc123"
        assert new_ctx.compliance_report == {"missing": []}

    def test_update_with_unknown_key_raises_typeerror(self):
        """Extras-drift guard (Finding 3 fix).

        A phase that adds a key to PhaseResult.extras without first
        adding the matching field to PhaseContext gets a TypeError
        instead of silently dropping the value.
        """
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        with pytest.raises(TypeError):
            ctx.update(this_field_does_not_exist="oops")

    def test_update_extras_splat_pattern(self):
        """The driver calls `ctx = ctx.update(**result.extras)` after
        each phase. Unknown keys in extras must raise.
        """
        ctx = PhaseContext(
            milestone_name="M1",
            milestone_dict={},
            spec="s",
            sections="",
            model="opus",
            budgets={},
        )
        valid_extras = {"plan_commit_sha": "abc"}
        new_ctx = ctx.update(**valid_extras)
        assert new_ctx.plan_commit_sha == "abc"

        bad_extras = {"compliance_report": {"x": 1}, "phase_x_output": "rogue"}
        with pytest.raises(TypeError):
            ctx.update(**bad_extras)


# ---- PhaseResult ----


class TestPhaseResult:
    def test_construct_with_required_fields(self):
        r = PhaseResult(
            phase="plan",
            cost_usd=1.5,
            duration_ms=1000,
            session_id="sess-00",
            tokens={
                "input_tokens": 50,
                "output_tokens": 200,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 400,
                "cache_hit_rate": 0.7273,
            },
            events_emitted=["PhaseStarted", "PhaseCompleted"],
        )
        assert r.phase == "plan"
        assert r.error is None
        assert r.extras == {}

    def test_extras_is_per_instance_dict(self):
        a = PhaseResult(
            phase="a",
            cost_usd=0,
            duration_ms=0,
            session_id="",
            tokens={},
            events_emitted=[],
        )
        b = PhaseResult(
            phase="b",
            cost_usd=0,
            duration_ms=0,
            session_id="",
            tokens={},
            events_emitted=[],
        )
        a.extras["foo"] = "bar"
        assert b.extras == {}, "default_factory=dict must give per-instance dicts"


# ---- PhaseBase ----


class TestPhaseBaseAbstract:
    def test_cannot_instantiate_without_run_method(self):
        class IncompletePhase(PhaseBase):
            name = "incomplete"
            log_event_start = "X_START"
            log_event_complete = "X_DONE"
            # Missing run() — abstract.

        with pytest.raises(TypeError, match="abstract"):
            IncompletePhase(orchestrator=MagicMock())

    def test_subclass_with_run_method_instantiates(self):
        class GoodPhase(PhaseBase):
            name = "good"
            log_event_start = "G_START"
            log_event_complete = "G_DONE"

            def run(self, ctx):
                return PhaseResult(
                    phase=self.name,
                    cost_usd=0,
                    duration_ms=0,
                    session_id="",
                    tokens={},
                    events_emitted=[],
                )

        orch = MagicMock()
        phase = GoodPhase(orchestrator=orch)
        assert phase.orc is orch
        assert phase.name == "good"


class _StubPhase(PhaseBase):
    """Concrete PhaseBase subclass for helper-delegation tests."""

    name = "stub"
    log_event_start = "STUB_START"
    log_event_complete = "STUB_DONE"

    def run(self, ctx):  # pragma: no cover — not exercised
        return PhaseResult(
            phase=self.name,
            cost_usd=0,
            duration_ms=0,
            session_id="",
            tokens={},
            events_emitted=[],
        )


def _mk_ctx() -> PhaseContext:
    return PhaseContext(
        milestone_name="M1",
        milestone_dict={"name": "M1"},
        spec="s",
        sections="",
        model="opus",
        budgets={},
    )


class TestPhaseBaseHelpers:
    def test_emit_phase_started_delegates_to_telemetry(self):
        from superpower_workflow.telemetry import PhaseStarted

        orch = MagicMock()
        phase = _StubPhase(orch)
        phase._emit_phase_started(_mk_ctx())

        orch._telemetry.emit.assert_called_once()
        evt = orch._telemetry.emit.call_args.args[0]
        assert isinstance(evt, PhaseStarted)
        assert evt.milestone == "M1"
        assert evt.phase == "stub"

    def test_emit_phase_completed_unpacks_tokens(self):
        from superpower_workflow.telemetry import PhaseCompleted

        orch = MagicMock()
        phase = _StubPhase(orch)
        r = ClaudeResult(
            is_error=False,
            cost_usd=1.5,
            duration_ms=2000,
            session_id="sess-00",
            text="ok",
            raw={
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 400,
                }
            },
        )
        phase._emit_phase_completed(_mk_ctx(), r)

        orch._telemetry.emit.assert_called_once()
        evt = orch._telemetry.emit.call_args.args[0]
        assert isinstance(evt, PhaseCompleted)
        assert evt.cost_usd == 1.5
        assert evt.input_tokens == 50
        assert evt.cache_creation_input_tokens == 100
        assert evt.cache_read_input_tokens == 400
        assert abs(evt.cache_hit_rate - 0.7273) < 1e-4

    def test_emit_phase_completed_adds_extra_cost(self):
        """When the phase made fix-loop / curator calls in addition to
        the primary claude call, extra_cost flows into the emitted
        event's cost_usd."""
        from superpower_workflow.telemetry import PhaseCompleted

        orch = MagicMock()
        phase = _StubPhase(orch)
        r = ClaudeResult(
            is_error=False,
            cost_usd=1.0,
            duration_ms=1000,
            session_id="sess-00",
            text="ok",
            raw={"usage": {}},
        )
        phase._emit_phase_completed(_mk_ctx(), r, extra_cost=0.50)

        evt = orch._telemetry.emit.call_args.args[0]
        assert isinstance(evt, PhaseCompleted)
        assert evt.cost_usd == 1.50  # primary + extra

    def test_audit_complete_appends_phase_complete_entry(self):
        orch = MagicMock()
        orch.state.run_id = "01TESTRUN"
        phase = _StubPhase(orch)
        phase._audit_complete(_mk_ctx(), cost=2.345)

        orch._audit.append.assert_called_once()
        args, kwargs = orch._audit.append.call_args
        assert args[0] == "PHASE_COMPLETE"
        assert kwargs["run_id"] == "01TESTRUN"
        assert kwargs["milestone"] == "M1"
        assert kwargs["data"]["phase"] == "stub"
        # Cost is rounded to 2 dp in the audit entry.
        assert kwargs["data"]["cost"] == 2.35

    def test_set_current_step_persists_to_state_dir(self, monkeypatch):
        """_set_current_step must save to self.orc._state_dir, NOT
        self.orc.claude_dir (preserves v1.3.13 #3 parent-state routing)."""

        orch = MagicMock()
        orch._state_dir = "/parent/.claude"
        orch.claude_dir = "/worker/.claude"

        captured = []

        def fake_save_state(claude_dir, state):
            captured.append((claude_dir, getattr(state, "current_step", None)))

        # Patch the symbol used inside base.py's local import. base.py
        # does a deferred `from superpower_workflow.state import save_state`
        # inside the method so we patch the source module.
        monkeypatch.setattr("superpower_workflow.state.save_state", fake_save_state)

        phase = _StubPhase(orch)
        phase._set_current_step(_mk_ctx(), "plan")

        # save_state must have been called against the parent state_dir.
        assert len(captured) == 1
        assert captured[0][0] == "/parent/.claude"
        assert captured[0][1] == "plan"

    def test_call_pre_phase_translates_plugin_veto(self):
        from superpower_workflow.orchestrator import _PhaseError
        from superpower_workflow.plugins.interface import PluginVetoError

        orch = MagicMock()
        orch._call_pre_phase.side_effect = PluginVetoError("plugin says no")

        phase = _StubPhase(orch)
        with pytest.raises(_PhaseError) as ei:
            phase._call_pre_phase(_mk_ctx())
        assert ei.value.phase == "stub"
        assert "plugin says no" in str(ei.value)

    def test_call_pre_phase_passes_milestone_dict(self):
        orch = MagicMock()
        phase = _StubPhase(orch)
        ctx = _mk_ctx()
        phase._call_pre_phase(ctx)
        orch._call_pre_phase.assert_called_once_with("stub", ctx.milestone_dict)

    def test_call_post_phase_passes_cost_dict(self):
        orch = MagicMock()
        phase = _StubPhase(orch)
        ctx = _mk_ctx()
        phase._call_post_phase(ctx, cost=3.14)
        orch._call_post_phase.assert_called_once_with("stub", ctx.milestone_dict, {"cost": 3.14})
