"""PhaseD — Push + Tag + SBOM + sign.

Verbatim lift of orchestrator.py:1403-1476. Key ordering invariants
the adversarial review flagged:

- `_call_post_phase` fires BEFORE the SBOM/sign blocks (Finding 1
  verdict point 4). The initial v1.2.0-real plan had PhaseD's gotcha
  #5 wrong (said post_phase moves AFTER security ops); this is FIXED
  here and pinned by `TestOrderingInvariant.test_post_phase_before_sbom`.
- _pre_commit hook fires once with an empty changed-files list (matches
  original line 1408).

PhaseD is unusual:
- No `_check_phase_result` for the primary claude — the original code
  emits PhaseCompleted unconditionally after _accumulate_cost. This
  is preserved verbatim.
- Single _accumulate_cost site (primary r.cost_usd only — no curator,
  no fix-loop, no coverage).
- SBOM + sign are best-effort side effects that don't affect cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superpower_workflow.phases.base import PhaseBase
from superpower_workflow.phases.result import PhaseResult
from superpower_workflow.prompts import phase_d_prompt
from superpower_workflow.runner import extract_token_usage
from superpower_workflow.state import save_state

if TYPE_CHECKING:
    from superpower_workflow.phases.context import PhaseContext


class PhaseD(PhaseBase):
    """Push phase — claude pushes the milestone + optional SBOM + sign."""

    name = "push"
    log_event_start = "PHASE_D_START"
    log_event_complete = "PHASE_D_COMPLETE"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        events: list[str] = []

        # 1. Plugin pre-phase hook.
        self._call_pre_phase(ctx)
        # 2. Plugin pre-commit hook with empty changed-files list.
        # Matches orchestrator.py:1408 verbatim — the empty list is
        # intentional (no specific commit set; pre-commit hooks that
        # inspect changed files get []).
        self.orc._call_pre_commit(ctx.milestone_dict, [])

        # 3. State transition.
        self.orc.state.current_step = "push"
        save_state(self.orc._state_dir, self.orc.state)

        # 4. Resolve branch name from git_strategy config.
        branch = (
            "main"
            if self.orc.config.get("git_strategy") == "main"
            else f"milestone/{ctx.milestone_name}"
        )

        # 5. Log + emit PhaseStarted.
        ctx.logger.log("PHASE_D_START")
        self._emit_phase_started(ctx)
        events.append("PhaseStarted")

        # 6. Primary claude call.
        r = self.orc._run_claude(
            phase_d_prompt(ctx.milestone_name, branch),
            model=ctx.model,
            effort=ctx.effort.get("push", "low"),
            budget=ctx.budgets.get("push", 3),
            cwd=self.orc.cwd,
            system_prompt=self.orc.sys_prompt,
            fallback_model=ctx.fallback_model,
        )
        # 7. Charge primary cost.
        self.orc._accumulate_cost(0.0, r.cost_usd)

        # 8-9. PhaseCompleted + log + audit + post_phase via shared
        # helper. CRITICAL ordering: _call_post_phase happens BEFORE
        # the SBOM/sign blocks below — Finding 1 verdict point 4.
        # NO _check_phase_result — Phase D's claude failure does NOT
        # raise. Preserved verbatim from original.
        self._emit_completion(ctx, r)
        events.append("PhaseCompleted")

        # 10. SBOM (best-effort).
        security = self.orc.config.get("security", {})
        sbom_tool = security.get("sbom_tool", "")
        sbom_output = security.get("sbom_output", "")
        if sbom_tool:
            self._run_sbom(ctx, sbom_tool, sbom_output)

        # 11. Sign (best-effort).
        if security.get("sign_artifacts", False):
            self._run_sign(ctx)

        return PhaseResult(
            phase=self.name,
            cost_usd=r.cost_usd,
            duration_ms=r.duration_ms,
            session_id=r.session_id,
            tokens=extract_token_usage(r.raw),
            events_emitted=events,
            extras={},
        )

    def _run_sbom(self, ctx: PhaseContext, sbom_tool: str, sbom_output: str) -> None:
        """SBOM generation — logs success/failure, never raises."""
        from superpower_workflow.security import generate_sbom

        ok, sbom_path = generate_sbom(
            tool_cmd=sbom_tool,
            output_path=sbom_output,
            cwd=self.orc.cwd,
            milestone=ctx.milestone_name,
        )
        if ok and sbom_path:
            ctx.logger.log("SBOM_GENERATED", milestone=ctx.milestone_name, path=sbom_path)
            self.orc._audit.append(
                "SBOM_GENERATED",
                run_id=self.orc.state.run_id,
                milestone=ctx.milestone_name,
                data={"path": sbom_path},
            )
        else:
            ctx.logger.log("SBOM_FAILED", milestone=ctx.milestone_name)

    def _run_sign(self, ctx: PhaseContext) -> None:
        """Artifact signing — logs success/failure, never raises."""
        from superpower_workflow.security import sign_artifact

        tag = ctx.milestone_name
        sig = sign_artifact(tag=tag, cwd=self.orc.cwd)
        if sig:
            ctx.logger.log("ARTIFACT_SIGNED", milestone=ctx.milestone_name)
            self.orc._audit.append(
                "ARTIFACT_SIGNED",
                run_id=self.orc.state.run_id,
                milestone=ctx.milestone_name,
                data={"tag": tag},
            )
        else:
            ctx.logger.log("SIGNING_SKIPPED", milestone=ctx.milestone_name)
