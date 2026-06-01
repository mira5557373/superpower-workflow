"""PhaseA — Plan + Ultrathink.

Verbatim lift of orchestrator.py:1099-1158 (the Phase A block of
`_run_milestone`). Behavior MUST match byte-for-byte so the golden trace
fixtures from Tasks 1.2/1.3/1.4 stay valid when Task 8 wires this class
into the driver.

Critical invariants preserved (all pinned by tests in
tests/test_phase_a.py):

1. Per-call `_accumulate_cost` for the primary claude call BEFORE
   `_check_phase_result` (v1.3.4 #15 retry safety + v1.3.12 in-flight
   gate granularity).
2. Per-call `_accumulate_cost` for the curator cost (Finding 1).
3. PhaseCompleted emission uses `r.cost_usd` ONLY (the primary call),
   NOT primary + curator. The original code emits the primary in the
   PhaseCompleted event and separately surfaces total cost via the
   audit append + post_phase plugin payload (both also use primary
   only — curator is "out-of-band").
4. `_audit.append("PHASE_COMPLETE", data={"cost": round(r.cost_usd, 2)})`
   uses primary cost rounded to 2 dp.
5. `_call_post_phase("plan", ms, {"cost": r.cost_usd})` uses primary
   cost (NOT rounded).
6. `archive_reports` and `clear_phase_state` operate on
   `self.orc.claude_dir` (worker-local in parallel mode), NOT
   `self.orc._state_dir` (the parent state path). This is intentional
   — reports are per-worker artifacts.
7. `save_state` writes to `self.orc._state_dir` (parent state path)
   — v1.3.13 #3 routing.
8. `plan_commit_sha` flows out via PhaseResult.extras so the driver
   threads it into the next PhaseContext (Phase B's prompt may
   reference it).

PhaseResult.cost_usd is REPORTING-ONLY per Finding 1 — it includes both
the primary claude cost AND the curator cost, returned for the
driver's `ctx.update(accumulated_cost = ctx.accumulated_cost +
result.cost_usd)`. Pure-local arithmetic — no state write at the
driver level. State has already advanced incrementally inside this
class via the two `_accumulate_cost` calls.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.prompts import phase_a_prompt
from superpower_workflow.runner import extract_token_usage
from superpower_workflow.state import (
    PhaseState,
    archive_reports,
    clear_phase_state,
    save_phase_state,
    save_state,
)

if TYPE_CHECKING:
    from superpower_workflow.phases.context import PhaseContext


class PhaseA(PhaseBase):
    """Plan phase — ultrathink + gap analysis + commit + tag."""

    name = "plan"
    log_event_start = "PHASE_A_START"
    log_event_complete = "PHASE_A_COMPLETE"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []

        # 1. Plugin pre-phase hook (translates PluginVetoError → _PhaseError).
        self._call_pre_phase(ctx)

        # 2. State transition + save (parent _state_dir per v1.3.13 #3).
        self._set_current_step(ctx, "plan")

        # 3. save_phase_state for the convergence hook to read.
        #    Note: this is worker-local (self.orc.claude_dir), NOT
        #    self.orc._state_dir — phase state is per-milestone.
        save_phase_state(
            self.orc.claude_dir,
            PhaseState(
                phase="ultrathink",
                max_iterations=ctx.convergence.get("max_iterations", 5),
            ),
        )

        # 4. Log + emit PhaseStarted.
        ctx.logger.log("PHASE_A_START")
        self._emit_phase_started(ctx)
        events.append("PhaseStarted")

        # 5. Primary claude call — phase_a_prompt(name, context, spec, sections).
        r = self.orc._run_claude(
            phase_a_prompt(ctx.milestone_name, ctx.context_summary, ctx.spec, ctx.sections),
            model=ctx.model,
            effort=ctx.effort.get("plan", "max"),
            budget=ctx.budgets.get("plan", 25),
            cwd=self.orc.cwd,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )

        # 6. Charge primary cost to state. Done BEFORE _check_phase_result
        #    so a v1.3.4 #15-style raise doesn't drop spent dollars.
        self.orc._accumulate_cost(0.0, r.cost_usd)

        # 7. Curator pass (returns 0.0 if disabled).
        curator_cost = self.orc._run_gap_curator(ctx.milestone_name, "plan")
        self.orc._accumulate_cost(0.0, curator_cost)

        # 8. Emit gap report + gap validation events (no-op if files absent).
        self.orc._emit_gap_report(ctx.milestone_name, "plan")
        events.append("GapReport")
        self.orc._emit_gap_validation(ctx.milestone_name)
        events.append("GapValidationEvent")

        # 9. Archive reports + clear worker-local phase state.
        archive_reports(self.orc.claude_dir, ctx.milestone_name, "plan")
        clear_phase_state(self.orc.claude_dir)

        # 10. Check result (may raise _PhaseError — cost is already in state).
        self.orc._check_phase_result(r, "Phase A")

        # 11. PhaseCompleted emit + log + audit + post_phase hook.
        #     Each of these uses r.cost_usd (primary only, NOT primary +
        #     curator). The original orchestrator code does the same.
        self._emit_phase_completed(ctx, r)
        events.append("PhaseCompleted")
        ctx.logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit_complete(ctx, r.cost_usd)
        self._call_post_phase(ctx, r.cost_usd)

        # 12. Capture plan commit SHA + session_id, save state, tag.
        #     subprocess.run([git, rev-parse, HEAD], cwd=self.orc.cwd) →
        #     stdout has SHA (or "" if git fails — fine, downstream
        #     handles empty SHA).
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.orc.cwd,
        )
        plan_commit_sha = sha_result.stdout.strip()
        self.orc.state.plan_commit_sha = plan_commit_sha
        self.orc.state.last_phase_session_id = r.session_id
        save_state(self.orc._state_dir, self.orc.state)

        # 13. Tag the pre-impl commit (best-effort; capture output to
        #     suppress noise).
        subprocess.run(
            ["git", "tag", f"pre-impl/{ctx.milestone_name}"],
            capture_output=True,
            cwd=self.orc.cwd,
        )

        # 14. Return PhaseResult — cost_usd is REPORTING-ONLY (primary +
        #     curator). The driver does pure-local accumulator arithmetic.
        #     plan_commit_sha flows out via extras so Phase B's
        #     PhaseContext can reference it.
        return PhaseResult(
            phase=self.name,
            cost_usd=r.cost_usd + curator_cost,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={"plan_commit_sha": plan_commit_sha},
        )
