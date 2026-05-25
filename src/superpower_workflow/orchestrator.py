"""Core milestone orchestrator: pre-flight checks -> phases A/B/C/D -> state update."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from superpower_workflow.audit import AuditTrail, derive_key
from superpower_workflow.context import build_context_summary
from superpower_workflow.integrations.ci_fix import ci_fix_loop
from superpower_workflow.integrations.github import (
    create_pr,
    fetch_issue,
    issue_to_milestone,
    render_pr_body,
)
from superpower_workflow.integrations.notifier import send_notification
from superpower_workflow.integrations.tracker import create_tracker
from superpower_workflow.logger import WorkflowLogger
from superpower_workflow.parallel.budget import ThreadSafeBudget
from superpower_workflow.parallel.executor import ParallelExecutor, ParallelResult
from superpower_workflow.parallel.planner import ExecutionWave, ParallelPlanner
from superpower_workflow.parallel.router import ModelRouter
from superpower_workflow.parallel.worktree import WorktreeManager
from superpower_workflow.policy import PolicyEngine
from superpower_workflow.prompts import (
    phase_a_prompt,
    phase_b_prompt,
    phase_c_prompt,
    phase_d_prompt,
    system_prompt,
)
from superpower_workflow.runner import ClaudeResult, run_claude
from superpower_workflow.security import SecretsHandler, generate_sbom, sign_artifact
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
from superpower_workflow.telemetry import (
    CoverageResult,
    GapReport,
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
    PhaseCompleted,
    PhaseStarted,
    QualityGateResult,
    RetryAttempt,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
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
        secrets_config = self.config.get("secrets", {})
        if secrets_config:
            self._secrets = SecretsHandler(secrets_config)
            try:
                self._secrets.resolve()
            except ValueError as e:
                print(f"  Warning: {e}")
                self._secrets = SecretsHandler({})
            fragment = self._secrets.prompt_fragment()
            if fragment:
                self.sys_prompt = self.sys_prompt + "\n\n" + fragment
        else:
            self._secrets = SecretsHandler({})
        self.cwd = str(project_root)
        self._telemetry: TelemetryEmitter | None = None
        self._audit = AuditTrail.disabled()
        self._run_start: float = 0.0
        self._integrations = self.config.get("integrations", {})
        self._slack_config = self._integrations.get("slack", {})
        self._from_ticket: str | None = None
        self._tracker_adapter = None

    def run(
        self,
        dry_run: bool = False,
        milestone_filter: str | None = None,
        from_ms: str | None = None,
        to_ms: str | None = None,
        phase_prefix: str | None = None,
        from_issue: str | None = None,
        from_ticket: str | None = None,
        parallel: bool = False,
        max_workers: int = 4,
        remote_url: str | None = None,
        best_of_n: int = 1,
        model_override: str | None = None,
    ) -> None:
        self._from_ticket = from_ticket
        self._tracker_adapter = None

        if from_issue:
            gh_config = self._integrations.get("github", {})
            issue_data = fetch_issue(
                from_issue,
                default_repo=gh_config.get("default_repo", ""),
                cwd=self.cwd,
            )
            ms = issue_to_milestone(issue_data, gh_config.get("issue_label_map"))
            self.config.setdefault("milestones", []).append(ms)

        if from_ticket:
            self._tracker_adapter = create_tracker(self.config)
            if self._tracker_adapter:
                ticket_data = self._tracker_adapter.fetch_ticket(from_ticket)
                ms = self._tracker_adapter.ticket_to_milestone(ticket_data)
                self.config.setdefault("milestones", []).append(ms)

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

        telemetry_config = self.config.get("telemetry", {})
        telemetry_path = Path(self.cwd) / telemetry_config.get("path", ".claude/telemetry.jsonl")
        if telemetry_config.get("enabled", True):
            self._telemetry = TelemetryEmitter(telemetry_path, run_id)
        else:
            self._telemetry = TelemetryEmitter.disabled()

        self._telemetry.emit(
            RunStarted(
                spec_sha=self.state.spec_sha,
                model=self.config["model"],
                milestone_count=len(milestones),
                max_budget_usd=self.config.get("max_total_budget_usd", 0),
            )
        )
        self._run_start = time.monotonic()

        security_config = self.config.get("security", {})
        if security_config.get("audit_trail", False):
            audit_key = derive_key()
            if audit_key:
                audit_path = Path(self.cwd) / ".claude" / "audit-trail.jsonl"
                self._audit = AuditTrail(audit_path, key=audit_key)
            else:
                self._audit = AuditTrail.disabled()
        else:
            self._audit = AuditTrail.disabled()

        self._audit.append(
            "RUN_START",
            run_id=run_id,
            data={
                "model": self.config["model"],
                "milestone_count": len(milestones),
            },
        )

        parallel_config = self.config.get("parallel", {})
        use_parallel = parallel or parallel_config.get("enabled", False)
        workers = max_workers or parallel_config.get("max_workers", 4)
        bon_count = best_of_n if best_of_n > 1 else parallel_config.get("best_of_n", 1)
        router = ModelRouter.from_config(self.config)

        if use_parallel and len(milestones) > 1:
            try:
                self._run_parallel(
                    milestones,
                    logger,
                    router,
                    workers,
                    bon_count,
                    model_override,
                    remote_url,
                )
                self._completion_notification(logger)
            finally:
                release_lock(self.claude_dir)
                logger.close()
                if self._telemetry:
                    self._telemetry.close()
            return

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
                    self._telemetry.emit(
                        MilestoneSkipped(
                            milestone=name,
                            reason=f"depends on failed: {deps_failed}",
                        )
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
                self._telemetry.emit(MilestoneStarted(milestone=name, index=i))
                self._audit.append("MILESTONE_START", run_id=run_id, milestone=name)
                self._notify("milestone_start", {"milestone": name})
                milestone_start = time.monotonic()
                self.state.current_milestone_index = i
                success = False

                decision = router.route(ms)
                if model_override:
                    ms_model = model_override
                elif self.config.get("model_routing", {}).get("enabled"):
                    ms_model = decision.model
                else:
                    ms_model = None

                for attempt in range(max_retries + 1):
                    try:
                        cost = self._run_milestone(ms, logger, model_override=ms_model)
                        self.state.completed.append(name)
                        self.state.total_cost_usd += cost
                        self.state.current_step = None
                        save_state(self.claude_dir, self.state)
                        logger.log("MILESTONE_COMPLETE", name=name, total_cost=round(cost, 2))
                        self._audit.append(
                            "MILESTONE_COMPLETE",
                            run_id=run_id,
                            milestone=name,
                            data={"cost": round(cost, 2)},
                        )
                        self._telemetry.emit(
                            MilestoneCompleted(
                                milestone=name,
                                cost_usd=round(cost, 2),
                                duration_seconds=round(time.monotonic() - milestone_start, 1),
                            )
                        )
                        self._notify(
                            "milestone_complete",
                            {"milestone": name, "cost_usd": round(cost, 2), "test_count": 0},
                        )
                        if self._from_ticket and self._tracker_adapter:
                            try:
                                self._tracker_adapter.update_status(
                                    self._from_ticket,
                                    "Done",
                                    comment=f"Milestone {name} completed",
                                )
                            except (OSError, ValueError):
                                logger.log("TRACKER_UPDATE_FAILED", ticket=self._from_ticket)
                        success = True
                        consecutive_failures = 0
                        break
                    except _PhaseError as e:
                        if attempt < max_retries:
                            delay = milestone_retry_delays[attempt]
                            self._telemetry.emit(
                                RetryAttempt(
                                    milestone=name,
                                    phase=e.phase,
                                    attempt=attempt + 1,
                                    reason=str(e),
                                    delay_seconds=delay,
                                )
                            )
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
                            self._telemetry.emit(
                                MilestoneFailed(
                                    milestone=name,
                                    phase=e.phase,
                                    reason=str(e),
                                    attempts=max_retries + 1,
                                )
                            )
                            self._notify(
                                "milestone_failed",
                                {"milestone": name, "phase": e.phase, "reason": str(e)},
                            )
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
            if self._telemetry:
                self._telemetry.close()

    def _notify(self, event: str, payload: dict) -> None:
        if self._slack_config:
            send_notification(self._slack_config, event, payload)

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
        if self._telemetry:
            from superpower_workflow.context import _count_test_files

            self._telemetry.emit(
                RunCompleted(
                    status=status,
                    completed_count=len(self.state.completed),
                    failed_count=len(self.state.failed),
                    skipped_count=len(self.state.skipped),
                    total_cost_usd=round(self.state.total_cost_usd, 2),
                    duration_seconds=round(time.monotonic() - self._run_start, 1),
                    test_file_count=_count_test_files(self.root),
                )
            )

        self._audit.append(
            "RUN_COMPLETE",
            run_id=self.state.run_id,
            data={
                "status": status,
                "completed": len(self.state.completed),
                "cost": round(self.state.total_cost_usd, 2),
            },
        )

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

    def _run_milestone(
        self,
        ms: dict,
        logger: WorkflowLogger,
        cwd_override: str | None = None,
        model_override: str | None = None,
        num_agents: int | None = None,
    ) -> float:
        name = ms["name"]
        sections = ms.get("spec_sections", "")
        spec = self.config["spec"]
        model = model_override or self.config["model"]
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
        self._telemetry.emit(PhaseStarted(milestone=name, phase="plan"))
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
        self._emit_gap_report(name, "plan")
        clear_phase_state(self.claude_dir)
        self._check_phase_result(r, "Phase A")
        self._telemetry.emit(
            PhaseCompleted(
                milestone=name,
                phase="plan",
                cost_usd=r.cost_usd,
                duration_ms=r.duration_ms,
                session_id=r.session_id,
                input_tokens=r.raw.get("input_tokens", 0) if r.raw else 0,
                output_tokens=r.raw.get("output_tokens", 0) if r.raw else 0,
            )
        )
        logger.log("PHASE_A_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit.append(
            "PHASE_COMPLETE",
            run_id=self.state.run_id,
            milestone=name,
            data={"phase": "plan", "cost": round(r.cost_usd, 2)},
        )

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
        self._telemetry.emit(PhaseStarted(milestone=name, phase="implement"))
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
        self._telemetry.emit(
            PhaseCompleted(
                milestone=name,
                phase="implement",
                cost_usd=r.cost_usd,
                duration_ms=r.duration_ms,
                session_id=r.session_id,
                input_tokens=r.raw.get("input_tokens", 0) if r.raw else 0,
                output_tokens=r.raw.get("output_tokens", 0) if r.raw else 0,
            )
        )
        logger.log("PHASE_B_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit.append(
            "PHASE_COMPLETE",
            run_id=self.state.run_id,
            milestone=name,
            data={"phase": "implement", "cost": round(r.cost_usd, 2)},
        )

        # Quality Gates Checkpoint #1
        self.state.current_step = "quality_check_b"
        save_state(self.claude_dir, self.state)
        passed, failures = self._verify_quality_gates(
            logger, milestone=name, checkpoint="quality_check_b"
        )
        if not passed:
            fix_prompt = (
                f"Quality gates failed after Phase B for {name}:\n"
                + "\n".join(f"- {f}" for f in failures)
                + "\nFix ALL issues. Commit the fix."
            )
            r = run_claude(
                fix_prompt,
                model=model,
                effort="high",
                budget=10.0,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=fallback,
            )
            cost += r.cost_usd
            passed, failures = self._verify_quality_gates(
                logger, milestone=name, checkpoint="quality_check_b"
            )
            if not passed:
                logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))

        policy_passed, policy_violations = self._check_policies(
            logger, milestone=name, checkpoint="quality_check_b"
        )
        if not policy_passed:
            fix_prompt = (
                f"Policy violations after {name}:\n"
                + "\n".join(f"- {v}" for v in policy_violations)
                + "\nFix ALL violations. Commit the fix."
            )
            r = run_claude(
                fix_prompt,
                model=model,
                effort="high",
                budget=10.0,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=fallback,
            )
            cost += r.cost_usd
            policy_passed, remaining = self._check_policies(
                logger, milestone=name, checkpoint="quality_check_b_recheck"
            )
            if not policy_passed:
                logger.log("POLICY_FIX_FAILED", violations=len(remaining))

        _, cov_cost = self._check_coverage(logger, milestone=name)
        cost += cov_cost
        plan_sha = self.state.plan_commit_sha or ""
        self._check_trailers(plan_sha, logger)

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
        self._telemetry.emit(PhaseStarted(milestone=name, phase="review"))
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
        self._emit_gap_report(name, "review")
        clear_phase_state(self.claude_dir)
        self._check_phase_result(r, "Phase C")
        self._telemetry.emit(
            PhaseCompleted(
                milestone=name,
                phase="review",
                cost_usd=r.cost_usd,
                duration_ms=r.duration_ms,
                session_id=r.session_id,
                input_tokens=r.raw.get("input_tokens", 0) if r.raw else 0,
                output_tokens=r.raw.get("output_tokens", 0) if r.raw else 0,
            )
        )
        logger.log("PHASE_C_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit.append(
            "PHASE_COMPLETE",
            run_id=self.state.run_id,
            milestone=name,
            data={"phase": "review", "cost": round(r.cost_usd, 2)},
        )

        # Quality Gates Checkpoint #2
        self.state.current_step = "quality_check_c"
        save_state(self.claude_dir, self.state)
        passed, failures = self._verify_quality_gates(
            logger, milestone=name, checkpoint="quality_check_c"
        )
        if not passed:
            fix_prompt = (
                f"Quality gates failed after Phase C for {name}:\n"
                + "\n".join(f"- {f}" for f in failures)
                + "\nFix ALL issues. Commit the fix."
            )
            r = run_claude(
                fix_prompt,
                model=model,
                effort="high",
                budget=10.0,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=fallback,
            )
            cost += r.cost_usd
            passed, failures = self._verify_quality_gates(
                logger, milestone=name, checkpoint="quality_check_c"
            )
            if not passed:
                logger.log("QUALITY_GATES_STILL_FAILING", failures=str(failures))

        policy_passed, policy_violations = self._check_policies(
            logger, milestone=name, checkpoint="quality_check_c"
        )
        if not policy_passed:
            fix_prompt = (
                f"Policy violations after {name}:\n"
                + "\n".join(f"- {v}" for v in policy_violations)
                + "\nFix ALL violations. Commit the fix."
            )
            r = run_claude(
                fix_prompt,
                model=model,
                effort="high",
                budget=10.0,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=fallback,
            )
            cost += r.cost_usd
            policy_passed, remaining = self._check_policies(
                logger, milestone=name, checkpoint="quality_check_c_recheck"
            )
            if not policy_passed:
                logger.log("POLICY_FIX_FAILED", violations=len(remaining))

        _, cov_cost = self._check_coverage(logger, milestone=name)
        cost += cov_cost
        plan_sha = self.state.plan_commit_sha or ""
        self._check_trailers(plan_sha, logger)

        # Phase D: Push + Tag
        self.state.current_step = "push"
        save_state(self.claude_dir, self.state)
        branch = "main" if self.config.get("git_strategy") == "main" else f"milestone/{name}"
        logger.log("PHASE_D_START")
        self._telemetry.emit(PhaseStarted(milestone=name, phase="push"))
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
        self._telemetry.emit(
            PhaseCompleted(
                milestone=name,
                phase="push",
                cost_usd=r.cost_usd,
                duration_ms=r.duration_ms,
                session_id=r.session_id,
                input_tokens=r.raw.get("input_tokens", 0) if r.raw else 0,
                output_tokens=r.raw.get("output_tokens", 0) if r.raw else 0,
            )
        )
        logger.log("PHASE_D_COMPLETE", cost=round(r.cost_usd, 2))
        self._audit.append(
            "PHASE_COMPLETE",
            run_id=self.state.run_id,
            milestone=name,
            data={"phase": "push", "cost": round(r.cost_usd, 2)},
        )

        security = self.config.get("security", {})
        sbom_tool = security.get("sbom_tool", "")
        sbom_output = security.get("sbom_output", "")
        if sbom_tool:
            ok, sbom_path = generate_sbom(
                tool_cmd=sbom_tool,
                output_path=sbom_output,
                cwd=self.cwd,
                milestone=name,
            )
            if ok and sbom_path:
                logger.log("SBOM_GENERATED", milestone=name, path=sbom_path)
                self._audit.append(
                    "SBOM_GENERATED",
                    run_id=self.state.run_id,
                    milestone=name,
                    data={"path": sbom_path},
                )
            else:
                logger.log("SBOM_FAILED", milestone=name)

        if security.get("sign_artifacts", False):
            tag = name
            sig = sign_artifact(tag=tag, cwd=self.cwd)
            if sig:
                logger.log("ARTIFACT_SIGNED", milestone=name)
                self._audit.append(
                    "ARTIFACT_SIGNED",
                    run_id=self.state.run_id,
                    milestone=name,
                    data={"tag": tag},
                )
            else:
                logger.log("SIGNING_SKIPPED", milestone=name)

        ci_config = self._integrations.get("ci", {})
        if ci_config.get("enabled", False):
            self.state.current_step = "ci_wait"
            save_state(self.claude_dir, self.state)
            logger.log("PHASE_E_START")
            self._telemetry.emit(PhaseStarted(milestone=name, phase="ci_fix"))

            self.state.current_step = "ci_fix"
            save_state(self.claude_dir, self.state)

            def _on_ci_attempt(attempt: int, max_attempts: int, status: str) -> None:
                self._notify(
                    "ci_fix",
                    {
                        "milestone": name,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "status": status,
                    },
                )

            ci_success, ci_cost = ci_fix_loop(
                cwd=self.cwd,
                ci_config=ci_config,
                run_claude_fn=run_claude,
                model=self.config["model"],
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
                on_attempt=_on_ci_attempt,
            )
            cost += ci_cost

            if ci_success:
                logger.log("PHASE_E_COMPLETE", status="passed", cost=round(ci_cost, 2))
            else:
                self.state.current_step = "ci_fix_failed"
                save_state(self.claude_dir, self.state)
                logger.log("PHASE_E_COMPLETE", status="failed", cost=round(ci_cost, 2))

            self._telemetry.emit(
                PhaseCompleted(
                    milestone=name,
                    phase="ci_fix",
                    cost_usd=round(ci_cost, 2),
                    duration_ms=0,
                    session_id="",
                )
            )
            self._audit.append(
                "PHASE_COMPLETE",
                run_id=self.state.run_id,
                milestone=name,
                data={"phase": "ci_fix", "cost": round(ci_cost, 2), "success": ci_success},
            )

        gh_config = self._integrations.get("github", {})
        if gh_config.get("auto_pr", False) and self.config.get("git_strategy") != "main":
            branch = f"milestone/{name}"
            base = "main"
            changes = ""
            plan_sha = self.state.plan_commit_sha or ""
            if plan_sha:
                log_result = subprocess.run(
                    ["git", "log", "--oneline", f"{plan_sha}..HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                    timeout=10,
                )
                changes = log_result.stdout.strip() if log_result.returncode == 0 else ""
            body = render_pr_body(
                milestone=name,
                description=ms.get("description", ""),
                changes=changes,
                cost_usd=cost,
            )
            pr_url = create_pr(
                title=name,
                body=body,
                branch=branch,
                base=base,
                cwd=self.cwd,
                repo=gh_config.get("default_repo", ""),
            )
            if pr_url:
                logger.log("PR_CREATED", milestone=name, url=pr_url)
                self._audit.append(
                    "PR_CREATED",
                    run_id=self.state.run_id,
                    milestone=name,
                    data={"url": pr_url},
                )

        return cost

    def _run_parallel(
        self,
        milestones: list[dict],
        logger: WorkflowLogger,
        router: ModelRouter,
        max_workers: int,
        best_of_n: int,
        model_override: str | None,
        remote_url: str | None = None,
    ) -> None:
        planner = ParallelPlanner(milestones, completed=set(self.state.completed))
        waves = planner.plan_waves()
        max_budget = self.config.get("max_total_budget_usd", float("inf"))
        budget = ThreadSafeBudget(max_budget - self.state.total_cost_usd)
        par_config = self.config.get("parallel", {})
        wt_dir_name = par_config.get("worktree_dir", ".worktrees")
        wt_mgr = WorktreeManager(self.root, worktree_dir=self.root / wt_dir_name)
        executor = ParallelExecutor(budget=budget, max_workers=max_workers, worktree_mgr=wt_mgr)
        failed_set = set(self.state.failed)

        for wave in waves:
            runnable = [
                m
                for m in wave.milestones
                if not any(
                    dep in failed_set
                    for dep in next(
                        (ms.get("depends_on", []) for ms in milestones if ms["name"] == m), []
                    )
                )
            ]
            skipped = [m for m in wave.milestones if m not in runnable]
            for s in skipped:
                self.state.skipped.append(s)
                logger.log("MILESTONE_SKIP", milestone=s, reason="dependency_failed")

            if not runnable:
                continue

            wave = ExecutionWave(index=wave.index, milestones=runnable)
            self.state.current_step = "parallel_wait"
            save_state(self.claude_dir, self.state)
            logger.log("PARALLEL_WAVE_START", wave=wave.index, milestones=str(wave.milestones))

            if self._telemetry:
                from superpower_workflow.telemetry import ParallelWaveStarted

                self._telemetry.emit(
                    ParallelWaveStarted(
                        wave_index=wave.index,
                        milestones=wave.milestones,
                        worker_count=max_workers,
                    )
                )

            def run_fn(name: str, run_cwd: str) -> ParallelResult:
                ms = next((m for m in milestones if m["name"] == name), None)
                if ms is None:
                    return ParallelResult(milestone=name, success=False, error="not found")
                decision = router.route(ms)
                if model_override:
                    ms_model = model_override
                elif self.config.get("model_routing", {}).get("enabled"):
                    ms_model = decision.model
                else:
                    ms_model = None
                try:
                    cost = self._run_milestone(ms, logger, model_override=ms_model)
                    return ParallelResult(
                        milestone=name, success=True, cost_usd=cost, worktree=run_cwd
                    )
                except Exception as e:
                    return ParallelResult(
                        milestone=name, success=False, error=str(e), worktree=run_cwd
                    )

            try:
                results = executor.execute_wave(wave, run_fn=run_fn, cwd=self.cwd)
            except Exception:
                wt_mgr.cleanup_all()
                raise

            self.state.current_step = "parallel_merge"
            save_state(self.claude_dir, self.state)

            for result in results:
                if result.success:
                    self.state.completed.append(result.milestone)
                    self.state.total_cost_usd += result.cost_usd
                else:
                    self.state.failed.append(result.milestone)
                    failed_set.add(result.milestone)
            save_state(self.claude_dir, self.state)

            if self._telemetry:
                from superpower_workflow.telemetry import ParallelWaveCompleted

                self._telemetry.emit(
                    ParallelWaveCompleted(
                        wave_index=wave.index,
                        succeeded=[r.milestone for r in results if r.success],
                        failed=[r.milestone for r in results if not r.success],
                        total_cost_usd=sum(r.cost_usd for r in results),
                    )
                )

            logger.log("PARALLEL_WAVE_COMPLETE", wave=wave.index)

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

    def _verify_quality_gates(
        self,
        logger: WorkflowLogger,
        milestone: str = "",
        checkpoint: str = "",
    ) -> tuple[bool, list[str]]:
        """Run all configured quality gates. Returns (all_passed, failure_details)."""
        gates = self.config.get("quality_gates", {})
        if not gates:
            return True, []
        failures: list[str] = []
        for gate_name in ("lint", "sast", "secret_scan", "dep_scan"):
            cmd = gates.get(gate_name)
            if not cmd:
                continue
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                    timeout=300,
                )
                if result.returncode != 0:
                    detail = (result.stdout or result.stderr)[:500]
                    failures.append(f"{gate_name}: {detail}")
                    logger.log("QUALITY_GATE_FAILED", gate=gate_name)
                else:
                    detail = ""
                    logger.log("QUALITY_GATE_PASSED", gate=gate_name)
                if self._telemetry:
                    self._telemetry.emit(
                        QualityGateResult(
                            milestone=milestone,
                            checkpoint=checkpoint,
                            gate=gate_name,
                            passed=result.returncode == 0,
                            detail=detail if result.returncode != 0 else "",
                        )
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                failures.append(f"{gate_name}: {e}")
                logger.log("QUALITY_GATE_ERROR", gate=gate_name, error=str(e))
                if self._telemetry:
                    self._telemetry.emit(
                        QualityGateResult(
                            milestone=milestone,
                            checkpoint=checkpoint,
                            gate=gate_name,
                            passed=False,
                            detail=str(e),
                        )
                    )
        return len(failures) == 0, failures

    def _check_policies(
        self,
        logger: WorkflowLogger,
        milestone: str = "",
        checkpoint: str = "",
    ) -> tuple[bool, list[str]]:
        policies_config = self.config.get("policies", {})
        if not policies_config:
            return True, []
        engine = PolicyEngine(policies_config)
        base_sha = self.state.plan_commit_sha or ""
        passed, violations = engine.check(Path(self.cwd), base_sha=base_sha)
        for v in violations:
            logger.log("POLICY_VIOLATION", checkpoint=checkpoint, detail=v)
            self._audit.append(
                "POLICY_VIOLATION",
                run_id=self.state.run_id,
                milestone=milestone,
                data={"checkpoint": checkpoint, "violation": v},
            )
        if passed:
            logger.log("POLICY_CHECK_PASSED", checkpoint=checkpoint)
        return passed, violations

    def _check_coverage(self, logger: WorkflowLogger, milestone: str = "") -> tuple[bool, float]:
        """Check branch coverage against threshold, iterating with Claude if below.

        Returns (passed, accumulated_cost).
        """
        gates = self.config.get("quality_gates", {})
        cmd = gates.get("coverage_command")
        threshold = gates.get("coverage_threshold", 0)
        max_attempts = gates.get("coverage_max_attempts", 3)
        report_path = gates.get("coverage_report_path", "coverage.json")
        if not cmd or threshold == 0:
            return True, 0.0
        extra_cost = 0.0
        for attempt in range(max_attempts):
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    cwd=self.cwd,
                    timeout=600,
                )
                if result.returncode != 0:
                    logger.log(
                        "COVERAGE_CMD_FAILED",
                        returncode=result.returncode,
                        attempt=attempt + 1,
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.log("COVERAGE_CMD_ERROR", error=str(e), attempt=attempt + 1)
            coverage = self._parse_coverage(report_path)
            if coverage >= threshold:
                logger.log("COVERAGE_PASSED", coverage=coverage, threshold=threshold)
                if self._telemetry:
                    self._telemetry.emit(
                        CoverageResult(
                            milestone=milestone,
                            coverage_pct=coverage,
                            threshold=threshold,
                            passed=True,
                        )
                    )
                return True, extra_cost
            logger.log(
                "COVERAGE_BELOW",
                coverage=coverage,
                threshold=threshold,
                attempt=attempt + 1,
            )
            if self._telemetry:
                self._telemetry.emit(
                    CoverageResult(
                        milestone=milestone,
                        coverage_pct=coverage,
                        threshold=threshold,
                        passed=False,
                    )
                )
            if attempt < max_attempts - 1:
                r = run_claude(
                    f"Branch coverage is {coverage}% (threshold: {threshold}%). "
                    f"Write additional tests for uncovered code. "
                    f"Attempt {attempt + 1}/{max_attempts}.",
                    model=self.config["model"],
                    effort="high",
                    budget=10.0,
                    cwd=self.cwd,
                    system_prompt=self.sys_prompt,
                    fallback_model=self.config.get("fallback_model"),
                )
                extra_cost += r.cost_usd
        return False, extra_cost

    def _parse_coverage(self, report_path: str) -> float:
        """Parse coverage.json for branch coverage percentage."""
        path = Path(self.cwd) / report_path
        if not path.exists():
            return 0.0
        try:
            data = json.loads(path.read_text())
            return float(data.get("totals", {}).get("percent_covered_display", "0"))
        except (json.JSONDecodeError, ValueError, KeyError):
            return 0.0

    def _check_trailers(self, since_sha: str, logger: WorkflowLogger) -> None:
        """Verify git trailers exist on commits since since_sha. Warn-only."""
        gates = self.config.get("quality_gates", {})
        if not gates.get("require_git_trailers"):
            return
        try:
            result = subprocess.run(
                ["git", "log", "--format=%H %b", f"{since_sha}..HEAD"],
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=10,
            )
            if result.returncode != 0:
                return
            commits = result.stdout.strip().split("\n")
            missing = [c[:8] for c in commits if c.strip() and "Generated-By:" not in c]
            if missing:
                logger.log(
                    "TRAILER_MISSING",
                    count=len(missing),
                    commits=str(missing[:5]),
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _emit_gap_report(self, milestone: str, phase: str) -> None:
        gap_path = self.claude_dir / GAP_REPORT_FILE
        if not gap_path.exists():
            return
        try:
            data = json.loads(gap_path.read_text())
            self._telemetry.emit(
                GapReport(
                    milestone=milestone,
                    phase=phase,
                    critical_gaps=data.get("critical_gaps", 0),
                    architectural_gaps=data.get("architectural_gaps", 0),
                    important_gaps=data.get("important_gaps", 0),
                    minor_gaps=data.get("minor_gaps", 0),
                    deferred_gaps=data.get("deferred_gaps", 0),
                    total_gaps_found=data.get("total_gaps_found", 0),
                    converged=data.get("converged", False),
                )
            )
        except (json.JSONDecodeError, OSError):
            pass

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
