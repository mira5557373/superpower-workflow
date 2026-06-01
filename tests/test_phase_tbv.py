"""v1.2.0-real Task 5: unit tests for PhaseTbV (trust-but-verify).

PhaseTbV is the new phase introduced by Finding 3 resolution. It owns
the spec_compliance + feature_verification stages that previously sat
ad-hoc between Phase B and Phase C in _run_milestone (orchestrator.py:
1267-1273).

Critical invariants:
- Finding 1: per-call _accumulate_cost — once per claude-emitting
  stage, even when cost is 0.0 (so a refactor that conditionally
  skips _accumulate_cost on delta=0 is caught).
- extras carry compliance_report + verification_report, possibly None
  — PhaseContext accepts both (typed dict | None).
- No PhaseStarted/PhaseCompleted from PhaseTbV — typed stage events
  emit inside the helpers.
- duration_ms = 0 and session_id = "" (no primary claude call).
- tokens dict is zero-shaped (matches extract_token_usage(None) keys).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from superpower_workflow.phases import PhaseContext, PhaseTbV


def _mk_orch(
    *,
    compliance_report=None,
    compliance_cost: float = 0.0,
    verification_report=None,
    verify_cost: float = 0.0,
) -> MagicMock:
    orch = MagicMock()
    orch.state = MagicMock()
    orch.state.run_id = "01TESTRUN"
    orch._run_spec_compliance.return_value = (compliance_report, compliance_cost)
    orch._run_feature_verification.return_value = (verification_report, verify_cost)
    return orch


def _mk_ctx(**overrides) -> PhaseContext:
    defaults = {
        "milestone_name": "M1",
        "milestone_dict": {"name": "M1"},
        "spec": "spec.md",
        "sections": "",
        "model": "opus",
        "budgets": {},
        "fallback_model": "haiku",
        "logger": MagicMock(),
    }
    defaults.update(overrides)
    return PhaseContext(**defaults)


# ---- validation disabled (default) ----


class TestNoOpPathWhenValidationDisabled:
    def test_returns_zero_cost_with_none_reports(self):
        orch = _mk_orch()
        result = PhaseTbV(orch).run(_mk_ctx())

        assert result.phase == "trust_but_verify"
        assert result.cost_usd == 0.0
        assert result.duration_ms == 0
        assert result.session_id == ""
        assert result.extras["compliance_report"] is None
        assert result.extras["verification_report"] is None
        # No stage events fired (both stages short-circuited).
        assert result.events_emitted == []

    def test_zero_token_shape(self):
        """Even on the no-op path, tokens dict has the 5 expected keys
        with zero values — downstream consumers (PhaseCompleted unpack
        via **tokens) don't need to special-case PhaseTbV."""
        orch = _mk_orch()
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.tokens == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_hit_rate": 0.0,
        }

    def test_extras_propagate_through_phasecontext_update(self):
        """The driver pattern is ctx.update(**result.extras). When
        extras={"compliance_report": None, "verification_report": None},
        PhaseContext.update accepts both (typed dict | None) and the
        updated context carries through to PhaseC."""
        orch = _mk_orch()
        ctx = _mk_ctx()
        result = PhaseTbV(orch).run(ctx)
        new_ctx = ctx.update(**result.extras)
        assert new_ctx.compliance_report is None
        assert new_ctx.verification_report is None

    def test_per_call_accumulate_cost_even_on_zero_delta(self):
        """Finding 1: _accumulate_cost is invoked once per stage even
        when delta=0. A refactor that conditionally skips on cost=0
        is caught by this test."""
        orch = _mk_orch()
        PhaseTbV(orch).run(_mk_ctx())
        # Two calls — one per stage.
        assert orch._accumulate_cost.call_count == 2
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [0.0, 0.0]


# ---- validation enabled ----


class TestComplianceEnabled:
    def test_compliance_report_in_extras(self):
        orch = _mk_orch(
            compliance_report={"missing": ["req-3"]},
            compliance_cost=0.75,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.extras["compliance_report"] == {"missing": ["req-3"]}
        assert result.extras["verification_report"] is None

    def test_compliance_cost_in_total(self):
        orch = _mk_orch(
            compliance_report={"missing": []},
            compliance_cost=0.75,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.cost_usd == 0.75

    def test_spec_compliance_completed_event_when_cost_nonzero(self):
        orch = _mk_orch(
            compliance_report={"missing": []},
            compliance_cost=0.50,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert "SpecComplianceCompleted" in result.events_emitted

    def test_no_compliance_event_when_cost_zero(self):
        """When compliance is disabled (cost=0), no event."""
        orch = _mk_orch()
        result = PhaseTbV(orch).run(_mk_ctx())
        assert "SpecComplianceCompleted" not in result.events_emitted


class TestVerificationEnabled:
    def test_verification_report_in_extras(self):
        orch = _mk_orch(
            verification_report={"broken": ["test-X"]},
            verify_cost=0.40,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.extras["verification_report"] == {"broken": ["test-X"]}
        assert result.extras["compliance_report"] is None

    def test_verify_cost_in_total(self):
        orch = _mk_orch(
            verification_report={"broken": []},
            verify_cost=0.40,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.cost_usd == 0.40

    def test_feature_verification_completed_event_when_cost_nonzero(self):
        orch = _mk_orch(
            verification_report={"broken": []},
            verify_cost=0.40,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert "FeatureVerificationCompleted" in result.events_emitted


class TestBothStagesEnabled:
    def test_both_costs_charged_and_summed(self):
        orch = _mk_orch(
            compliance_report={"missing": []},
            compliance_cost=0.75,
            verification_report={"broken": []},
            verify_cost=0.40,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        assert result.cost_usd == 1.15
        # Two _accumulate_cost calls, in order.
        assert orch._accumulate_cost.call_count == 2
        deltas = [c.args[1] for c in orch._accumulate_cost.call_args_list]
        assert deltas == [0.75, 0.40]

    def test_both_events_in_order(self):
        orch = _mk_orch(
            compliance_report={"missing": []},
            compliance_cost=0.75,
            verification_report={"broken": []},
            verify_cost=0.40,
        )
        result = PhaseTbV(orch).run(_mk_ctx())
        # SpecCompliance first, then FeatureVerification.
        assert result.events_emitted == [
            "SpecComplianceCompleted",
            "FeatureVerificationCompleted",
        ]


# ---- delegation ----


class TestDelegation:
    def test_run_spec_compliance_receives_milestone_name_and_dict(self):
        orch = _mk_orch()
        ctx = _mk_ctx()
        PhaseTbV(orch).run(ctx)
        orch._run_spec_compliance.assert_called_once_with("M1", {"name": "M1"})

    def test_run_feature_verification_receives_milestone_name_only(self):
        orch = _mk_orch()
        PhaseTbV(orch).run(_mk_ctx())
        orch._run_feature_verification.assert_called_once_with("M1")
