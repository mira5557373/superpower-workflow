"""PhaseE — CI fix loop.

Verbatim lift of orchestrator.py:1478-1532. Key ordering invariants
the adversarial review flagged:

- State transition order at PhaseStarted emit time (Finding 1 verdict
  point 3): `ci_wait → save → log → emit PhaseStarted → ci_fix →
  save`. At the moment of PhaseStarted emission, `state.current_step`
  is "ci_wait" (NOT "ci_fix"). This is INTENTIONAL — a telemetry
  consumer correlating PhaseStarted with state.current_step snapshots
  observes "ci_wait" at PhaseStarted, and "ci_fix" persists right after.
- PhaseE NEVER raises on ci_success=False (preserved verbatim). The
  driver checks result.extras["ci_success"] to decide milestone fate.

PhaseE is unusual:
- Conditional on `integrations.ci.enabled` — if False, short-circuits
  to a no-op PhaseResult (zero cost, empty events, ci_success=True,
  ci_enabled=False). The driver always invokes; the helper gates.
- No _call_pre_phase, no _check_phase_result, no _call_post_phase.
  Preserved verbatim from original.
- PhaseCompleted is emitted manually (NOT via _emit_phase_completed)
  because the helper unpacks `**ci_tokens` from ci_fix_loop's
  aggregated return — NOT extract_token_usage(r.raw) since there's
  no primary `r`.
- PhaseCompleted.cost_usd uses `round(ci_cost, 2)` — different from
  other phases (which emit r.cost_usd unrounded in the event,
  rounded only in the log/audit). Preserved verbatim.
- duration_ms=0, session_id="" — no single primary claude call;
  the loop makes N internal calls.

Critical: ci_fix_loop returns (ci_success, ci_cost, ci_tokens) where
ci_cost is the aggregate of internal claude iterations. The single
_accumulate_cost(0, ci_cost) call charges the aggregate to state at
the LOOP BOUNDARY — not per iteration. Mid-loop crashes drop partial
cost (matches the strict-mode loop pattern from PhaseC).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superpower_workflow.integrations.ci_fix import ci_fix_loop
from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.state import save_state
from superpower_workflow.telemetry import PhaseCompleted, PhaseStarted

if TYPE_CHECKING:
    from superpower_workflow.phases.context import PhaseContext

# Zero-token shape used when the phase short-circuits (CI disabled).
_ZERO_TOKENS = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_hit_rate": 0.0,
}


class PhaseE(PhaseBase):
    """CI fix loop — wait for CI, fix failures, retry."""

    name = "ci_fix"
    log_event_start = "PHASE_E_START"
    log_event_complete = "PHASE_E_COMPLETE"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []

        # 0. Short-circuit if CI not enabled — driver always calls, helper gates.
        ci_config = self.orc._integrations.get("ci", {})
        if not ci_config.get("enabled", False):
            return PhaseResult(
                phase=self.name,
                cost_usd=0.0,
                duration_ms=0,
                session_id="",
                tokens=dict(_ZERO_TOKENS),
                events_emitted=events,
                extras={"ci_success": True, "ci_enabled": False},
            )

        # 1. state="ci_wait" → save_state. Per Finding 1 verdict point 3,
        # PhaseStarted is emitted at "ci_wait" current_step, NOT "ci_fix".
        self.orc.state.current_step = "ci_wait"
        save_state(self.orc._state_dir, self.orc.state)

        # 2. Log PHASE_E_START.
        ctx.logger.log("PHASE_E_START")

        # 3. Emit PhaseStarted (with phase="ci_fix" payload — matches
        # original line 1483 which uses phase="ci_fix" not "ci_wait").
        self.orc._telemetry.emit(PhaseStarted(milestone=ctx.milestone_name, phase=self.name))
        events.append("PhaseStarted")

        # 4. NOW transition to "ci_fix" + save. The two-step transition
        # is intentional — telemetry consumers see PhaseStarted at
        # "ci_wait", then "ci_fix" persists right after.
        self.orc.state.current_step = "ci_fix"
        save_state(self.orc._state_dir, self.orc.state)

        # 5. CI attempt notification callback.
        def _on_ci_attempt(attempt: int, max_attempts: int, status: str) -> None:
            self.orc._notify(
                "ci_fix",
                {
                    "milestone": ctx.milestone_name,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "status": status,
                },
            )

        # 6. CI fix loop — returns (success, aggregate_cost, aggregate_tokens).
        ci_success, ci_cost, ci_tokens = ci_fix_loop(
            cwd=self.orc.cwd,
            ci_config=ci_config,
            run_claude_fn=self.orc._run_claude,
            model=ctx.model,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
            on_attempt=_on_ci_attempt,
        )

        # 7. Charge aggregate cost. v1.3.4 #15 retry safety holds at the
        # loop boundary only — mid-loop crashes drop partial cost.
        # Matches strict-mode loop pattern from PhaseC.
        self.orc._accumulate_cost(0.0, ci_cost)

        # 8. Log completion + transition state on failure.
        if ci_success:
            ctx.logger.log("PHASE_E_COMPLETE", status="passed", cost=round(ci_cost, 2))
        else:
            self.orc.state.current_step = "ci_fix_failed"
            save_state(self.orc._state_dir, self.orc.state)
            ctx.logger.log("PHASE_E_COMPLETE", status="failed", cost=round(ci_cost, 2))

        # 9. PhaseCompleted — uses round(ci_cost, 2) in cost_usd (NOT
        # the unrounded value other phases use). duration_ms=0,
        # session_id="" since there's no single primary call.
        self.orc._telemetry.emit(
            PhaseCompleted(
                milestone=ctx.milestone_name,
                phase=self.name,
                cost_usd=round(ci_cost, 2),
                duration_ms=0,
                session_id="",
                **ci_tokens,
            )
        )
        events.append("PhaseCompleted")

        # 10. Audit. Includes ci_success bool in data — distinct from
        # other phases' audit payloads.
        self.orc._audit.append(
            "PHASE_COMPLETE",
            run_id=self.orc.state.run_id,
            milestone=ctx.milestone_name,
            data={
                "phase": "ci_fix",
                "cost": round(ci_cost, 2),
                "success": ci_success,
            },
        )

        return PhaseResult(
            phase=self.name,
            cost_usd=ci_cost,
            duration_ms=0,
            session_id="",
            tokens=ci_tokens,
            events_emitted=events,
            extras={"ci_success": ci_success, "ci_enabled": True},
        )
