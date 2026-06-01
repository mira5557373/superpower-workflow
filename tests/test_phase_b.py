"""v1.2.0-real Task 5: unit tests for PhaseB (Implement).

PhaseB is a verbatim lift of orchestrator.py:1160-1265 with QG#1
delegated to the run_quality_gate_checkpoint helper from Task 3. These
tests pin in-class invariants; the helper's own tests pin the
asymmetric checkpoint label / per-call gate accumulation behavior.

Critical invariants:
- v1.3.4 #15: primary cost charged BEFORE _check_phase_result.
- Finding 1: per-call _accumulate_cost — primary + (QG fix-loop via
  helper) + coverage.
- last_phase_session_id mutates state but does NOT save_state inline
  (matches original — next save_state happens at quality_check_b
  transition).
- PhaseCompleted emits primary cost only (qg + cov reported via
  PhaseResult.cost_usd, not via the event).
- context_summary refreshed via build_context_summary lands in extras.
- Driver pattern: ctx.update(**result.extras) sets ctx.context_summary
  for PhaseTbV / PhaseC.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.phases import PhaseB, PhaseContext
from superpower_workflow.runner import ClaudeResult


def _mk_orch(
    *,
    primary_cost: float = 2.50,
    qg_cost: float = 0.0,
    cov_cost: float = 0.30,
    primary_is_error: bool = False,
) -> MagicMock:
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system"
    orch.claude_dir = "/tmp/claude"
    orch._state_dir = "/tmp/state"
    orch.root = "/tmp/cwd"
    orch.state = MagicMock()
    orch.state.run_id = "01TESTRUN"
    orch.state.plan_commit_sha = "abc123"
    orch.state.last_phase_session_id = None
    orch.state.completed = []
    orch.config = {"milestones": [{"name": "M1"}]}

    orch._find_plan_path.return_value = "/tmp/cwd/plan.md"
    orch._run_claude.return_value = ClaudeResult(
        is_error=primary_is_error,
        cost_usd=primary_cost,
        duration_ms=2500,
        session_id="sess-B",
        text="ok",
        raw={
            "usage": {
                "input_tokens": 30,
                "output_tokens": 80,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 200,
            }
        },
    )
    orch._check_coverage.return_value = (True, cov_cost)
    orch._check_trailers.return_value = None

    if primary_is_error:
        from superpower_workflow.orchestrator import _PhaseError

        orch._check_phase_result.side_effect = _PhaseError("implement", "claude err")
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "",
        "model": "opus",
        "budgets": {"implement": 100},
        "fallback_model": "haiku",
        "effort": {"implement": "high"},
        "context_summary": "old context",
        "plan_commit_sha": "abc123",
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


@pytest.fixture(autouse=True)
def _stub_io():
    with (
        patch("superpower_workflow.state.save_state") as save_state_mock,
        patch("superpower_workflow.phases.implement.save_state", new=save_state_mock),
        patch(
            "superpower_workflow.phases.implement.build_context_summary",
            return_value="refreshed context",
        ) as build_ctx_mock,
        patch(
            "superpower_workflow.phases.implement.run_quality_gate_checkpoint",
            return_value=0.0,
        ) as qg_mock,
    ):
        yield {
            "save_state": save_state_mock,
            "build_context_summary": build_ctx_mock,
            "run_quality_gate_checkpoint": qg_mock,
        }


# ---- happy path ----


class TestHappyPath:
    def test_phase_result_shape(self, _stub_io):
        orch = _mk_orch()
        result = PhaseB(orch).run(_mk_ctx())

        assert result.phase == "implement"
        # cost = primary (2.50) + qg (0.0) + cov (0.30)
        assert result.cost_usd == 2.80
        assert result.duration_ms == 2500
        assert result.session_id == "sess-B"
        assert result.tokens["cache_creation_input_tokens"] == 50
        assert result.tokens["cache_read_input_tokens"] == 200
        assert abs(result.tokens["cache_hit_rate"] - 0.7143) < 1e-4
        assert result.events_emitted == ["PhaseStarted", "PhaseCompleted"]

    def test_context_summary_in_extras(self, _stub_io):
        """The refreshed context lands in extras so the driver's
        ctx.update(**result.extras) sets ctx.context_summary for
        PhaseTbV / PhaseC."""
        orch = _mk_orch()
        result = PhaseB(orch).run(_mk_ctx())
        assert result.extras["context_summary"] == "refreshed context"


# ---- per-call _accumulate_cost (Finding 1) ----


class TestAccumulateCostGranularity:
    def test_two_accumulate_calls_in_class(self, _stub_io):
        """Primary claude + coverage. QG cost flows via the helper's
        own internal _accumulate_cost calls (which run_quality_gate_
        checkpoint mocks out in this test — but its own tests pin the
        per-call invariant)."""
        orch = _mk_orch(primary_cost=2.0, cov_cost=0.3)
        PhaseB(orch).run(_mk_ctx())

        assert orch._accumulate_cost.call_count == 2
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [2.0, 0.3]

    def test_qg_helper_invoked_with_correct_checkpoint(self, _stub_io):
        orch = _mk_orch()
        ctx = _mk_ctx()
        PhaseB(orch).run(ctx)

        _stub_io["run_quality_gate_checkpoint"].assert_called_once()
        kwargs = _stub_io["run_quality_gate_checkpoint"].call_args.kwargs
        assert kwargs["checkpoint"] == "quality_check_b"
        assert kwargs["phase_label"] == "Phase B"

    def test_qg_fix_loop_cost_in_phase_total(self, _stub_io):
        """When the helper returns a non-zero qg_cost (fix-loop fired),
        it's added to PhaseResult.cost_usd."""
        _stub_io["run_quality_gate_checkpoint"].return_value = 0.50
        orch = _mk_orch(primary_cost=1.0, cov_cost=0.0)
        result = PhaseB(orch).run(_mk_ctx())
        assert result.cost_usd == 1.50  # 1.0 + 0.5 + 0.0


# ---- v1.3.4 #15: primary charge BEFORE _check_phase_result ----


class TestRetrySafety:
    def test_primary_charge_before_check(self, _stub_io):
        orch = _mk_orch()
        call_order: list[str] = []

        def record_accumulate(local, delta):
            call_order.append(f"_accumulate_cost({delta})")
            return local + delta

        def record_check(r, label):
            call_order.append(f"_check_phase_result({label})")

        orch._accumulate_cost.side_effect = record_accumulate
        orch._check_phase_result.side_effect = record_check

        PhaseB(orch).run(_mk_ctx())
        # Primary accumulate first, then check.
        assert call_order[0] == "_accumulate_cost(2.5)"
        check_idx = call_order.index("_check_phase_result(Phase B)")
        accumulate_idx = call_order.index("_accumulate_cost(2.5)")
        assert accumulate_idx < check_idx

    def test_primary_persists_if_check_raises(self, _stub_io):
        from superpower_workflow.orchestrator import _PhaseError

        orch = _mk_orch(primary_is_error=True)
        with pytest.raises(_PhaseError):
            PhaseB(orch).run(_mk_ctx())
        # Primary _accumulate_cost fired before the raise.
        assert orch._accumulate_cost.call_count == 1
        assert orch._accumulate_cost.call_args_list[0].args[1] == 2.50


# ---- state mutation ordering ----


class TestStateMutations:
    def test_last_phase_session_id_set_inline(self, _stub_io):
        """state.last_phase_session_id is set after the primary claude
        call. The original code does NOT call save_state immediately —
        the next save_state happens at the quality_check_b transition.
        """
        orch = _mk_orch()
        PhaseB(orch).run(_mk_ctx())
        # state.last_phase_session_id was set to the claude session.
        assert orch.state.last_phase_session_id == "sess-B"

    def test_save_state_count(self, _stub_io):
        """save_state is called exactly twice in PhaseB:
        1. After _set_current_step('implement')
        2. After setting state.current_step='quality_check_b'
        No save_state for last_phase_session_id (matches original).
        """
        orch = _mk_orch()
        PhaseB(orch).run(_mk_ctx())
        assert _stub_io["save_state"].call_count == 2

    def test_save_state_targets_state_dir(self, _stub_io):
        orch = _mk_orch()
        PhaseB(orch).run(_mk_ctx())
        for call in _stub_io["save_state"].call_args_list:
            assert call.args[0] == "/tmp/state"


# ---- delegation ----


class TestDelegation:
    def test_phase_completed_emits_primary_cost_only(self, _stub_io):
        from superpower_workflow.telemetry import PhaseCompleted

        _stub_io["run_quality_gate_checkpoint"].return_value = 0.50
        orch = _mk_orch(primary_cost=2.0, cov_cost=0.5)
        PhaseB(orch).run(_mk_ctx())

        emitted = [c.args[0] for c in orch._telemetry.emit.call_args_list]
        completed = [e for e in emitted if isinstance(e, PhaseCompleted)]
        assert len(completed) == 1
        assert completed[0].cost_usd == 2.0  # primary only

    def test_audit_uses_primary_cost(self, _stub_io):
        orch = _mk_orch(primary_cost=2.0)
        PhaseB(orch).run(_mk_ctx())
        audit_calls = orch._audit.append.call_args_list
        phase_complete = [c for c in audit_calls if c.args and c.args[0] == "PHASE_COMPLETE"]
        assert phase_complete[0].kwargs["data"]["cost"] == 2.0

    def test_post_phase_uses_primary_cost(self, _stub_io):
        orch = _mk_orch(primary_cost=2.0)
        PhaseB(orch).run(_mk_ctx())
        args, _ = orch._call_post_phase.call_args
        assert args[0] == "implement"
        assert args[2] == {"cost": 2.0}

    def test_check_coverage_invoked_after_qg(self, _stub_io):
        orch = _mk_orch()
        PhaseB(orch).run(_mk_ctx())
        orch._check_coverage.assert_called_once()

    def test_check_trailers_uses_plan_commit_sha(self, _stub_io):
        orch = _mk_orch()
        orch.state.plan_commit_sha = "ffeeddccbbaa"
        PhaseB(orch).run(_mk_ctx())
        orch._check_trailers.assert_called_once()
        assert orch._check_trailers.call_args.args[0] == "ffeeddccbbaa"

    def test_check_trailers_handles_no_plan_sha(self, _stub_io):
        orch = _mk_orch()
        orch.state.plan_commit_sha = None
        PhaseB(orch).run(_mk_ctx())
        # Falls back to "" per the original code.
        assert orch._check_trailers.call_args.args[0] == ""


# ---- context refresh ----


class TestContextRefresh:
    def test_build_context_summary_invoked_with_correct_args(self, _stub_io):
        orch = _mk_orch()
        orch.state.completed = ["M0"]
        ctx = _mk_ctx()
        PhaseB(orch).run(ctx)

        _stub_io["build_context_summary"].assert_called_once_with(
            ["M0"],
            "/tmp/cwd",
            ctx.milestone_dict,
            [{"name": "M1"}],
        )
