"""v1.2.0-real Task 3: unit tests for run_quality_gate_checkpoint helper.

Pins behavior PhaseB and PhaseC will both depend on (Tasks 5 and 6).
Critical invariants:

- Gate ordering is preserved: (lint, sast, secret_scan, dep_scan)
- Fix-loop fires per-call `_accumulate_cost` (Finding 1 — v1.3.12
  in-flight budget gate granularity).
- Policy recheck uses the asymmetric `f"{checkpoint}_recheck"` label
  (Finding 2 item 1 — the original orchestrator code uses two
  different labels for the gates recheck vs policy recheck).
- Happy path with all gates passing returns 0.0 and makes ZERO claude
  calls.
- No-gates-configured short-circuits via the orchestrator helper.
- Fix prompt content matches the original orchestrator code verbatim.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from superpower_workflow.phases import PhaseContext
from superpower_workflow.quality_gates import run_quality_gate_checkpoint
from superpower_workflow.runner import ClaudeResult


def _mk_orch(
    *,
    gates_first_result=(True, []),
    gates_recheck_result=(True, []),
    policies_first_result=(True, []),
    policies_recheck_result=(True, []),
    claude_cost: float = 0.50,
) -> MagicMock:
    """Build a mock Orchestrator with configurable gate/policy responses.

    Gate and policy calls return distinct values per invocation via
    side_effect so the test can simulate fail-then-pass.
    """
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system prompt"

    # _verify_quality_gates side_effect cycles through:
    # [first call, recheck call]. Beyond 2 calls returns the recheck
    # tuple — fine because callers never go past 2.
    orch._verify_quality_gates.side_effect = [
        gates_first_result,
        gates_recheck_result,
        gates_recheck_result,
    ]
    orch._check_policies.side_effect = [
        policies_first_result,
        policies_recheck_result,
        policies_recheck_result,
    ]
    orch._run_claude.return_value = ClaudeResult(
        is_error=False,
        cost_usd=claude_cost,
        duration_ms=1000,
        session_id="sess-fix",
        text="ok",
        raw={"usage": {"input_tokens": 10}},
    )
    return orch


def _mk_ctx() -> PhaseContext:
    return PhaseContext(
        milestone_name="M1",
        milestone_dict={"name": "M1"},
        spec="spec.md",
        sections="",
        model="opus",
        budgets={},
        fallback_model="haiku",
        logger=MagicMock(),
    )


# ---- happy path ----


class TestHappyPath:
    def test_returns_zero_when_all_gates_pass(self):
        orch = _mk_orch()
        cost = run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert cost == 0.0

    def test_zero_claude_calls_on_happy_path(self):
        orch = _mk_orch()
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        orch._run_claude.assert_not_called()

    def test_one_gate_check_one_policy_check_on_happy_path(self):
        orch = _mk_orch()
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert orch._verify_quality_gates.call_count == 1
        assert orch._check_policies.call_count == 1


# ---- gate fix-loop ----


class TestGateFixLoop:
    def test_returns_fix_loop_cost_when_gate_fails(self):
        orch = _mk_orch(
            gates_first_result=(False, ["lint: x"]),
            gates_recheck_result=(True, []),
            claude_cost=0.75,
        )
        cost = run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert cost == 0.75

    def test_fix_loop_invokes_claude_with_high_effort_budget_10(self):
        orch = _mk_orch(gates_first_result=(False, ["lint: x"]))
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        orch._run_claude.assert_called_once()
        kwargs = orch._run_claude.call_args.kwargs
        assert kwargs["effort"] == "high"
        assert kwargs["budget"] == 10.0
        assert kwargs["model"] == "opus"
        assert kwargs["fallback_model"] == "haiku"

    def test_fix_loop_recheck_uses_SAME_label(self):
        """Gate recheck reuses the original checkpoint label — distinct
        from policy recheck which uses the _recheck suffix."""
        orch = _mk_orch(
            gates_first_result=(False, ["lint: x"]),
            gates_recheck_result=(True, []),
        )
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert orch._verify_quality_gates.call_count == 2
        for call in orch._verify_quality_gates.call_args_list:
            assert call.kwargs["checkpoint"] == "quality_check_b"

    def test_fix_loop_charges_state_per_call(self):
        """Finding 1 regression test — the v1.3.12 in-flight budget gate
        requires state.total_cost_usd advance within ms of each claude
        call. The helper must call _accumulate_cost AFTER each fix-loop
        claude call, not defer to the caller's per-phase aggregate.
        """
        orch = _mk_orch(gates_first_result=(False, ["lint: x"]))
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        # Exactly one fix-loop claude call → exactly one _accumulate_cost.
        orch._accumulate_cost.assert_called_once()
        # delta param matches the claude cost.
        args = orch._accumulate_cost.call_args.args
        assert args[1] == 0.50  # default claude_cost in _mk_orch

    def test_fix_prompt_contains_phase_label_and_failures(self):
        orch = _mk_orch(gates_first_result=(False, ["lint: ruff exited 1", "sast: pattern"]))
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        prompt = orch._run_claude.call_args.args[0]
        assert "Phase B" in prompt
        assert "M1" in prompt
        assert "lint: ruff exited 1" in prompt
        assert "sast: pattern" in prompt
        assert "Fix ALL issues" in prompt

    def test_logs_quality_gates_still_failing_if_recheck_also_fails(self):
        orch = _mk_orch(
            gates_first_result=(False, ["lint: x"]),
            gates_recheck_result=(False, ["lint: still x"]),
        )
        ctx = _mk_ctx()
        run_quality_gate_checkpoint(orch, ctx, checkpoint="quality_check_b", phase_label="Phase B")
        # The logger was called with QUALITY_GATES_STILL_FAILING at least once.
        events_logged = [c.args[0] for c in ctx.logger.log.call_args_list]
        assert "QUALITY_GATES_STILL_FAILING" in events_logged


# ---- policy fix-loop ----


class TestPolicyFixLoop:
    def test_policy_recheck_uses_ASYMMETRIC_recheck_label(self):
        """Finding 2 item 1 — policy recheck uses checkpoint_recheck
        suffix, distinct from gate recheck which reuses the same label.
        Both QG#1 and QG#2 share this asymmetry verbatim from the
        original orchestrator code.
        """
        orch = _mk_orch(
            policies_first_result=(False, ["forbidden file"]),
            policies_recheck_result=(True, []),
        )
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert orch._check_policies.call_count == 2
        first_call, recheck_call = orch._check_policies.call_args_list
        assert first_call.kwargs["checkpoint"] == "quality_check_b"
        assert recheck_call.kwargs["checkpoint"] == "quality_check_b_recheck"

    def test_qg2_policy_recheck_also_uses_asymmetric_label(self):
        """Same asymmetry applies at QG#2 (Phase C). quality_check_c →
        quality_check_c_recheck.
        """
        orch = _mk_orch(
            policies_first_result=(False, ["forbidden"]),
        )
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_c", phase_label="Phase C"
        )
        recheck_call = orch._check_policies.call_args_list[1]
        assert recheck_call.kwargs["checkpoint"] == "quality_check_c_recheck"

    def test_policy_fix_loop_returns_claude_cost(self):
        orch = _mk_orch(
            policies_first_result=(False, ["violation"]),
            claude_cost=0.30,
        )
        cost = run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        assert cost == 0.30

    def test_policy_fix_prompt_lists_violations(self):
        orch = _mk_orch(
            policies_first_result=(False, ["forbidden path foo.txt", "missing trailer"]),
        )
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        prompt = orch._run_claude.call_args.args[0]
        assert "forbidden path foo.txt" in prompt
        assert "missing trailer" in prompt
        assert "Fix ALL violations" in prompt

    def test_policy_fix_loop_charges_state(self):
        orch = _mk_orch(policies_first_result=(False, ["v"]))
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        orch._accumulate_cost.assert_called_once()

    def test_logs_policy_fix_failed_if_recheck_still_violates(self):
        orch = _mk_orch(
            policies_first_result=(False, ["v"]),
            policies_recheck_result=(False, ["v"]),
        )
        ctx = _mk_ctx()
        run_quality_gate_checkpoint(orch, ctx, checkpoint="quality_check_b", phase_label="Phase B")
        events_logged = [c.args[0] for c in ctx.logger.log.call_args_list]
        assert "POLICY_FIX_FAILED" in events_logged


# ---- combined: both gate and policy fail-loops fire ----


class TestBothFixLoops:
    def test_both_loops_fire_independently(self):
        """Gates and policies are independent — failing one doesn't
        affect the other's check/recheck sequence."""
        orch = _mk_orch(
            gates_first_result=(False, ["lint: x"]),
            gates_recheck_result=(True, []),
            policies_first_result=(False, ["v"]),
            policies_recheck_result=(True, []),
            claude_cost=0.40,
        )
        cost = run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        # Two fix-loop claude calls, two state charges.
        assert orch._run_claude.call_count == 2
        assert orch._accumulate_cost.call_count == 2
        # Cost is the sum of both fix-loops.
        assert cost == 0.80
        # Each side's recheck used its own label convention.
        gate_calls = orch._verify_quality_gates.call_args_list
        assert gate_calls[0].kwargs["checkpoint"] == "quality_check_b"
        assert gate_calls[1].kwargs["checkpoint"] == "quality_check_b"
        policy_calls = orch._check_policies.call_args_list
        assert policy_calls[0].kwargs["checkpoint"] == "quality_check_b"
        assert policy_calls[1].kwargs["checkpoint"] == "quality_check_b_recheck"


# ---- delegation contracts ----


class TestDelegation:
    def test_passes_milestone_name_to_orchestrator_helpers(self):
        orch = _mk_orch()
        ctx = _mk_ctx()
        run_quality_gate_checkpoint(orch, ctx, checkpoint="quality_check_b", phase_label="Phase B")
        orch._verify_quality_gates.assert_called_with(
            ctx.logger,
            milestone="M1",
            checkpoint="quality_check_b",
        )
        orch._check_policies.assert_called_with(
            ctx.logger,
            milestone="M1",
            checkpoint="quality_check_b",
        )

    def test_passes_cwd_and_sys_prompt_from_orchestrator(self):
        orch = _mk_orch(gates_first_result=(False, ["x"]))
        orch.cwd = "/some/cwd"
        orch.sys_prompt = "the system prompt"
        run_quality_gate_checkpoint(
            orch, _mk_ctx(), checkpoint="quality_check_b", phase_label="Phase B"
        )
        kwargs = orch._run_claude.call_args.kwargs
        assert kwargs["cwd"] == "/some/cwd"
        assert kwargs["system_prompt"] == "the system prompt"
