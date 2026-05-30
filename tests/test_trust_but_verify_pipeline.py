"""Tests for the extracted TrustButVerifyPipeline (v1.2.0 lite)."""

from __future__ import annotations

from superpower_workflow.pipelines import TrustButVerifyPipeline


class _Ctx:
    """Stand-in for the orchestrator's milestone context."""

    def __init__(self, name="m1"):
        self.name = name


class TestPipelineSkipsMissingStages:
    def test_runs_with_no_stages(self):
        p = TrustButVerifyPipeline()
        result = p.run(_Ctx())
        assert result.compliance_report is None
        assert result.verification_report is None
        assert result.total_cost_usd == 0.0
        assert result.converged is True  # no compliance => trivially converged


class TestPipelineCallsStages:
    def test_compliance_only(self):
        called = []

        def compliance(ctx):
            called.append(("compliance", ctx.name))
            return {"missing": 0, "implemented": 5, "total_requirements": 5}, 0.3

        p = TrustButVerifyPipeline(spec_compliance_fn=compliance)
        result = p.run(_Ctx("M1"))
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
        result = p.run(_Ctx())
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
        p.run(_Ctx())
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
        result = p.run(_Ctx())
        assert ran == ["strict"]
        assert len(result.strict_iterations) == 1
        assert result.total_cost_usd == 0.5


class TestConverged:
    def test_converged_true_when_missing_zero_broken_zero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 0}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 0}, 0.0),
        )
        assert p.run(_Ctx()).converged is True

    def test_converged_false_when_missing_nonzero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 1}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 0}, 0.0),
        )
        assert p.run(_Ctx()).converged is False

    def test_converged_false_when_broken_nonzero(self):
        p = TrustButVerifyPipeline(
            spec_compliance_fn=lambda c: ({"missing": 0}, 0.0),
            feature_verification_fn=lambda c: ({"broken": 2}, 0.0),
        )
        assert p.run(_Ctx()).converged is False
