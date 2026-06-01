"""PhaseTbV — Trust-but-verify stages (spec_compliance + feature_verification).

New phase introduced by Finding 3 resolution. Lifts orchestrator.py:
1267-1273 (the two TbV stages between QG#1+context-refresh and the
Phase C review) into its own class.

Rationale: keeping PhaseB at "implement + QG#1 + coverage + trailers +
context refresh" preserves the original Phase B conceptual boundary
and gives spec_compliance + feature_verification their own home
without conflating them with strict-mode (which lives inside PhaseC).
The v1.2.0-lite TrustButVerifyPipeline (which conflated those two
concerns) was retired in Task 9 of the v1.2.0-real refactor.

PhaseTbV is unusual:

- It has NO primary claude call (both `_run_spec_compliance` and
  `_run_feature_verification` are independent claude calls or skip).
- It emits NO PhaseStarted/PhaseCompleted events (the stages each
  emit their own typed events: SpecComplianceCompleted,
  FeatureVerificationCompleted).
- When validation is fully disabled (the default config), the phase
  is a near-no-op — both stages return (None, 0.0) and the phase
  returns extras={"compliance_report": None, "verification_report":
  None}. The driver still calls `ctx.update(**extras)` to propagate
  Nones, which PhaseContext accepts (the fields are typed
  `dict | None`).

Critical invariants pinned by tests/test_phase_tbv.py:

1. Finding 1: per-call _accumulate_cost — one per claude-emitting
   stage. Stages that short-circuit (return cost=0) STILL invoke
   _accumulate_cost (which no-ops on delta=0 but the call site is
   preserved so a refactor catching it is caught).
2. extras["compliance_report"] and extras["verification_report"]
   flow correctly even when None (PhaseContext.update accepts).
3. _set_current_step transitions inside the helper methods
   (_run_spec_compliance and _run_feature_verification each do
   their own save_state when active) — PhaseTbV itself doesn't
   call _set_current_step.
4. No PhaseStarted/PhaseCompleted from PhaseTbV — the typed
   SpecComplianceCompleted / FeatureVerificationCompleted events
   fire inside the stage helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult

if TYPE_CHECKING:
    from superpower_workflow.phases.context import PhaseContext


class PhaseTbV(PhaseBase):
    """Trust-but-verify — spec compliance + feature verification stages."""

    name = "trust_but_verify"
    log_event_start = "PHASE_TBV_START"
    log_event_complete = "PHASE_TBV_COMPLETE"

    # Zero-token shape used when the phase short-circuits (validation
    # entirely disabled). Matches extract_token_usage(None)'s output so
    # downstream consumers don't need to special-case PhaseTbV.
    _ZERO_TOKENS = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_hit_rate": 0.0,
    }

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []
        phase_cost = 0.0

        # 1. Spec compliance — returns (report, cost). When validation.
        # spec_compliance is False (default), returns (None, 0.0).
        compliance_report, compliance_cost = self.orc._run_spec_compliance(
            ctx.milestone_name, ctx.milestone_dict
        )
        # Finding 1: per-call _accumulate_cost (no-op when delta=0).
        self.orc._accumulate_cost(0.0, compliance_cost)
        phase_cost += compliance_cost
        if compliance_cost > 0:
            events.append("SpecComplianceCompleted")

        # 2. Feature verification — returns (report, cost). When
        # validation.feature_verification is False, returns (None, 0.0).
        verification_report, verify_cost = self.orc._run_feature_verification(ctx.milestone_name)
        self.orc._accumulate_cost(0.0, verify_cost)
        phase_cost += verify_cost
        if verify_cost > 0:
            events.append("FeatureVerificationCompleted")

        # 3. Return PhaseResult — extras carry both reports (possibly
        # None) so PhaseC's PhaseContext can reference them in its
        # phase_c_prompt construction.
        return PhaseResult(
            phase=self.name,
            cost_usd=phase_cost,
            duration_ms=0,  # No primary claude call.
            session_id="",
            tokens=dict(self._ZERO_TOKENS),
            events_emitted=events,
            extras={
                "compliance_report": compliance_report,
                "verification_report": verification_report,
            },
        )
