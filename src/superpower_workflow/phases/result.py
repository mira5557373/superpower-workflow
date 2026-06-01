"""PhaseResult — uniform return shape for every PhaseBase.run().

Per Finding 1 resolution, `cost_usd` is REPORTING-ONLY: the local sum of
all claude-call costs the phase made. It is NOT what the driver passes
to `_accumulate_cost` — state.total_cost_usd is already advanced
incrementally INSIDE each phase via `self.orc._accumulate_cost(local,
delta)` after every internal claude call. The driver does pure-local
arithmetic on `ctx.accumulated_cost`:

    ctx = ctx.update(
        accumulated_cost=ctx.accumulated_cost + result.cost_usd,
        **result.extras,
    )

That preserves the v1.3.12 in-flight budget gate (state advances
within ms of each claude call, so sibling parallel workers see the
spend immediately) AND v1.3.4 #15 retry safety (cost is in state
BEFORE `_check_phase_result` can raise).

`tokens` matches the keys returned by
`superpower_workflow.runner.extract_token_usage()` exactly, so a
PhaseResult can be unpacked into PhaseCompleted via `**result.tokens`.

`extras` carries phase-specific outputs that flow into PhaseContext via
`ctx.update(**result.extras)`. Examples:
  - PhaseA: {"plan_commit_sha": "..."} — Phase B's prompt refs this
  - PhaseB: {"context_summary": "..."} — Phase C's prompt refs this
  - PhaseTbV: {"compliance_report": {...}, "verification_report": {...}}
              — Phase C's prompt conditionally refs these
  - PhaseE: {"ci_success": True} — driver decides milestone fate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superpower_workflow.orchestrator import _PhaseError


@dataclass
class PhaseResult:
    """Uniform return shape from PhaseBase.run()."""

    phase: str
    cost_usd: float
    duration_ms: int
    session_id: str
    tokens: dict[str, int | float]
    events_emitted: list[str]
    error: _PhaseError | None = None
    extras: dict[str, Any] = field(default_factory=dict)
