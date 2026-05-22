"""Core milestone orchestrator that manages the four-phase workflow."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from superpower_workflow.context import build_context_summary
from superpower_workflow.logger import WorkflowLogger
from superpower_workflow.prompts import (
    phase_a_prompt,
    phase_b_prompt,
    phase_c_prompt,
    phase_d_prompt,
    system_prompt,
)
from superpower_workflow.runner import run_claude
from superpower_workflow.state import (
    PhaseState,
    acquire_lock,
    clear_phase_state,
    load_config,
    load_state,
    release_lock,
    save_phase_state,
    save_state,
)


class Orchestrator:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root
        self.claude_dir = project_root / ".claude"
        self.config = load_config(self.claude_dir)
        self.state = load_state(self.claude_dir)
        self.sys_prompt = system_prompt()
        self.cwd = str(project_root)

    def run(self, dry_run=False, milestone_filter=None, from_ms=None, to_ms=None) -> None:
        milestones = self._filter_milestones(milestone_filter, from_ms, to_ms)
        if dry_run:
            for ms in milestones:
                print(f"  [DRY RUN] Would execute: {ms['name']}")
            return

        run_id = time.strftime("%Y%m%d-%H%M%S")
        self.state.run_id = run_id
        self.state.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger = WorkflowLogger(self.claude_dir, run_id)

        try:
            if not acquire_lock(self.claude_dir):
                print("Another orchestration is running.")
                return
            for i, ms in enumerate(milestones):
                name = ms["name"]
                if name in self.state.completed:
                    continue
                logger.log("MILESTONE_START", name=name)
                self.state.current_milestone_index = i
                cost = self._run_milestone(ms, logger)
                self.state.completed.append(name)
                self.state.total_cost_usd += cost
                self.state.current_step = None
                save_state(self.claude_dir, self.state)
                logger.log("MILESTONE_COMPLETE", name=name, total_cost=round(cost, 2))
                delay = self.config.get("delay_between_phases_seconds", 10)
                if delay > 0:
                    time.sleep(delay)
        finally:
            release_lock(self.claude_dir)
            logger.close()

    def _run_milestone(self, ms, logger) -> float:
        name = ms["name"]
        sections = ms.get("spec_sections", "")
        spec = self.config["spec"]
        model = self.config["model"]
        fallback = self.config.get("fallback_model")
        budgets = self.config["budgets"]
        effort = self.config.get("effort", {})
        context = build_context_summary(self.state.completed)
        verify = self.config.get("verify_commands", {})
        convergence = self.config.get("convergence", {})
        cost = 0.0

        # Phase A: Plan + Ultrathink
        self.state.current_step = "plan"
        save_state(self.claude_dir, self.state)
        save_phase_state(
            self.claude_dir,
            PhaseState(phase="ultrathink", max_iterations=convergence.get("max_iterations", 5)),
        )
        logger.log("PHASE_A_START")
        r = run_claude(
            phase_a_prompt(name, context, spec, sections),
            model=model,
            effort=effort.get("plan", "max"),
            budget=budgets.get("plan", 25),
            cwd=self.cwd,
            system_prompt=self.sys_prompt,
            fallback_model=fallback,
        )
        cost += r.cost_usd
        clear_phase_state(self.claude_dir)
        logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))

        # Capture plan_commit_sha
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.cwd,
        )
        self.state.plan_commit_sha = sha_result.stdout.strip()
        self.state.last_phase_session_id = r.session_id
        # Rollback tag
        subprocess.run(
            ["git", "tag", f"pre-impl/{name}"],
            capture_output=True,
            cwd=self.cwd,
        )

        # Phase B: Implement
        self.state.current_step = "implement"
        save_state(self.claude_dir, self.state)
        plan_path = self._find_plan_path(name)
        logger.log("PHASE_B_START")
        r = run_claude(
            phase_b_prompt(name, context, plan_path),
            model=model,
            effort=effort.get("implement", "high"),
            budget=budgets.get("implement", 100),
            cwd=self.cwd,
            system_prompt=self.sys_prompt,
            fallback_model=fallback,
        )
        cost += r.cost_usd
        self.state.last_phase_session_id = r.session_id
        logger.log("PHASE_B_COMPLETE", cost=round(r.cost_usd, 2))

        # Phase C: Review + Fix
        self.state.current_step = "review"
        save_state(self.claude_dir, self.state)
        save_phase_state(
            self.claude_dir,
            PhaseState(phase="review", max_iterations=convergence.get("max_iterations", 5)),
        )
        logger.log("PHASE_C_START")
        r = run_claude(
            phase_c_prompt(
                name,
                context,
                self.state.plan_commit_sha or "",
                verify.get("test", "true"),
                verify.get("lint", "true"),
                verify.get("format", "true"),
            ),
            model=model,
            effort=effort.get("review", "max"),
            budget=budgets.get("review", 40),
            cwd=self.cwd,
            system_prompt=self.sys_prompt,
            fallback_model=fallback,
        )
        cost += r.cost_usd
        clear_phase_state(self.claude_dir)
        logger.log("PHASE_C_COMPLETE", cost=round(r.cost_usd, 2))

        # Phase D: Push + Tag
        self.state.current_step = "push"
        save_state(self.claude_dir, self.state)
        branch = "main" if self.config.get("git_strategy") == "main" else f"milestone/{name}"
        logger.log("PHASE_D_START")
        r = run_claude(
            phase_d_prompt(name, branch),
            model=model,
            effort=effort.get("push", "low"),
            budget=budgets.get("push", 3),
            cwd=self.cwd,
            system_prompt=self.sys_prompt,
            fallback_model=fallback,
        )
        cost += r.cost_usd
        logger.log("PHASE_D_COMPLETE", cost=round(r.cost_usd, 2))
        return cost

    def _filter_milestones(self, milestone, from_ms, to_ms):
        all_ms = self.config.get("milestones", [])
        if milestone:
            return [m for m in all_ms if m["name"] == milestone]
        if from_ms or to_ms:
            names = [m["name"] for m in all_ms]
            start = names.index(from_ms) if from_ms and from_ms in names else 0
            end = names.index(to_ms) + 1 if to_ms and to_ms in names else len(names)
            return all_ms[start:end]
        return all_ms

    def _find_plan_path(self, name):
        plans_dir = Path(self.cwd) / "docs" / "superpowers" / "plans"
        if plans_dir.exists():
            for f in sorted(plans_dir.glob(f"*{name}*")):
                return str(f)
        return f"docs/superpowers/plans/*{name}*.md"
