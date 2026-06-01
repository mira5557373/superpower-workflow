"""v1.2.0-real Task 4: unit tests for PhaseA (Plan).

PhaseA is a verbatim lift of orchestrator.py:1099-1158. These tests pin
the load-bearing invariants the v1.3.x audit findings called out:

- v1.3.4 #15: primary cost charged BEFORE _check_phase_result raises.
- v1.3.12: per-call _accumulate_cost for primary + curator (NOT a
  single per-phase aggregate at the end).
- v1.3.13 #3: state.plan_commit_sha + last_phase_session_id persist
  via save_state(self.orc._state_dir, ...), NOT self.orc.claude_dir.
- archive_reports + clear_phase_state operate on claude_dir (worker-
  local), not _state_dir.
- PhaseCompleted emits primary cost only (curator is out-of-band).
- audit + post_phase get r.cost_usd, not phase_cost.
- plan_commit_sha flows out via extras for Phase B's PhaseContext.

The golden trace from Task 1.2 still locks the full ordering at the
event level; these unit tests provide focused coverage of the in-class
invariants.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.phases import PhaseA, PhaseContext
from superpower_workflow.runner import ClaudeResult

# ---- fixtures ----


def _mk_orch(
    *,
    primary_cost: float = 1.00,
    curator_cost: float = 0.20,
    git_sha: str = "0123456789abcdef0123456789abcdef01234567",
    primary_is_error: bool = False,
) -> MagicMock:
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system prompt"
    orch.claude_dir = "/tmp/claude"
    orch._state_dir = "/tmp/state"
    orch.state = MagicMock()
    orch.state.plan_commit_sha = None
    orch.state.last_phase_session_id = None
    orch.state.run_id = "01TESTRUN"

    orch._run_claude.return_value = ClaudeResult(
        is_error=primary_is_error,
        cost_usd=primary_cost,
        duration_ms=1500,
        session_id="sess-A",
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
    orch._run_gap_curator.return_value = curator_cost
    if primary_is_error:
        from superpower_workflow.orchestrator import _PhaseError

        orch._check_phase_result.side_effect = _PhaseError("plan", "claude err")
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "1,2",
        "model": "opus",
        "budgets": {"plan": 25},
        "fallback_model": "haiku",
        "effort": {"plan": "max"},
        "convergence": {"max_iterations": 5},
        "context_summary": "context goes here",
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


# Auto-patch the file-I/O helpers (save_state at the SOURCE module so
# PhaseBase._set_current_step's deferred import also gets the stub) and
# subprocess (so git rev-parse + git tag are deterministic).
@pytest.fixture(autouse=True)
def _stub_io():
    class _Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def dispatch(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        tokens = cmd if isinstance(cmd, (list, tuple)) else cmd.split()
        if "rev-parse" in tokens:
            return _Result(stdout="0123456789abcdef0123456789abcdef01234567\n")
        # git tag, git push, etc → rc=0
        return _Result()

    # save_state is patched at the source module — PhaseBase imports it
    # deferred inside _set_current_step, so patching phases.plan.save_state
    # alone leaves the deferred import unstubbed (str paths fail mkdir).
    with (
        patch("superpower_workflow.state.save_state") as save_state_mock,
        patch("superpower_workflow.phases.plan.save_state", new=save_state_mock),
        patch("superpower_workflow.phases.plan.save_phase_state") as sps_mock,
        patch("superpower_workflow.phases.plan.archive_reports") as arch_mock,
        patch("superpower_workflow.phases.plan.clear_phase_state") as clear_mock,
        patch("superpower_workflow.phases.plan.subprocess.run", side_effect=dispatch),
    ):
        yield {
            "save_state": save_state_mock,
            "save_phase_state": sps_mock,
            "archive_reports": arch_mock,
            "clear_phase_state": clear_mock,
        }


# ---- happy path ----


class TestHappyPath:
    def test_returns_phase_result_with_expected_shape(self):
        orch = _mk_orch()
        result = PhaseA(orch).run(_mk_ctx())

        assert result.phase == "plan"
        assert result.cost_usd == 1.20  # primary + curator
        assert result.duration_ms == 1500
        assert result.session_id == "sess-A"
        assert result.error is None
        # Tokens unpack cleanly into PhaseCompleted (cache_hit_rate
        # included via extract_token_usage).
        assert result.tokens["cache_creation_input_tokens"] == 100
        assert result.tokens["cache_read_input_tokens"] == 400
        assert abs(result.tokens["cache_hit_rate"] - 0.7273) < 1e-4

    def test_plan_commit_sha_in_extras(self):
        orch = _mk_orch()
        result = PhaseA(orch).run(_mk_ctx())
        assert result.extras["plan_commit_sha"] == ("0123456789abcdef0123456789abcdef01234567")

    def test_events_emitted_order(self):
        orch = _mk_orch()
        result = PhaseA(orch).run(_mk_ctx())
        # Order matches the original orchestrator block: PhaseStarted →
        # GapReport → GapValidationEvent → PhaseCompleted.
        assert result.events_emitted == [
            "PhaseStarted",
            "GapReport",
            "GapValidationEvent",
            "PhaseCompleted",
        ]


# ---- per-call _accumulate_cost (Finding 1) ----


class TestAccumulateCostGranularity:
    def test_two_accumulate_calls_per_phase(self):
        """One for primary claude, one for curator. NOT a single
        per-phase aggregate at the end — v1.3.12 in-flight gate
        requires per-call granularity.
        """
        orch = _mk_orch(primary_cost=1.0, curator_cost=0.5)
        PhaseA(orch).run(_mk_ctx())

        # Exactly two _accumulate_cost calls.
        assert orch._accumulate_cost.call_count == 2
        # Each delta matches.
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [1.0, 0.5]

    def test_curator_cost_zero_still_charged(self):
        """When curator is disabled it returns 0.0 — the code still
        invokes _accumulate_cost (which short-circuits on delta=0).
        Test confirms the call happens so a refactor that conditionally
        skips _accumulate_cost on curator=0 is caught.
        """
        orch = _mk_orch(curator_cost=0.0)
        PhaseA(orch).run(_mk_ctx())
        assert orch._accumulate_cost.call_count == 2
        assert orch._accumulate_cost.call_args_list[1].args[1] == 0.0


# ---- v1.3.4 #15: cost in state BEFORE _check_phase_result raises ----


class TestRetrySafety:
    def test_primary_charge_happens_before_check_phase_result(self):
        """Both calls must fire in order: _accumulate_cost → ... →
        _check_phase_result. If _check_phase_result raises, primary
        cost is already in state."""
        orch = _mk_orch()
        call_order: list[str] = []

        def record_accumulate(local, delta):
            call_order.append(f"_accumulate_cost({delta})")
            return local + delta

        def record_check(r, label):
            call_order.append(f"_check_phase_result({label})")

        orch._accumulate_cost.side_effect = record_accumulate
        orch._check_phase_result.side_effect = record_check

        PhaseA(orch).run(_mk_ctx())

        # Primary charge first, then curator charge, then check.
        assert call_order[0] == "_accumulate_cost(1.0)"
        assert call_order[1] == "_accumulate_cost(0.2)"
        check_idx = call_order.index("_check_phase_result(Phase A)")
        assert check_idx == 2

    def test_primary_charge_persists_if_check_raises(self):
        """Wire _check_phase_result to raise (simulating an error
        response). Primary _accumulate_cost must have fired BEFORE
        the raise so retry sees the spent money."""
        from superpower_workflow.orchestrator import _PhaseError

        orch = _mk_orch(primary_is_error=True)
        with pytest.raises(_PhaseError):
            PhaseA(orch).run(_mk_ctx())

        # Primary cost was charged before the raise.
        assert orch._accumulate_cost.call_count == 2  # primary + curator
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas[0] == 1.00


# ---- state routing (v1.3.13 #3) ----


class TestStateRouting:
    def test_set_current_step_writes_to_state_dir(self, _stub_io):
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx())

        # save_state called at least twice: once for current_step,
        # once for plan_commit_sha + session_id. Both target _state_dir.
        for call in _stub_io["save_state"].call_args_list:
            assert call.args[0] == "/tmp/state", (
                f"save_state must target _state_dir; got {call.args[0]}"
            )

    def test_save_phase_state_targets_claude_dir(self, _stub_io):
        """save_phase_state is worker-local — uses claude_dir, NOT
        _state_dir."""
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx())

        _stub_io["save_phase_state"].assert_called_once()
        assert _stub_io["save_phase_state"].call_args.args[0] == "/tmp/claude"

    def test_archive_and_clear_target_claude_dir(self, _stub_io):
        """Reports archive/clear are worker-local artifacts."""
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx())

        assert _stub_io["archive_reports"].call_args.args[0] == "/tmp/claude"
        assert _stub_io["clear_phase_state"].call_args.args[0] == "/tmp/claude"


# ---- PhaseCompleted + audit + post_phase use r.cost_usd ----


class TestPostPhaseDelegations:
    def test_phase_completed_emits_primary_cost_only(self):
        """The PhaseCompleted event's cost_usd is r.cost_usd (primary),
        NOT primary + curator. The original orchestrator block does the
        same — curator cost is reported separately via the return value
        and via audit, not via PhaseCompleted.cost_usd.
        """
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5)
        PhaseA(orch).run(_mk_ctx())

        # Find the PhaseCompleted event in the emit calls.
        emitted = [c.args[0] for c in orch._telemetry.emit.call_args_list]
        completed = [e for e in emitted if isinstance(e, PhaseCompleted)]
        assert len(completed) == 1
        assert completed[0].cost_usd == 2.0  # primary only

    def test_audit_complete_called_with_primary_cost(self):
        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5)
        PhaseA(orch).run(_mk_ctx())
        # _audit.append → PHASE_COMPLETE with data["cost"] == round(2.0, 2)
        audit_calls = orch._audit.append.call_args_list
        phase_complete = [c for c in audit_calls if c.args and c.args[0] == "PHASE_COMPLETE"]
        assert len(phase_complete) == 1
        assert phase_complete[0].kwargs["data"]["cost"] == 2.0

    def test_call_post_phase_with_primary_cost(self):
        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5)
        PhaseA(orch).run(_mk_ctx())

        orch._call_post_phase.assert_called_once()
        args, _ = orch._call_post_phase.call_args
        # ("plan", milestone_dict, {"cost": 2.0})
        assert args[0] == "plan"
        assert args[1] == {"name": "M1"}
        assert args[2] == {"cost": 2.0}


# ---- claude call parameters ----


class TestClaudeInvocation:
    def test_run_claude_uses_phase_a_prompt_and_effort_max(self):
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx(effort={"plan": "max"}))
        kwargs = orch._run_claude.call_args.kwargs
        assert kwargs["model"] == "opus"
        assert kwargs["fallback_model"] == "haiku"
        assert kwargs["effort"] == "max"
        assert kwargs["budget"] == 25
        assert kwargs["cwd"] == "/tmp/cwd"

    def test_effort_falls_back_when_plan_unspecified(self):
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx(effort={}))
        assert orch._run_claude.call_args.kwargs["effort"] == "max"

    def test_budget_falls_back_to_default(self):
        orch = _mk_orch()
        PhaseA(orch).run(_mk_ctx(budgets={}))
        assert orch._run_claude.call_args.kwargs["budget"] == 25
