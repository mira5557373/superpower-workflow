"""PhaseBase — abstract skeleton shared by every concrete phase class.

Subclasses (PhaseA/PhaseB/PhaseTbV/PhaseC/PhaseD/PhaseE) implement
`run(ctx)` and rely on the shared helpers below for the side effects
that touch shared orchestrator state: telemetry emission, audit-trail
appends, current-step transitions, plugin pre/post hooks.

Per Finding 1 resolution, phases call `self.orc._accumulate_cost(...)`
AFTER every internal claude call themselves — that's NOT in PhaseBase
because the local_acc thread varies per phase. PhaseBase only owns
side effects that are shaped identically across phases.

Sync execute() per ODQ-4 — async deferred to ≥v2.0.0.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from superpower_workflow.orchestrator import Orchestrator
    from superpower_workflow.phases.context import PhaseContext
    from superpower_workflow.phases.result import PhaseResult
    from superpower_workflow.runner import ClaudeResult


class PhaseBase(ABC):
    """Abstract base class for a single phase of the milestone loop.

    Subclasses MUST set `name`, `log_event_start`, `log_event_complete`
    as class-level constants and implement `run(ctx) -> PhaseResult`.
    """

    # Subclasses set these as ClassVar — never per-instance.
    name: ClassVar[str]
    log_event_start: ClassVar[str]
    log_event_complete: ClassVar[str]

    def __init__(self, orchestrator: Orchestrator) -> None:
        """Bind to an Orchestrator handle.

        Phases NEVER mutate orchestrator state directly except through
        the helper methods exposed on Orchestrator (`_accumulate_cost`,
        `_audit.append`, `_telemetry.emit`, `_call_pre_phase`,
        `_call_post_phase`). All other state is read-only.
        """
        self.orc = orchestrator

    @abstractmethod
    def run(self, ctx: PhaseContext) -> PhaseResult:
        """Execute the phase. Return a PhaseResult describing the outcome.

        Per Finding 1, cost is transferred to `state.total_cost_usd`
        INSIDE this method via `self.orc._accumulate_cost(local, delta)`
        after EVERY internal claude call — the returned
        `PhaseResult.cost_usd` is reporting-only.
        """

    # ---- shared helpers (final / non-overridable in practice) ----

    def _emit_phase_started(self, ctx: PhaseContext) -> None:
        """Emit a PhaseStarted telemetry event for this phase."""
        from superpower_workflow.telemetry import PhaseStarted

        self.orc._telemetry.emit(PhaseStarted(milestone=ctx.milestone_name, phase=self.name))

    def _emit_phase_completed(
        self,
        ctx: PhaseContext,
        r: ClaudeResult,
        extra_cost: float = 0.0,
    ) -> None:
        """Emit a PhaseCompleted telemetry event.

        `r` is the primary claude result for this phase; `extra_cost`
        is the local sum of any non-primary claude calls (curator, QG
        fix-loop, etc.) the phase made. The reported `cost_usd` is the
        TOTAL phase cost (primary + extra). Token fields come from
        `extract_token_usage(r.raw)` — the primary call's shape, NOT
        an aggregate (callers that need aggregated tokens build their
        own event via `tokens=...`).
        """
        from superpower_workflow.runner import extract_token_usage
        from superpower_workflow.telemetry import PhaseCompleted

        tokens = extract_token_usage(r.raw)
        self.orc._telemetry.emit(
            PhaseCompleted(
                milestone=ctx.milestone_name,
                phase=self.name,
                cost_usd=r.cost_usd + extra_cost,
                duration_ms=r.duration_ms,
                session_id=r.session_id,
                **tokens,
            )
        )

    def _audit_complete(self, ctx: PhaseContext, cost: float) -> None:
        """Append a PHASE_COMPLETE entry to the audit trail."""
        self.orc._audit.append(
            "PHASE_COMPLETE",
            run_id=self.orc.state.run_id,
            milestone=ctx.milestone_name,
            data={"phase": self.name, "cost": round(cost, 2)},
        )

    def _set_current_step(self, ctx: PhaseContext, step: str) -> None:
        """Advance `state.current_step` and persist to disk.

        Writes to `self.orc._state_dir` (the v1.3.13 parent-state path)
        — never `self.orc.claude_dir` (the worker-local path in
        parallel mode). This preserves the v1.3.13 #3 state-routing
        invariant.
        """
        from superpower_workflow.state import save_state

        self.orc.state.current_step = step
        save_state(self.orc._state_dir, self.orc.state)

    def _call_pre_phase(self, ctx: PhaseContext) -> None:
        """Invoke plugin pre_phase hooks. Translates PluginVetoError to _PhaseError."""
        from superpower_workflow.orchestrator import _PhaseError
        from superpower_workflow.plugins.interface import PluginVetoError

        try:
            self.orc._call_pre_phase(self.name, ctx.milestone_dict)
        except PluginVetoError as e:
            raise _PhaseError(self.name, str(e)) from e

    def _call_post_phase(self, ctx: PhaseContext, cost: float) -> None:
        """Invoke plugin post_phase hooks with the realized cost."""
        self.orc._call_post_phase(self.name, ctx.milestone_dict, {"cost": cost})
