"""Core milestone orchestrator: pre-flight checks -> phases A/B/C/D -> state update."""

from __future__ import annotations

import json
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
from superpower_workflow.runner import ClaudeResult, run_claude
from superpower_workflow.state import (
    GAP_REPORT_FILE,
    PHASE_FILE,
    PhaseState,
    acquire_lock,
    clear_phase_state,
    load_config,
    load_state,
    release_lock,
    save_phase_state,
    save_state,
)

REQUIRED_CONFIG_KEYS = ("spec", "model", "budgets", "milestones")


def validate_config(config: dict) -> list[str]:
    errors = []
    for key in REQUIRED_CONFIG_KEYS:
        if key not in config:
            errors.append(f"Missing required field: '{key}'")
    if "budgets" in config:
        for phase in ("plan", "implement", "review", "push"):
            if phase not in config["budgets"]:
                errors.append(f"Missing budget for phase: '{phase}'")
    return errors


class Orchestrator:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root
        self.claude_dir = project_root / ".claude"
        self.config = load_config(self.claude_dir)
        config_errors = validate_config(self.config)
        if config_errors:
            raise ValueError(
                "Invalid workflow.json:\n" + "\n".join(f"  - {e}" for e in config_errors)
            )
        self.state = load_state(self.claude_dir)
        self.sys_prompt = system_prompt()
        self.cwd = str(project_root)

    def run(
        self,
        dry_run: bool = False,
        milestone_filter: str | None = None,
        from_ms: str | None = None,
        to_ms: str | None = None,
        phase_prefix: str | None = None,
    ) -> None:
        milestones = self._filter_milestones(milestone_filter, from_ms, to_ms, phase_prefix)

        if dry_run:
            for ms in milestones:
                print(f"  [DRY RUN] Would execute: {ms['name']}")
            return

        if not self._preflight_checks():
            return

        run_id = time.strftime("%Y%m%d-%H%M%S")
        self.state.run_id = run_id
        self.state.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.state.spec_sha = self._capture_spec_sha()
        logger = WorkflowLogger(self.claude_dir, run_id)

        milestone_retry_delays = [120, 300, 600]
        max_retries = len(milestone_retry_delays)
        consecutive_failures = 0

        try:
            for i, ms in enumerate(milestones):
                name = ms["name"]
                if name in self.state.completed:
                    continue
                if name in self.state.failed or name in self.state.skipped:
                    continue

                deps_failed = [
                    d
                    for d in ms.get("depends_on", [])
                    if d in self.state.failed or d in self.state.skipped
                ]
                if deps_failed:
                    self.state.skipped.append(name)
                    save_state(self.claude_dir, self.state)
                    logger.log(
                        "MILESTONE_SKIPPED",
                        name=name,
                        reason=f"depends on failed: {deps_failed}",
                    )
                    print(f"  SKIP: {name} (depends on failed: {deps_failed})")
                    continue

                max_budget = self.config.get("max_total_budget_usd", float("inf"))
                if self.state.total_cost_usd >= max_budget:
                    print(
                        f"  FATAL: Total budget ${max_budget} exceeded "
                        f"(${self.state.total_cost_usd:.2f} spent). Stopping."
                    )
                    logger.log(
                        "BUDGET_EXCEEDED",
                        spent=self.state.total_cost_usd,
                        limit=max_budget,
                    )
                    break

                logger.log("MILESTONE_START", name=name)
                self.state.current_milestone_index = i
                success = False

                for attempt in range(max_retries + 1):
                    try:
                        cost = self._run_milestone(ms, logger)
                        self.state.completed.append(name)
                        self.state.total_cost_usd += cost
                        self.state.current_step = None
                        save_state(self.claude_dir, self.state)
                        logger.log("MILESTONE_COMPLETE", name=name, total_cost=round(cost, 2))
                        success = True
                        consecutive_failures = 0
                        break
                    except _PhaseError as e:
                        if attempt < max_retries:
                            delay = milestone_retry_delays[attempt]
                            logger.log(
                                "MILESTONE_RETRY",
                                name=name,
                                attempt=attempt + 1,
                                phase=e.phase,
                                reason=str(e),
                                wait=delay,
                            )
                            print(
                                f"  RETRY: {name} failed at {e.phase} "
                                f"(attempt {attempt + 1}/{max_retries}). "
                                f"Waiting {delay}s..."
                            )
                            time.sleep(delay)
                        else:
                            logger.log(
                                "MILESTONE_FAILED",
                                name=name,
                                phase=e.phase,
                                reason=str(e),
                            )
                            print(
                                f"  FAILED: {name} after {max_retries + 1} attempts. "
                                f"Skipping to next."
                            )
                            self.state.failed.append(name)
                            save_state(self.claude_dir, self.state)

                if not success:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        print(
                            "  FATAL: 3 consecutive milestone failures. "
                            "Likely systemic issue. Stopping."
                        )
                        logger.log("CIRCUIT_BREAKER", consecutive=consecutive_failures)
                        break

                delay = self.config.get("delay_between_phases_seconds", 10)
                if delay > 0:
                    time.sleep(delay)

            self._completion_notification(logger)
        finally:
            release_lock(self.claude_dir)
            logger.close()

    def _preflight_checks(self) -> bool:
        if not acquire_lock(self.claude_dir):
            print("  FATAL: Another orchestration is running.")
            return False

        git_status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=self.cwd,
        )
        if git_status.stdout.strip():
            release_lock(self.claude_dir)
            print("  FATAL: Uncommitted changes detected. Commit or stash before running.")
            return False

        verify = self.config.get("verify_commands", {})
        for name, cmd in verify.items():
            if cmd is None:
                continue
            result = subprocess.run(cmd, shell=True, capture_output=True, cwd=self.cwd)
            if result.returncode != 0:
                release_lock(self.claude_dir)
                print(f"  FATAL: Verify command '{name}' failed: {cmd}")
                return False

        milestones = self.config.get("milestones", [])
        if not milestones:
            release_lock(self.claude_dir)
            print("  FATAL: No milestones in workflow.json. Run: sw decompose")
            return False

        names = [m["name"] for m in milestones]
        for ms in milestones:
            for dep in ms.get("depends_on", []):
                if (
                    dep not in names or names.index(dep) >= names.index(ms["name"])
                ) and dep not in self.state.completed:
                    release_lock(self.claude_dir)
                    print(f"  FATAL: Dependency '{dep}' for '{ms['name']}' not satisfied.")
                    return False

        max_budget = self.config.get("max_total_budget_usd", float("inf"))
        if self.state.total_cost_usd >= max_budget:
            release_lock(self.claude_dir)
            print(
                f"  FATAL: Budget already exceeded "
                f"(${self.state.total_cost_usd:.2f} >= ${max_budget})"
            )
            return False

        for name in (PHASE_FILE, GAP_REPORT_FILE):
            (self.claude_dir / name).unlink(missing_ok=True)

        return True

    def _capture_spec_sha(self) -> str:
        spec_path = self.config.get("spec", "")
        if not spec_path:
            return ""
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", spec_path],
            capture_output=True,
            text=True,
            cwd=self.cwd,
        )
        return result.stdout.strip()

    def _completion_notification(self, logger: WorkflowLogger) -> None:
        status = "complete"
        if self.state.failed:
            status = "partial" if self.state.completed else "failed"
        summary = {
            "status": status,
            "completed": self.state.completed,
            "failed": self.state.failed,
            "skipped": self.state.skipped,
            "total_cost_usd": round(self.state.total_cost_usd, 2),
            "run_id": self.state.run_id,
        }
        summary_path = self.claude_dir / "workflow-complete.json"
        summary_path.write_text(json.dumps(summary, indent=2))
        logger.log(
            "RUN_COMPLETE",
            cost=summary["total_cost_usd"],
            milestones=len(self.state.completed),
        )
        print("\a")
        parts = [f"{len(self.state.completed)} completed"]
        if self.state.failed:
            parts.append(f"{len(self.state.failed)} failed")
        if self.state.skipped:
            parts.append(f"{len(self.state.skipped)} skipped")
        print(f"  Run {status}. {', '.join(parts)}. ${self.state.total_cost_usd:.2f} total.")

        webhook = self.config.get("notification_webhook")
        if webhook:
            try:
                import urllib.request

                req = urllib.request.Request(
                    webhook,
                    data=json.dumps(summary).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                print("  Warning: webhook notification failed")

    def _check_phase_result(self, r: ClaudeResult, phase: str) -> None:
        if r.is_error:
            raise _PhaseError(phase, r.text or "claude -p returned an error")

    def _run_milestone(self, ms: dict, logger: WorkflowLogger) -> float:
        name = ms["name"]
        sections = ms.get("spec_sections", "")
        spec = self.config["spec"]
        model = self.config["model"]
        fallback = self.config.get("fallback_model")
        budgets = self.config["budgets"]
        effort = self.config.get("effort", {})
        context = build_context_summary(
            self.state.completed,
            self.root,
            ms,
            self.config.get("milestones", []),
        )
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
        self._check_phase_result(r, "Phase A")
        logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))

        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.cwd,
        )
        self.state.plan_commit_sha = sha_result.stdout.strip()
        self.state.last_phase_session_id = r.session_id
        save_state(self.claude_dir, self.state)

        subprocess.run(["git", "tag", f"pre-impl/{name}"], capture_output=True, cwd=self.cwd)

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
        self._check_phase_result(r, "Phase B")
        logger.log("PHASE_B_COMPLETE", cost=round(r.cost_usd, 2))

        # Refresh context to include what Phase B built
        context = build_context_summary(
            self.state.completed,
            self.root,
            ms,
            self.config.get("milestones", []),
        )

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
        self._check_phase_result(r, "Phase C")
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

    def _filter_milestones(
        self,
        milestone: str | None,
        from_ms: str | None,
        to_ms: str | None,
        phase_prefix: str | None = None,
    ) -> list[dict]:
        all_ms = self.config.get("milestones", [])
        if milestone:
            return [m for m in all_ms if m["name"] == milestone]
        if phase_prefix:
            prefix = f"{phase_prefix}-"
            return [m for m in all_ms if m["name"].startswith(prefix)]
        if from_ms or to_ms:
            names = [m["name"] for m in all_ms]
            start = names.index(from_ms) if from_ms and from_ms in names else 0
            end = names.index(to_ms) + 1 if to_ms and to_ms in names else len(names)
            return all_ms[start:end]
        return all_ms

    def _find_plan_path(self, name: str) -> str:
        plans_dir = Path(self.cwd) / "docs" / "superpowers" / "plans"
        if plans_dir.exists():
            for f in sorted(plans_dir.glob(f"*{name}*")):
                return str(f)
        print(f"  WARNING: No plan file found matching '{name}' in {plans_dir}")
        return f"docs/superpowers/plans/{name}.md"


class _PhaseError(Exception):
    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(message)
