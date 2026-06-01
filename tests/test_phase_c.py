"""v1.2.0-real Task 6: unit tests for PhaseC (Review).

PhaseC is a verbatim lift of orchestrator.py:1275-1402. The
extraction design was validated by a 3-agent workflow; an adversarial
test-coverage verifier surfaced a HIGH coverage gap which is closed
by the last 2 test classes below (TestStrictModeMultiIteration +
TestStrictModeRetrySafety).

Critical invariants:
- v1.3.4 #15: primary + curator cost charged BEFORE _check_phase_result.
- Finding 1: 6 per-call _accumulate_cost sites (primary, curator, QG
  gate fix, QG policy fix, coverage, strict aggregate).
- PRIMARY r preserved through all "primary cost only" emissions.
- _run_strict_mode_loop invoked UNCONDITIONALLY; helper gates the
  no-op internally.
- Strict loop costs aggregate inside the loop via raw +=; PhaseC
  accumulates only the aggregate at the boundary. Mid-iteration
  crashes drop partial cost — preserved verbatim from original.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.phases import PhaseC, PhaseContext
from superpower_workflow.runner import ClaudeResult


def _mk_orch(
    *,
    primary_cost: float = 1.50,
    curator_cost: float = 0.30,
    qg_cost: float = 0.0,
    cov_cost: float = 0.40,
    strict_cost: float = 0.0,
    primary_is_error: bool = False,
) -> MagicMock:
    orch = MagicMock()
    orch.cwd = "/tmp/cwd"
    orch.sys_prompt = "system"
    orch.claude_dir = "/tmp/claude"
    orch._state_dir = "/tmp/state"
    orch.state = MagicMock()
    orch.state.run_id = "01TESTRUN"
    orch.state.plan_commit_sha = "abc123"

    orch._run_claude.return_value = ClaudeResult(
        is_error=primary_is_error,
        cost_usd=primary_cost,
        duration_ms=2000,
        session_id="sess-C",
        text="ok",
        raw={
            "usage": {
                "input_tokens": 60,
                "output_tokens": 250,
                "cache_creation_input_tokens": 120,
                "cache_read_input_tokens": 480,
            }
        },
    )
    orch._run_gap_curator.return_value = curator_cost
    orch._check_coverage.return_value = (True, cov_cost)
    orch._check_trailers.return_value = None
    orch._run_strict_mode_loop.return_value = strict_cost

    if primary_is_error:
        from superpower_workflow.orchestrator import _PhaseError

        orch._check_phase_result.side_effect = _PhaseError("review", "claude err")
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "",
        "model": "opus",
        "budgets": {"review": 40},
        "fallback_model": "haiku",
        "effort": {"review": "max"},
        "verify": {"test": "pytest", "lint": "ruff check ."},
        "convergence": {"max_iterations": 5},
        "validation": {},
        "context_summary": "context",
        "plan_commit_sha": "abc123",
        "compliance_report": None,
        "verification_report": None,
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


@pytest.fixture(autouse=True)
def _stub_io():
    with (
        patch("superpower_workflow.state.save_state") as save_state_mock,
        patch("superpower_workflow.phases.review.save_state", new=save_state_mock),
        patch("superpower_workflow.phases.review.save_phase_state") as sps_mock,
        patch("superpower_workflow.phases.review.archive_reports") as arch_mock,
        patch("superpower_workflow.phases.review.clear_phase_state") as clear_mock,
        patch(
            "superpower_workflow.phases.review.run_quality_gate_checkpoint",
            return_value=0.0,
        ) as qg_mock,
    ):
        yield {
            "save_state": save_state_mock,
            "save_phase_state": sps_mock,
            "archive_reports": arch_mock,
            "clear_phase_state": clear_mock,
            "run_quality_gate_checkpoint": qg_mock,
        }


# ---- happy path ----


class TestHappyPath:
    def test_phase_result_shape(self, _stub_io):
        orch = _mk_orch()
        result = PhaseC(orch).run(_mk_ctx())

        assert result.phase == "review"
        # cost = primary (1.5) + curator (0.3) + qg (0) + cov (0.4) + strict (0)
        assert result.cost_usd == 2.20
        assert result.duration_ms == 2000
        assert result.session_id == "sess-C"
        assert result.tokens["cache_creation_input_tokens"] == 120
        assert result.tokens["cache_read_input_tokens"] == 480
        # 480/(60+120+480) = 0.7273
        assert abs(result.tokens["cache_hit_rate"] - 0.7273) < 1e-4
        assert result.extras == {}

    def test_events_in_order(self, _stub_io):
        orch = _mk_orch()
        result = PhaseC(orch).run(_mk_ctx())
        # Matches Phase A pattern (NOT Phase B): GapReport +
        # GapValidationEvent fire BEFORE PhaseCompleted.
        assert result.events_emitted == [
            "PhaseStarted",
            "GapReport",
            "GapValidationEvent",
            "PhaseCompleted",
        ]


# ---- six _accumulate_cost sites (Finding 1) ----


class TestAccumulateCostSites:
    def test_four_accumulate_calls_in_class(self, _stub_io):
        """PhaseC calls _accumulate_cost 4 times directly: primary,
        curator, coverage, strict. QG fix-loop costs (sites 3 + 4)
        fire INSIDE run_quality_gate_checkpoint which is mocked here.
        """
        orch = _mk_orch(
            primary_cost=1.0,
            curator_cost=0.2,
            cov_cost=0.4,
            strict_cost=0.5,
        )
        PhaseC(orch).run(_mk_ctx())

        assert orch._accumulate_cost.call_count == 4
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        # Order: primary → curator → coverage → strict
        assert deltas == [1.0, 0.2, 0.4, 0.5]

    def test_qg_helper_called_with_quality_check_c(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        _stub_io["run_quality_gate_checkpoint"].assert_called_once()
        kwargs = _stub_io["run_quality_gate_checkpoint"].call_args.kwargs
        assert kwargs["checkpoint"] == "quality_check_c"
        assert kwargs["phase_label"] == "Phase C"

    def test_phase_total_sums_all_six_sources(self, _stub_io):
        _stub_io["run_quality_gate_checkpoint"].return_value = 0.6
        orch = _mk_orch(
            primary_cost=2.0,
            curator_cost=0.5,
            cov_cost=0.3,
            strict_cost=0.4,
        )
        # Helper returns 0.6 (qg+policy fix combined).
        result = PhaseC(orch).run(_mk_ctx())
        # primary + curator + qg + cov + strict = 2.0 + 0.5 + 0.6 + 0.3 + 0.4
        assert result.cost_usd == 3.8


# ---- v1.3.4 #15: cost charged BEFORE _check_phase_result ----


class TestRetrySafety:
    def test_primary_and_curator_before_check(self, _stub_io):
        orch = _mk_orch()
        call_order: list[str] = []

        def record_accumulate(local, delta):
            call_order.append(f"_accumulate_cost({delta})")
            return local + delta

        def record_check(r, label):
            call_order.append(f"_check_phase_result({label})")

        orch._accumulate_cost.side_effect = record_accumulate
        orch._check_phase_result.side_effect = record_check

        PhaseC(orch).run(_mk_ctx())
        # Primary first, then curator, then check.
        assert call_order[0] == "_accumulate_cost(1.5)"
        assert call_order[1] == "_accumulate_cost(0.3)"
        check_idx = call_order.index("_check_phase_result(Phase C)")
        assert check_idx == 2

    def test_primary_and_curator_persist_if_check_raises(self, _stub_io):
        from superpower_workflow.orchestrator import _PhaseError

        orch = _mk_orch(primary_is_error=True)
        with pytest.raises(_PhaseError):
            PhaseC(orch).run(_mk_ctx())
        # Both primary and curator fired before the raise.
        assert orch._accumulate_cost.call_count == 2
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [1.50, 0.30]


# ---- state routing ----


class TestStateRouting:
    def test_save_state_targets_state_dir_count_two(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        # 2 explicit save_state calls: _set_current_step('review') +
        # current_step = 'quality_check_c'. _accumulate_cost may
        # internally save_state but that's the orchestrator's helper —
        # the mock counts only direct invocations.
        assert _stub_io["save_state"].call_count == 2
        for call in _stub_io["save_state"].call_args_list:
            assert call.args[0] == "/tmp/state"

    def test_save_phase_state_archive_clear_target_claude_dir(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        assert _stub_io["save_phase_state"].call_args.args[0] == "/tmp/claude"
        assert _stub_io["archive_reports"].call_args.args[0] == "/tmp/claude"
        assert _stub_io["clear_phase_state"].call_args.args[0] == "/tmp/claude"


# ---- primary-cost-only emissions ----


class TestPrimaryCostOnlyEmissions:
    def test_phase_completed_uses_primary(self, _stub_io):
        from superpower_workflow.telemetry import PhaseCompleted

        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5, cov_cost=0.3, strict_cost=1.0)
        _stub_io["run_quality_gate_checkpoint"].return_value = 0.4
        PhaseC(orch).run(_mk_ctx())

        emitted = [c.args[0] for c in orch._telemetry.emit.call_args_list]
        completed = [e for e in emitted if isinstance(e, PhaseCompleted)]
        assert len(completed) == 1
        # PhaseCompleted.cost_usd = primary ONLY (2.0), NOT phase total (4.2).
        assert completed[0].cost_usd == 2.0

    def test_audit_uses_primary(self, _stub_io):
        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5)
        PhaseC(orch).run(_mk_ctx())
        audit_calls = orch._audit.append.call_args_list
        phase_complete = [c for c in audit_calls if c.args and c.args[0] == "PHASE_COMPLETE"]
        assert phase_complete[0].kwargs["data"]["cost"] == 2.0

    def test_post_phase_uses_primary(self, _stub_io):
        orch = _mk_orch(primary_cost=2.0, curator_cost=0.5)
        PhaseC(orch).run(_mk_ctx())
        args, _ = orch._call_post_phase.call_args
        assert args[0] == "review"
        assert args[2] == {"cost": 2.0}


# ---- strict-mode invocation ----


class TestStrictModeInvocation:
    def test_strict_mode_called_unconditionally(self, _stub_io):
        """Even when validation.strict_mode is missing/False, PhaseC
        invokes the loop. Gating lives inside the helper."""
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx(validation={}))
        orch._run_strict_mode_loop.assert_called_once()

    def test_strict_mode_receives_initial_reports_from_ctx(self, _stub_io):
        """The compliance_report + verification_report that PhaseTbV
        populated in ctx flow to _run_strict_mode_loop."""
        orch = _mk_orch()
        # phase_c_prompt expects `missing` and `broken` as int counts
        # (it does `> 0` comparisons), so the report shape mirrors the
        # real _run_spec_compliance / _run_feature_verification output.
        compliance = {"missing": 1, "details": [{"status": "missing", "desc": "req-3"}]}
        verification = {"broken": 1, "details": [{"status": "broken", "test": "test-X"}]}
        PhaseC(orch).run(
            _mk_ctx(
                compliance_report=compliance,
                verification_report=verification,
            )
        )
        kwargs = orch._run_strict_mode_loop.call_args.kwargs
        assert kwargs["initial_compliance"] is compliance
        assert kwargs["initial_verification"] is verification

    def test_strict_mode_kwargs_thread_through(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        kwargs = orch._run_strict_mode_loop.call_args.kwargs
        assert kwargs["name"] == "M1"
        assert kwargs["ms"] == {"name": "M1"}
        assert kwargs["model"] == "opus"
        assert kwargs["fallback"] == "haiku"


# ---- coverage-gap closures from the adversarial verifier ----


class TestStrictModeMultiIteration:
    """Closes verdict gap 1: 'INV-1 only tests N=1 strict iteration. A
    regression that calls _accumulate_cost per iteration would pass
    INV-1 trivially yet fail at N>=2.'

    Pin: PhaseC's ACC #6 fires EXACTLY ONCE regardless of strict-
    iteration count, with delta equal to the aggregate total_cost
    returned by _run_strict_mode_loop.
    """

    def test_strict_aggregate_is_single_accumulate_call(self, _stub_io):
        """Simulate 5 strict iterations each costing 0.20 — the loop's
        internal raw += accumulates to 1.0 and returns once. PhaseC
        must accumulate this single aggregate, NOT 5 separate calls.
        """
        orch = _mk_orch(strict_cost=1.0)  # 5 × 0.20 aggregated by helper
        PhaseC(orch).run(_mk_ctx())

        # PhaseC's direct _accumulate_cost calls: primary, curator, cov,
        # strict. Strict must be exactly 1 call with delta == aggregate.
        strict_calls = [c for c in orch._accumulate_cost.call_args_list if c.args[1] == 1.0]
        assert len(strict_calls) == 1, (
            f"Expected exactly 1 _accumulate_cost call with strict aggregate; "
            f"got {len(strict_calls)}. A regression that accumulates per "
            f"strict iteration would create N calls."
        )

    def test_strict_zero_aggregate_still_accumulates(self, _stub_io):
        """Strict disabled returns 0.0 — _accumulate_cost(0.0) is
        still invoked. A refactor that conditionally skips on cost=0
        is caught here.
        """
        orch = _mk_orch(strict_cost=0.0)
        PhaseC(orch).run(_mk_ctx())
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        # Last delta is 0.0 from the strict aggregate.
        assert deltas[-1] == 0.0


class TestStrictModeRetrySafety:
    """Closes verdict gap 2: 'a retry-safety boundary invariant for
    mid-strict-loop crashes. Force _run_strict_mode_loop to raise.
    Assert state.total_cost_usd does NOT include any strict cost.'

    Pin: v1.3.4 #15 retry-safety only holds at the strict-loop
    BOUNDARY — preserved verbatim from the original. A mid-iteration
    raise drops partial cost. This is INTENTIONAL behavior, not a bug
    — the test pins it so a future refactor that 'fixes' the partial
    drop is caught (the fix would be a behavior change requiring
    explicit opt-in, not a silent improvement).
    """

    def test_strict_loop_raise_does_not_charge_partial(self, _stub_io):
        """Wire _run_strict_mode_loop to raise mid-loop. State should
        carry primary + curator + coverage but NOT any strict cost.
        """
        orch = _mk_orch(strict_cost=0.0)
        # Simulate a raise — partial total_cost inside the loop is lost.
        orch._run_strict_mode_loop.side_effect = RuntimeError("crash mid-iter")

        with pytest.raises(RuntimeError, match="crash mid-iter"):
            PhaseC(orch).run(_mk_ctx())

        # _accumulate_cost was called for primary (1.5), curator (0.3),
        # coverage (0.4) — but the strict ACC never fired because the
        # raise happened during _run_strict_mode_loop, before line 17's
        # _accumulate_cost(0, strict_cost).
        assert orch._accumulate_cost.call_count == 3
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [1.5, 0.3, 0.4]

    def test_strict_loop_completion_charges_aggregate(self, _stub_io):
        """Counter-test: when the loop completes normally with a
        non-zero return, PhaseC's ACC #6 fires once with the aggregate."""
        orch = _mk_orch(strict_cost=0.75)
        PhaseC(orch).run(_mk_ctx())
        assert orch._accumulate_cost.call_count == 4
        assert orch._accumulate_cost.call_args_list[-1].args[1] == 0.75


# ---- pre-phase / pre-commit error protocol ----


class TestErrorProtocol:
    def test_plugin_veto_translates_to_phase_error(self, _stub_io):
        from superpower_workflow.orchestrator import _PhaseError
        from superpower_workflow.plugins.interface import PluginVetoError

        orch = _mk_orch()
        orch._call_pre_phase.side_effect = PluginVetoError("plugin blocked")
        with pytest.raises(_PhaseError) as ei:
            PhaseC(orch).run(_mk_ctx())
        assert ei.value.phase == "review"


# ---- delegation ----


class TestDelegation:
    def test_check_coverage_invoked_with_milestone(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        orch._check_coverage.assert_called_once()
        # Positional logger + kwarg milestone.
        assert orch._check_coverage.call_args.kwargs["milestone"] == "M1"

    def test_check_trailers_uses_plan_commit_sha(self, _stub_io):
        orch = _mk_orch()
        orch.state.plan_commit_sha = "deadbeef"
        PhaseC(orch).run(_mk_ctx())
        orch._check_trailers.assert_called_once()
        assert orch._check_trailers.call_args.args[0] == "deadbeef"

    def test_check_trailers_falls_back_to_empty_sha(self, _stub_io):
        orch = _mk_orch()
        orch.state.plan_commit_sha = None
        PhaseC(orch).run(_mk_ctx())
        assert orch._check_trailers.call_args.args[0] == ""

    def test_gap_curator_called_with_review_label(self, _stub_io):
        orch = _mk_orch()
        PhaseC(orch).run(_mk_ctx())
        orch._run_gap_curator.assert_called_once_with("M1", "review")
