"""TrustButVerifyPipeline — extracted from orchestrator (v1.2.0 lite, v1.3.1 signatures).

Encapsulates the four-stage trust-but-verify flow that runs between Phase B
and Phase D:
  1. Spec compliance check (independent claude -p)
  2. Feature verification (independent claude -p)
  3. Phase C review (existing claude -p, handled by orchestrator)
  4. (When validation.strict_mode) Strict-mode loop on residual findings

v1.3.1 HIGH #8 fix: callable signatures now match the real orchestrator
methods. `PipelineContext` is the explicit data the adapter functions
receive — name, ms, model, fallback, plus optional logger.

The pipeline is currently UNUSED by the orchestrator. When v1.2.1 wires it,
the orchestrator constructs adapters that wrap its existing methods into
pipeline-compatible callables. The test suite now PINS the real signatures
so a future signature drift (rename, return-shape change) is caught at
unit-test level.

Dependency-injectable: takes callables for each stage so the class has no
circular dependency on the orchestrator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineContext:
    """The per-milestone context the adapter functions receive.

    Mirrors what the orchestrator's hot-path methods need:
    `_run_spec_compliance(self, name, ms)`,
    `_run_feature_verification(self, name)`,
    `_run_strict_mode_loop(self, name, ms, model, fallback, ...)`.

    Adapters can extend this dict via `extras` for orchestrator-specific
    state (logger, telemetry handle, etc.) without changing the protocol.
    """

    milestone_name: str = ""
    milestone_dict: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    fallback_model: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrustButVerifyResult:
    """Aggregate output of a single pipeline run."""

    compliance_report: dict | None = None
    verification_report: dict | None = None
    strict_iterations: list[dict] = field(default_factory=list)
    total_cost_usd: float = 0.0

    @property
    def converged(self) -> bool:
        """True when no missing requirements remain after all stages."""
        if self.compliance_report is None:
            return True
        missing = self.compliance_report.get("missing", 0)
        broken = (
            self.verification_report.get("broken", 0) if self.verification_report is not None else 0
        )
        return missing == 0 and broken == 0


# Stage callable type aliases — these are what the v1.2.1 orchestrator
# adapters must produce. v1.3.1 nails them down to avoid signature drift.

# (ctx) -> (compliance_report_dict_or_None, cost)
SpecComplianceFn = Callable[[PipelineContext], tuple[dict | None, float]]

# (ctx) -> (verification_report_dict_or_None, cost)
FeatureVerificationFn = Callable[[PipelineContext], tuple[dict | None, float]]

# (ctx, compliance, verification) -> (iterations_list, cost)
# The orchestrator's `_run_strict_mode_loop` currently returns just `float`;
# v1.2.1's adapter must capture iterations from telemetry events emitted
# during the loop and return them here. Adapter responsibility.
StrictLoopFn = Callable[
    [PipelineContext, dict | None, dict | None],
    tuple[list[dict], float],
]


@dataclass
class TrustButVerifyPipeline:
    """Coordinates the four-stage pipeline. All stages are optional via flags.

    Future use (v1.2.1): orchestrator wraps `_run_spec_compliance`,
    `_run_feature_verification`, `_run_strict_mode_loop` as adapter functions
    that match these signatures, then calls `pipeline.run(ctx)`.
    """

    spec_compliance_fn: SpecComplianceFn | None = None
    feature_verification_fn: FeatureVerificationFn | None = None
    strict_loop_fn: StrictLoopFn | None = None
    config: dict = field(default_factory=dict)

    def _strict_enabled(self) -> bool:
        return bool(self.config.get("validation", {}).get("strict_mode", False))

    def run(self, ctx: PipelineContext) -> TrustButVerifyResult:
        """Execute the pipeline.

        Returns a TrustButVerifyResult aggregating stage outputs and total cost.
        Any stage missing (callable=None) is silently skipped — useful for
        partial pipelines and tests. Exceptions inside a stage callable
        propagate; the orchestrator's adapter is responsible for retry/fallback.
        """
        result = TrustButVerifyResult()

        if self.spec_compliance_fn is not None:
            compliance, cost = self.spec_compliance_fn(ctx)
            result.compliance_report = compliance
            result.total_cost_usd += float(cost or 0.0)

        if self.feature_verification_fn is not None:
            verification, cost = self.feature_verification_fn(ctx)
            result.verification_report = verification
            result.total_cost_usd += float(cost or 0.0)

        if self.strict_loop_fn is not None and self._strict_enabled():
            iterations, cost = self.strict_loop_fn(
                ctx,
                result.compliance_report,
                result.verification_report,
            )
            result.strict_iterations = iterations or []
            result.total_cost_usd += float(cost or 0.0)

        return result
