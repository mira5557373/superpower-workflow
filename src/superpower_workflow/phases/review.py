"""PhaseC — Review + Fix + QG#2 + strict-mode + gap curator.

Verbatim lift of orchestrator.py:1275-1402. The largest extraction so
far. The 3-agent design workflow (Workflow ws3glvjd7) verified the
6-site _accumulate_cost map against source; the adversarial test
verifier surfaced one HIGH coverage gap (strict-mode loop N>=2
iterations + mid-strict-loop crash retry-safety) which is addressed
by 2 additional unit tests below the design's baseline 15 invariants.

Critical invariants preserved (pinned by tests/test_phase_c.py):

1. Six _accumulate_cost sites (Finding 1 — v1.3.12 in-flight gate):
   - ACC #1 primary r.cost_usd (BEFORE _check_phase_result)
   - ACC #2 curator_cost (BEFORE _check_phase_result)
   - ACC #3 QG#2 gate fix (inside helper, only if gates fail)
   - ACC #4 QG#2 policy fix (inside helper, only if policies fail)
   - ACC #5 cov_cost (after QG, NOT inside helper)
   - ACC #6 strict_cost aggregate (after coverage, NOT per-iteration)
2. v1.3.4 #15: primary + curator cost charged BEFORE _check_phase_result.
3. Asymmetric checkpoint label: gates recheck reuses 'quality_check_c';
   policy recheck uses 'quality_check_c_recheck' (handled by Task 3
   helper).
4. Curator + emit_gap_report + emit_gap_validation + archive +
   clear_phase_state happen BEFORE _check_phase_result (matches Phase A
   ordering, NOT Phase B). This is intentional — DO NOT reorder.
5. The PRIMARY r is preserved verbatim through PhaseCompleted /
   audit / post_phase emissions; the helper internally reassigns r
   for fix calls but those don't leak out.
6. _run_strict_mode_loop is called UNCONDITIONALLY — strict_mode gate
   lives inside the helper. PhaseC always invokes it; the helper
   returns 0.0 when disabled.
7. Strict iteration costs accrue to a LOCAL `total_cost` inside
   _run_strict_mode_loop via raw `+=` (NOT _accumulate_cost). v1.3.4
   #15 retry-safety only holds at the strict-loop BOUNDARY (a
   mid-iteration crash drops partial cost) — preserved verbatim.
8. PhaseCompleted, PHASE_C_COMPLETE log, audit.append, _call_post_phase
   all emit PRIMARY r.cost_usd ONLY (not the running cost).
9. archive_reports + clear_phase_state + save_phase_state target
   claude_dir (worker-local); save_state targets _state_dir (v1.3.13 #3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.prompts import phase_c_prompt
from superpower_workflow.quality_gates import run_quality_gate_checkpoint
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


class PhaseC(PhaseBase):
    """Review phase — fix claude + QG#2 + coverage + strict-mode."""

    name = "review"
    log_event_start = "PHASE_C_START"
    log_event_complete = "PHASE_C_COMPLETE"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []
        r, curator_cost = self._run_review(ctx, events)
        qg_cost, cov_cost, strict_cost = self._run_post_review_checks(ctx)
        return PhaseResult(
            phase=self.name,
            cost_usd=r.cost_usd + curator_cost + qg_cost + cov_cost + strict_cost,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={},
        )

    def _run_review(self, ctx: PhaseContext, events: list[str]):
        """Phase C primary review — claude call + curator + gap emission
        + archive + check + completion emit. Mutates `events` in place.

        Returns the primary ClaudeResult and the curator cost.
        """
        self._call_pre_phase(ctx)
        self._set_current_step(ctx, "review")
        save_phase_state(
            self.orc.claude_dir,
            PhaseState(
                phase="review",
                max_iterations=ctx.convergence.get("max_iterations", 5),
            ),
        )
        ctx.logger.log("PHASE_C_START")
        self._emit_phase_started(ctx)
        events.append("PhaseStarted")

        # phase_c_prompt threads compliance + verification reports
        # from PhaseTbV (via driver's ctx.update(**result.extras)).
        r = self.orc._run_claude(
            phase_c_prompt(
                ctx.milestone_name,
                ctx.context_summary,
                ctx.plan_commit_sha or "",
                ctx.verify.get("test", "true"),
                ctx.verify.get("lint", "true"),
                ctx.verify.get("format", "true"),
                compliance_report=ctx.compliance_report,
                verification_report=ctx.verification_report,
            ),
            model=ctx.model,
            effort=ctx.effort.get("review", "max"),
            budget=ctx.budgets.get("review", 40),
            cwd=self.orc.cwd,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )
        # ACC #1 + #2: primary + curator BEFORE _check_phase_result
        # (v1.3.4 #15 + v1.3.12). Order matches Phase A — gap emit
        # also fires before the check.
        self.orc._accumulate_cost(0.0, r.cost_usd)
        curator_cost = self.orc._run_gap_curator(ctx.milestone_name, "review")
        self.orc._accumulate_cost(0.0, curator_cost)

        self.orc._emit_gap_report(ctx.milestone_name, "review")
        events.append("GapReport")
        self.orc._emit_gap_validation(ctx.milestone_name)
        events.append("GapValidationEvent")

        archive_reports(self.orc.claude_dir, ctx.milestone_name, "review")
        clear_phase_state(self.orc.claude_dir)
        self.orc._check_phase_result(r, "Phase C")

        # QG#2 helper below internally reassigns its own r for fix
        # calls; the original r used here doesn't leak.
        self._emit_completion(ctx, r)
        events.append("PhaseCompleted")
        return r, curator_cost

    def _run_post_review_checks(self, ctx: PhaseContext):
        """Phase C post-review checks — QG#2 + coverage + trailers +
        strict-mode loop. Returns the three cost aggregates that flow
        into PhaseResult.cost_usd.
        """
        self.orc.state.current_step = "quality_check_c"
        save_state(self.orc._state_dir, self.orc.state)

        # QG#2: ACC #3 (gates fix) + ACC #4 (policy fix) happen INSIDE
        # the helper, per-call. The helper handles the asymmetric
        # policy _recheck label.
        qg_cost = run_quality_gate_checkpoint(
            self.orc,
            ctx,
            checkpoint="quality_check_c",
            phase_label="Phase C",
        )

        # ACC #5 coverage: bool discarded (failure doesn't block);
        # cov_cost aggregates the helper's inner _run_claude iterations.
        _, cov_cost = self.orc._check_coverage(ctx.logger, milestone=ctx.milestone_name)
        self.orc._accumulate_cost(0.0, cov_cost)

        plan_sha = self.orc.state.plan_commit_sha or ""
        self.orc._check_trailers(plan_sha, ctx.logger)

        # Strict-mode UNCONDITIONAL call — helper returns 0.0 when off.
        # ACC #6: single aggregate accumulate at the strict-loop
        # BOUNDARY (v1.3.4 #15 holds only here, NOT per iteration —
        # preserved verbatim from original).
        strict_cost = self.orc._run_strict_mode_loop(
            name=ctx.milestone_name,
            ms=ctx.milestone_dict,
            model=ctx.model,
            fallback=ctx.fallback_model,
            initial_compliance=ctx.compliance_report,
            initial_verification=ctx.verification_report,
            logger=ctx.logger,
        )
        self.orc._accumulate_cost(0.0, strict_cost)
        return qg_cost, cov_cost, strict_cost
