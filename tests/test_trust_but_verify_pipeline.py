"""Tests for the extracted TrustButVerifyPipeline (v1.2.0 lite + v1.3.1 signatures)."""

from __future__ import annotations

import inspect

from superpower_workflow.pipelines import (
    PipelineContext,
    TrustButVerifyPipeline,
)


def _ctx(name="m1", ms=None, model="opus", fallback="haiku"):
    return PipelineContext(
        milestone_name=name,
        milestone_dict=ms or {"name": name, "estimated_cost": 10.0},
        model=model,
        fallback_model=fallback,
    )


class TestPipelineSkipsMissingStages:
    def test_runs_with_no_stages(self):
        p = TrustButVerifyPipeline()
        result = p.run(_ctx())
        assert result.compliance_report is None
        assert result.verification_report is None
        assert result.total_cost_usd == 0.0
        assert result.converged is True  # no compliance => trivially converged


class TestPipelineCallsStages:
    def test_compliance_only(self):
        called = []

        def compliance(ctx):
            called.append(("compliance", ctx.milestone_name))
            return {"missing": 0, "implemented": 5, "total_requirements": 5}, 0.3

        p = TrustButVerifyPipeline(spec_compliance_fn=compliance)
        result = p.run(_ctx("M1"))
        assert called == [("compliance", "M1")]
        assert result.compliance_report["implemented"] == 5
        assert result.total_cost_usd == 0.3

    def test_full_pipeline_costs_aggregate(self):
        def compliance(ctx):
            return {"missing": 0}, 0.3

        def verification(ctx):
            return {"broken": 0}, 0.4

        def strict(ctx, compliance, verification):
            return [], 0.0  # no iterations needed

        p = TrustButVerifyPipeline(
            spec_compliance_fn=compliance,
            feature_verification_fn=verification,
            strict_loop_fn=strict,
            config={"validation": {"strict_mode": True}},
        )
        result = p.run(_ctx())
        assert round(result.total_cost_usd, 2) == 0.7
        assert result.converged is True


class TestStrictModeGating:
    def test_strict_loop_skipped_when_strict_mode_false(self):
        ran = []

        def strict(*a, **kw):
            ran.append("strict")
            return [], 0.0

        p = TrustButVerifyPipeline(
            strict_loop_fn=strict,
            config={"validation": {"strict_mode": False}},
        )
        p.run(_ctx())
        assert ran == []

    def test_strict_loop_runs_when_strict_mode_true(self):
        ran = []

        def strict(ctx, c, v):
            ran.append("strict")
            return [{"iteration": 1, "converged": True}], 0.5

        p = TrustButVerifyPipeline(
            strict_loop_fn=strict,
            config={"validation": {"strict_mode": True}},
        )
        result = p.run(_ctx())
        assert ran == ["strict"]
        assert len(result.strict_iterations) == 1
        assert result.total_cost_usd == 0.5


class TestConverged:
    def test_converged_true_when_missing_zero_broken_zero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 0}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 0}, 0.0),
        )
        assert p.run(_ctx()).converged is True

    def test_converged_false_when_missing_nonzero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 1}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 0}, 0.0),
        )
        assert p.run(_ctx()).converged is False

    def test_converged_false_when_broken_nonzero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 0}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 2}, 0.0),
        )
        assert p.run(_ctx()).converged is False


class TestPipelineContextShape:
    """v1.3.1 HIGH #8: PipelineContext fields must match what the orchestrator
    actually passes to its phase methods. If a field is renamed/removed here,
    the adapter for v1.2.1 will need updating in lockstep — these tests fail
    loudly if someone drops a field without updating the adapter.
    """

    def test_context_has_required_fields(self):
        ctx = PipelineContext(
            milestone_name="m1",
            milestone_dict={"x": 1},
            model="opus",
            fallback_model="haiku",
        )
        assert ctx.milestone_name == "m1"
        assert ctx.milestone_dict == {"x": 1}
        assert ctx.model == "opus"
        assert ctx.fallback_model == "haiku"
        assert ctx.extras == {}

    def test_context_extras_accepts_logger_and_telemetry(self):
        log = object()
        tel = object()
        ctx = PipelineContext(extras={"logger": log, "telemetry": tel})
        assert ctx.extras["logger"] is log
        assert ctx.extras["telemetry"] is tel


class TestSignatureContractWithOrchestrator:
    """v1.3.1 HIGH #8: pin the orchestrator method signatures the v1.2.1
    adapter must wrap. If `_run_spec_compliance` gets renamed or its arg
    list changes, this test fails — forcing PipelineContext / adapter
    updates in the same PR.
    """

    def test_orchestrator_spec_compliance_signature(self):
        from superpower_workflow.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator._run_spec_compliance)
        params = list(sig.parameters)
        # Should be (self, name, ms) — what PipelineContext carries.
        assert params[0] == "self"
        assert "name" in params
        assert "ms" in params

    def test_orchestrator_feature_verification_signature(self):
        from superpower_workflow.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator._run_feature_verification)
        params = list(sig.parameters)
        assert params[0] == "self"
        assert "name" in params

    def test_orchestrator_strict_loop_signature(self):
        from superpower_workflow.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator._run_strict_mode_loop)
        params = list(sig.parameters)
        assert params[0] == "self"
        assert "name" in params
        assert "ms" in params
        assert "model" in params
        assert "fallback" in params
