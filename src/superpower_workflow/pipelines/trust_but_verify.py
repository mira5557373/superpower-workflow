"""TrustButVerifyPipeline — extracted from orchestrator (v1.2.0 lite).

Encapsulates the four-stage trust-but-verify flow that runs between Phase B
and Phase D:
  1. Spec compliance check (independent claude -p)
  2. Feature verification (independent claude -p)
  3. Phase C review (existing claude -p)
  4. (When validation.strict_mode) Strict-mode loop on residual findings

This class is currently UNUSED by the orchestrator — extracted here as a
forward-compatible API for the v1.2.1 phase refactor. The orchestrator
continues to call its existing methods. Tests on this module pin the
behavior contract so that when the v1.2.1 refactor swaps the orchestrator
to use this class, regressions are caught at unit-test level.

Dependency-injectable: takes callables for compliance, verification, curator,
strict-mode loop so the class doesn't import the orchestrator (no circular
dependency).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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
        if self.verification_report is not None:
            broken = self.verification_report.get("broken", 0)
        else:
            broken = 0
        return missing == 0 and broken == 0


@dataclass
class TrustButVerifyPipeline:
    """Coordinates the four-stage pipeline. All stages are optional via flags."""

    spec_compliance_fn: Callable[[Any], tuple[dict | None, float]] | None = None
    feature_verification_fn: Callable[[Any], tuple[dict | None, float]] | None = None
    strict_loop_fn: Callable[[Any, dict | None, dict | None], tuple[list[dict], float]] | None = (
        None
    )
    config: dict = field(default_factory=dict)

    def _strict_enabled(self) -> bool:
        v = self.config.get("validation", {})
        return bool(v.get("strict_mode", False))

    def run(self, context: Any) -> TrustButVerifyResult:
        """Execute the pipeline. `context` is the orchestrator's per-milestone
        state object — opaque to this class.

        Returns a TrustButVerifyResult aggregating stage outputs and total cost.
        Any stage missing (callable=None) is silently skipped — useful for
        partial pipelines in tests.
        """
        result = TrustButVerifyResult()

        if self.spec_compliance_fn is not None:
            compliance, cost = self.spec_compliance_fn(context)
            result.compliance_report = compliance
            result.total_cost_usd += float(cost or 0.0)

        if self.feature_verification_fn is not None:
            verification, cost = self.feature_verification_fn(context)
            result.verification_report = verification
            result.total_cost_usd += float(cost or 0.0)

        if self.strict_loop_fn is not None and self._strict_enabled():
            iterations, cost = self.strict_loop_fn(
                context,
                result.compliance_report,
                result.verification_report,
            )
            result.strict_iterations = iterations or []
            result.total_cost_usd += float(cost or 0.0)

        return result
