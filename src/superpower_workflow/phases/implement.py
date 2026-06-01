"""PhaseB — Implement + QG#1 + coverage + trailers + context refresh.

Verbatim lift of orchestrator.py:1160-1265. Behavior MUST match
byte-for-byte so the golden trace from Task 1.2 (happy path) and the
fix-loop fixture from Task 1.3 remain valid through Task 8 wire-up.

PhaseB ends with the context refresh (build_context_summary applied to
whatever Phase B's claude call produced). The downstream stages
(spec_compliance + feature_verification) split out into PhaseTbV per
Finding 3 resolution — keeping a clean phase boundary between
implement/QG and the trust-but-verify stages so future evolution
(custom validation pipelines, alternate compliance backends) drops
into PhaseTbV without re-extracting from PhaseB.

Critical invariants preserved (pinned by tests/test_phase_b.py):

1. v1.3.4 #15 + v1.3.12: primary _accumulate_cost BEFORE
   _check_phase_result.
2. Finding 1: per-call _accumulate_cost — primary, fix-loop (via
   run_quality_gate_checkpoint), coverage. NOT a single per-phase
   aggregate.
3. Finding 2 item 1: the QG#1 fix-loop uses checkpoint="quality_check_b"
   for gates recheck (same label) and "quality_check_b_recheck" for
   policy recheck (asymmetric). Already pinned by
   run_quality_gate_checkpoint's own tests; PhaseB just delegates.
4. PhaseCompleted emits primary cost only — fix-loop, coverage,
   compliance, verification costs are reported separately.
5. last_phase_session_id mutates state but doesn't save_state inline
   (matches original code at line 1180 — the next save_state happens
   at line 1203 when current_step transitions to quality_check_b).
6. context refresh via build_context_summary lands in
   PhaseResult.extras["context_summary"] so the driver threads it
   into the next PhaseContext via ctx.update(**extras).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superpower_workflow.context import build_context_summary
from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.prompts import phase_b_prompt
from superpower_workflow.quality_gates import run_quality_gate_checkpoint
from superpower_workflow.runner import extract_token_usage
from superpower_workflow.state import save_state

if TYPE_CHECKING:
    from superpower_workflow.phases.context import PhaseContext


class PhaseB(PhaseBase):
    """Implement phase — claude builds + QG#1 + coverage + trailers + context refresh."""

    name = "implement"
    log_event_start = "PHASE_B_START"
    log_event_complete = "PHASE_B_COMPLETE"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []

        # 1. Plugin pre-phase hook.
        self._call_pre_phase(ctx)

        # 2. State transition + save (parent _state_dir).
        self._set_current_step(ctx, "implement")

        # 3. Resolve plan path (where Phase A wrote the plan output).
        plan_path = self.orc._find_plan_path(ctx.milestone_name)

        # 4. Log + emit PhaseStarted.
        ctx.logger.log("PHASE_B_START")
        self._emit_phase_started(ctx)
        events.append("PhaseStarted")

        # 5. Primary claude call.
        r = self.orc._run_claude(
            phase_b_prompt(ctx.milestone_name, ctx.context_summary, plan_path),
            model=ctx.model,
            effort=ctx.effort.get("implement", "high"),
            budget=ctx.budgets.get("implement", 100),
            cwd=self.orc.cwd,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )

        # 6. Charge primary cost (Finding 1 + v1.3.4 #15).
        self.orc._accumulate_cost(0.0, r.cost_usd)

        # 7. Persist last_phase_session_id in-memory only — original
        # orchestrator code does NOT call save_state here; the next
        # save_state fires when current_step transitions to
        # quality_check_b (step 9).
        self.orc.state.last_phase_session_id = r.session_id

        # 8. Check result (may raise; cost already in state).
        self.orc._check_phase_result(r, "Phase B")

        # 9. PhaseCompleted + log + audit + post_phase.
        self._emit_phase_completed(ctx, r)
        events.append("PhaseCompleted")
        ctx.logger.log("PHASE_B_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit_complete(ctx, r.cost_usd)
        self._call_post_phase(ctx, r.cost_usd)

        # 10. Transition to quality_check_b + save.
        self.orc.state.current_step = "quality_check_b"
        save_state(self.orc._state_dir, self.orc.state)

        # 11. QG#1 via the shared helper (Task 3). Helper handles fix-
        # loop with per-call _accumulate_cost (Finding 1) and the
        # asymmetric policy _recheck label (Finding 2 item 1).
        qg_cost = run_quality_gate_checkpoint(
            self.orc,
            ctx,
            checkpoint="quality_check_b",
            phase_label="Phase B",
        )

        # 12. Coverage check (returns (passed, cost) — cost is the
        # claude iterations the coverage helper made internally).
        _, cov_cost = self.orc._check_coverage(ctx.logger, milestone=ctx.milestone_name)
        self.orc._accumulate_cost(0.0, cov_cost)

        # 13. Trailer check — no cost, just policy verification.
        plan_sha = self.orc.state.plan_commit_sha or ""
        self.orc._check_trailers(plan_sha, ctx.logger)

        # 14. Refresh context to include what Phase B built. The driver
        # threads this into the next PhaseContext via extras.
        new_context = build_context_summary(
            self.orc.state.completed,
            self.orc.root,
            ctx.milestone_dict,
            self.orc.config.get("milestones", []),
        )

        # 15. Return PhaseResult — cost_usd is REPORTING-ONLY per
        # Finding 1 (primary + QG fix-loop + coverage). State has
        # already advanced incrementally.
        return PhaseResult(
            phase=self.name,
            cost_usd=r.cost_usd + qg_cost + cov_cost,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={"context_summary": new_context},
        )
