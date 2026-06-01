"""Quality-gate checkpoint helper shared by PhaseB (QG#1) and PhaseC (QG#2).

Module-level function (not a PhaseBase method) per the plan's Finding 3
resolution: the same checkpoint logic runs at both Phase B (after
implement) and Phase C (after review), so it lives outside any phase
class and gets called as `run_quality_gate_checkpoint(orc, ctx,
checkpoint=...)` from each.

Behavior preserved from orchestrator.py:1201-1252 (QG#1) and
orchestrator.py:1333-1384 (QG#2):

1. Run `_verify_quality_gates(checkpoint=label)` — the orchestrator
   helper iterates gates in fixed order (lint, sast, secret_scan,
   dep_scan) and emits one typed `QualityGateResult` event per
   configured gate.
2. If any gate failed, run a fix-loop claude call with effort='high'
   budget=10.0, charge cost to state via `_accumulate_cost`
   (Finding 1 in-flight gate granularity preserved), then recheck
   gates with the SAME label.
3. Run `_check_policies(checkpoint=label)` — logs POLICY_VIOLATION
   for each violation.
4. If any policy failed, run a fix-loop claude call, charge cost,
   then recheck with the ASYMMETRIC label `f"{label}_recheck"`.
   This asymmetry is intentional and preserved verbatim — Finding 2
   item 1 explicitly called out the recheck-label asymmetry as
   load-bearing test coverage.

Returns total extra cost spent in fix-loops (0.0 on happy path).
Caller adds it to their local accumulator AND phase cost-tracking
local. State.total_cost_usd has already advanced incrementally inside
this function via `_accumulate_cost`, so the v1.3.12 in-flight gate
binds even if the caller's `_accumulate_cost(local, extra_cost)` is
deferred.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superpower_workflow.orchestrator import Orchestrator
    from superpower_workflow.phases.context import PhaseContext


def run_quality_gate_checkpoint(
    orc: Orchestrator,
    ctx: PhaseContext,
    *,
    checkpoint: str,
    phase_label: str,
) -> float:
    """Run gates + policies at a checkpoint, including fix-loops.

    Args:
        orc: the Orchestrator (for delegations to _verify_quality_gates,
            _check_policies, _run_claude, _accumulate_cost).
        ctx: the PhaseContext (for milestone_name, model, fallback_model,
            logger).
        checkpoint: the checkpoint label — "quality_check_b" for QG#1
            (Phase B) or "quality_check_c" for QG#2 (Phase C). The
            policy recheck uses `f"{checkpoint}_recheck"` (asymmetric).
        phase_label: human-readable phase label used in the fix prompt
            ("Phase B" or "Phase C"). The exact prompt strings are
            preserved verbatim from the original orchestrator code so
            the golden trace + downstream claude integrations don't
            see a behavior shift.

    Returns:
        Total extra cost from fix-loop claude calls (0.0 if no
        fix-loops fired). State.total_cost_usd has already been
        advanced incrementally — this return value is for the caller's
        local accumulator + phase cost-tracking.
    """
    extra_cost = 0.0
    logger = ctx.logger

    # 1. Gates check
    passed, failures = orc._verify_quality_gates(
        logger,
        milestone=ctx.milestone_name,
        checkpoint=checkpoint,
    )

    # 2. Gate fix-loop (if any gate failed)
    if not passed:
        fix_prompt = (
            f"Quality gates failed after {phase_label} for {ctx.milestone_name}:\n"
            + "\n".join(f"- {f}" for f in failures)
            + "\nFix ALL issues. Commit the fix."
        )
        r = orc._run_claude(
            fix_prompt,
            model=ctx.model,
            effort="high",
            budget=10.0,
            cwd=orc.cwd,
            system_prompt=orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )
        # Finding 1: charge state IMMEDIATELY so v1.3.12 in-flight gate
        # binds across parallel siblings.
        orc._accumulate_cost(0.0, r.cost_usd)
        extra_cost += r.cost_usd

        # Recheck — SAME label as the first check (NOT a _recheck variant).
        passed, failures = orc._verify_quality_gates(
            logger,
            milestone=ctx.milestone_name,
            checkpoint=checkpoint,
        )
        if not passed:
            logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))

    # 3. Policy check
    policy_passed, violations = orc._check_policies(
        logger,
        milestone=ctx.milestone_name,
        checkpoint=checkpoint,
    )

    # 4. Policy fix-loop (if any policy violated)
    if not policy_passed:
        fix_prompt = (
            f"Policy violations after {ctx.milestone_name}:\n"
            + "\n".join(f"- {v}" for v in violations)
            + "\nFix ALL violations. Commit the fix."
        )
        r = orc._run_claude(
            fix_prompt,
            model=ctx.model,
            effort="high",
            budget=10.0,
            cwd=orc.cwd,
            system_prompt=orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )
        orc._accumulate_cost(0.0, r.cost_usd)
        extra_cost += r.cost_usd

        # Recheck — ASYMMETRIC label with _recheck suffix.
        # This is intentional and load-bearing (Finding 2 item 1).
        policy_passed, remaining = orc._check_policies(
            logger,
            milestone=ctx.milestone_name,
            checkpoint=f"{checkpoint}_recheck",
        )
        if not policy_passed:
            logger.log("POLICY_FIX_FAILED", violations=len(remaining))

    return extra_cost
