"""PhaseContext — frozen carrier for the per-milestone phase loop state.

Phases consume a PhaseContext and produce a PhaseResult. The driver
threads `ctx = ctx.update(accumulated_cost=ctx.accumulated_cost +
result.cost_usd, **result.extras)` between phases — pure local
arithmetic, no state writes (cost transfer to `state.total_cost_usd`
happens INSIDE each phase via `self.orc._accumulate_cost(...)` per
internal claude call, preserving the v1.3.12 in-flight budget gate).

Frozen + update()-only mutation is the Finding 3 resolution: a phase
that adds an `extras` key without adding the corresponding
PhaseContext field will raise TypeError instead of silently dropping
the data. update() goes through dataclasses.replace, which validates
that every kwarg matches a known field.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpower_workflow.logger import WorkflowLogger


@dataclass(frozen=True)
class PhaseContext:
    """Immutable per-milestone phase-loop context."""

    # ---- identity ----
    milestone_name: str
    milestone_dict: dict[str, Any]

    # ---- config slice (read-only refs; phases never mutate) ----
    spec: str
    sections: str
    model: str
    budgets: dict[str, Any]
    fallback_model: str | None = None
    effort: dict[str, str] = field(default_factory=dict)
    verify: dict[str, str] = field(default_factory=dict)
    convergence: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    # ---- cumulative work (advanced via ctx.update()) ----
    context_summary: str = ""
    accumulated_cost: float = 0.0
    plan_commit_sha: str | None = None

    # ---- downstream injection (PhaseB → PhaseTbV → PhaseC) ----
    compliance_report: dict[str, Any] | None = None
    verification_report: dict[str, Any] | None = None

    # ---- logger handle (kept here so PhaseBase.run is single-arg) ----
    logger: WorkflowLogger | None = None

    def update(self, **kwargs: Any) -> PhaseContext:
        """Return a NEW PhaseContext with the given fields replaced.

        Phases MUST go through this method, never `dataclasses.replace`
        directly. `update()` is the single instrumentation point for
        golden-trace recording AND the place where unknown-field guard
        fires (a phase that adds an `extras` key without a matching
        PhaseContext field gets a `TypeError` instead of silently
        dropping the value).
        """
        return dataclasses.replace(self, **kwargs)
