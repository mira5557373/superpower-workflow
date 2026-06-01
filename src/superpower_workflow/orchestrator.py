"""Core milestone orchestrator: pre-flight checks -> phases A/B/C/D -> state update."""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from pathlib import Path

from superpower_workflow.audit import AuditTrail, derive_key
from superpower_workflow.context import build_context_summary
from superpower_workflow.docs.api_docs import build_api_docs
from superpower_workflow.docs.changelog import generate_changelog
from superpower_workflow.docs.diagrams import generate_mermaid
from superpower_workflow.docs.readme_gen import generate_readme
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
from superpower_workflow.phases import (
    PhaseA,
    PhaseB,
    PhaseC,
    PhaseContext,
    PhaseD,
    PhaseE,
    PhaseTbV,
)
from superpower_workflow.plugins.interface import Plugin
from superpower_workflow.plugins.loader import load_plugins
from superpower_workflow.policy import PolicyEngine
from superpower_workflow.prompts import (
    system_prompt,
)
from superpower_workflow.runner import ClaudeResult, run_claude
from superpower_workflow.security import SecretsHandler
from superpower_workflow.state import (
    GAP_REPORT_FILE,
    GAP_REPORT_RAW_FILE,
    PHASE_FILE,
    HeartbeatThread,
    acquire_lock,
    load_config,
    load_state,
    release_lock,
    save_state,
)
from superpower_workflow.telemetry import (
    BudgetAlert,
    CoverageResult,
    FeatureVerificationCompleted,
    GapCurationCompleted,
    GapReport,
    GapValidationEvent,
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
    QualityGateResult,
    RetryAttempt,
    RunCompleted,
    RunCostProjection,
    RunStarted,
    SpecComplianceCompleted,
    StrictModeIteration,
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


# v1.3.8 Edit A: thread-local override for cwd / claude_dir.
#
# v1.3.5 #6 claimed worktree isolation by switching the parallel executor to
# `execute_wave_isolated`, but `_run_milestone` and its 40+ subprocess sites
# still passed `self.cwd` (the parent repo) — so every git/test/claude
# command ran in the parent repo, not the worktree. The v1.3.7 review
# confirmed this and v1.3.7 gated parallel mode pending the proper fix.
#
# v1.3.8 delivers it. Rather than threading `cwd` through 100+ call sites,
# `Orchestrator.cwd` and `.claude_dir` are now properties backed by a
# threading.local override that the parallel branch sets per-worker via
# `_worker_context`. Sequential mode is unaffected (no override set →
# property returns the instance default). The 100+ existing read sites
# automatically resolve to the per-worker worktree without modification.
_orchestrator_local = threading.local()


class Orchestrator:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root
        # v1.3.8: store via the property setter (which writes to _claude_dir_storage)
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

        plugins_config = self.config.get("plugins", {})
        if plugins_config.get("enabled", True):
            blocked = plugins_config.get("blocked", [])
            self._plugins: list[Plugin] = load_plugins(blocked=blocked)
        else:
            self._plugins = []

        # v1.3.5 #4 fix: serialize mutations to self.state when parallel
        # worker threads share it. The state cost-accumulator
        # (`_accumulate_cost`) and the parallel-wave merge step both take
        # this lock. Sequential mode is unaffected (lock acquisition on
        # an uncontended lock is ~50ns).
        self._state_lock = threading.Lock()

        # v1.3.17 / v1.1.9.1 — current milestone + phase labels used in
        # BudgetAlert + RunCostProjection event payloads. Best-effort
        # labels (empty string is a valid value). Set by the milestone
        # loop + phase classes when they transition.
        self._current_milestone_name: str = ""
        self._current_phase_name: str = ""

        # v1.3.19 — set to True inside parallel worker bodies so the
        # drift detector skips emission (parallel-mode v1 limitation
        # — Verdict 2 fix #2). ParallelExecutor sets this when running
        # `execute_wave_isolated`.
        self._in_parallel_worker: bool = False

        # v1.3.20 — set via `sw run --ignore-ceiling`. When True AND
        # SW_ALLOW_CEILING_BYPASS=1 is set, a block-mode ceiling becomes
        # a bypass (CostCeilingBlocked override_used=True + CEILING_BYPASS
        # audit). Defense-in-depth: the flag ALONE in a non-TTY shell with
        # no env var still blocks (verdict revision #3).
        self._ignore_ceiling: bool = False

        # v1.3.12: shared in-flight cost counter across parallel workers.
        # `_run_claude` charges to this BEFORE state is updated so sibling
        # workers' budget checks see in-flight spend within milliseconds.
        # Without this, N workers can each blow the cap in parallel before
        # any of them returns and triggers `_accumulate_cost`.
        self._in_flight_cost: float = 0.0
        self._in_flight_lock = threading.Lock()

        # v1.3.13 fix #10 (audit finding): track all live `claude -p` Popen
        # children so the SIGTERM/SIGINT shutdown handler can terminate
        # them before SystemExit propagates. v1.3.7 #2 added process-group
        # flags so signals propagate via the OS group, but a SIGTERM
        # delivered to the parent that triggers the shutdown handler
        # raised SystemExit which slipped past runner's `except
        # KeyboardInterrupt`. The shutdown handler now walks this set
        # and calls _terminate_process_group on each registered child.
        self._live_children: set = set()
        self._live_children_lock = threading.Lock()

        # v1.3.13 fix #3 (audit finding): canonical path for run-scoped state.
        # v1.3.10 narrow-fixed `_accumulate_cost`'s save_state to write to
        # parent's .claude/ but left 18 other state-writing sites routing
        # through `self.claude_dir` — which v1.3.8 Edit A's property
        # resolves to the WORKER's worktree inside `_worker_context`.
        # `_state_dir` is set once at __init__ and NEVER moves. Every site
        # that persists run-scoped state (workflow-state.json, lock files,
        # audit trail, heartbeat) routes through this. `self.claude_dir`
        # (the property) remains for per-milestone artifacts that genuinely
        # belong in the worker's worktree.
        self._state_dir: Path = project_root / ".claude"

    # v1.3.8 Edit A: properties that route reads through thread-local
    # override (set by `_worker_context` in parallel branches). Every
    # existing `self.cwd` / `self.claude_dir` read site automatically gets
    # the per-worker worktree value without any code change.
    @property
    def cwd(self) -> str:
        return getattr(_orchestrator_local, "cwd_override", None) or self._cwd_storage

    @cwd.setter
    def cwd(self, value: str) -> None:
        self._cwd_storage = value

    @property
    def claude_dir(self) -> Path:
        return getattr(_orchestrator_local, "claude_dir_override", None) or self._claude_dir_storage

    @claude_dir.setter
    def claude_dir(self, value: Path) -> None:
        self._claude_dir_storage = value

    def _worker_context(self, cwd: str, claude_dir: Path):
        """v1.3.8 Edit A: per-worker cwd/claude_dir scope.

        Used by `_run_parallel.run_fn` to override `self.cwd` / `self.claude_dir`
        for the duration of one worker's `_run_milestone` call. Restores the
        previous values (which may themselves be overrides from an outer
        context) on exit so nested contexts behave correctly.
        """
        import contextlib as _contextlib

        @_contextlib.contextmanager
        def _ctx():
            prev_cwd = getattr(_orchestrator_local, "cwd_override", None)
            prev_cd = getattr(_orchestrator_local, "claude_dir_override", None)
            _orchestrator_local.cwd_override = cwd
            _orchestrator_local.claude_dir_override = claude_dir
            try:
                yield
            finally:
                _orchestrator_local.cwd_override = prev_cwd
                _orchestrator_local.claude_dir_override = prev_cd

        return _ctx()

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
        ignore_ceiling: bool = False,
    ) -> None:
        self._ignore_ceiling = ignore_ceiling
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
            self._print_dry_run(milestones)
            return

        if not self._preflight_checks():
            return

        # v1.3.4 #9 fix: background-timer heartbeat refresh. The per-milestone
        # heartbeat call below (line ~283) is insufficient when Phase B runs
        # longer than HEARTBEAT_STALE_SECONDS (default 600s) — a second
        # orchestrator can decide the first is hung and force-clean the lock.
        # The background thread refreshes every 60s independent of phase work.
        self._heartbeat_thread = HeartbeatThread(self._state_dir, interval=60.0)
        self._heartbeat_thread.start()

        # v1.3.7 #4 fix: install SIGTERM handler so container orchestrators
        # (Kubernetes / Docker / systemd) get a clean shutdown — state saved,
        # lock released, heartbeat stopped. Without this, SIGTERM kills the
        # process with no chance to persist progress; the next pod sees a
        # stale lock for HEARTBEAT_STALE_SECONDS (10 min) and re-runs
        # already-completed milestones from the on-disk state.
        self._install_shutdown_handlers()

        run_id = time.strftime("%Y%m%d-%H%M%S")
        self.state.run_id = run_id
        self.state.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.state.spec_sha = self._capture_spec_sha()
        logger = WorkflowLogger(self.claude_dir, run_id)

        # v1.3.2 #3: route through the shared path resolver instead of
        # `Path(self.cwd) / config_path` so a malicious `telemetry.path`
        # (e.g. "../../etc/passwd") cannot direct `TelemetryEmitter.emit`'s
        # `mkdir(parents=True)+open(..., "a")` write outside the project root.
        from superpower_workflow.paths import resolve_telemetry_path, telemetry_enabled

        if telemetry_enabled(self.config):
            telemetry_path = resolve_telemetry_path(Path(self.cwd), self.config)
            if telemetry_path is None:
                # Path escaped project root — warning already emitted; fall
                # back to disabled emitter so the run still proceeds.
                self._telemetry = TelemetryEmitter.disabled()
            else:
                self._telemetry = TelemetryEmitter(telemetry_path, run_id)
        else:
            self._telemetry = TelemetryEmitter.disabled()

        # v1.3.6 #20 fix: hold engine reference for explicit disposal in
        # the run-finally blocks. Pre-fix, the SQLAlchemy engine + its
        # connection pool relied on garbage collection — under test
        # harnesses that instantiate many Orchestrator objects per process,
        # the pool leaked connections until the OS file-descriptor limit hit.
        self._db_engine = None
        url_env_name = self.config.get("database", {}).get("url_env", "SW_DATABASE_URL")
        db_url = os.environ.get(url_env_name, "")
        if db_url:
            try:
                from superpower_workflow.db.engine import create_engine_from_url
                from superpower_workflow.db.models import Base
                from superpower_workflow.db.writer import TelemetryDbWriter

                engine = create_engine_from_url(db_url)
                Base.metadata.create_all(engine)
                self._db_engine = engine
                self._telemetry = TelemetryDbWriter(
                    emitter=self._telemetry,
                    engine=engine,
                    project_name=self.root.name,
                    project_path=str(self.root),
                )
            except ImportError:
                pass

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

        # v1.3.20 — cost ceiling preflight at the run_start gate. Projected
        # total cost = estimator output (or max_total_budget_usd fallback).
        # On block, raises SystemExit(7); caller's finally blocks still run.
        try:
            from superpower_workflow.estimator import estimate as _estimate
        except ImportError:
            _estimate = None
        projected_total = 0.0
        if _estimate is not None:
            try:
                est = _estimate(self.config)
                projected_total = (
                    float(est.get("total_cost_usd", 0.0)) if isinstance(est, dict) else 0.0
                )
            except Exception:  # noqa: BLE001
                projected_total = 0.0
        if projected_total <= 0:
            mb = self.config.get("max_total_budget_usd", 0)
            projected_total = float(mb) if isinstance(mb, int | float) else 0.0
        self._check_cost_ceilings(
            gate="run_start",
            projected_run_cost_usd=projected_total,
        )

        parallel_config = self.config.get("parallel", {})
        use_parallel = parallel or parallel_config.get("enabled", False)
        workers = max_workers or parallel_config.get("max_workers", 4)
        bon_count = best_of_n if best_of_n > 1 else parallel_config.get("best_of_n", 1)
        router = ModelRouter.from_config(self.config)

        # v1.3.8: parallel mode is ungated — Edit A (thread-local
        # cwd/claude_dir override via `_worker_context`) makes per-worker
        # worktree isolation actually work. The SW_ALLOW_BROKEN_PARALLEL
        # gate from v1.3.7 is removed.
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
                # v1.3.4 #9: stop background heartbeat BEFORE releasing the
                # lock so the daemon thread doesn't refresh a meta file that's
                # about to be unlinked.
                if getattr(self, "_heartbeat_thread", None):
                    self._heartbeat_thread.stop()
                release_lock(self._state_dir)
                logger.close()
                if self._telemetry:
                    self._telemetry.close()
                # v1.3.6 #20: dispose SQLAlchemy engine to release pool conns.
                if getattr(self, "_db_engine", None) is not None:
                    import contextlib as _contextlib

                    with _contextlib.suppress(Exception):
                        self._db_engine.dispose()
            return

        milestone_retry_delays = [120, 300, 600]
        max_retries = len(milestone_retry_delays)
        consecutive_failures = 0

        try:
            for i, ms in enumerate(milestones):
                # v1.3.4 #9: heartbeat is now refreshed by the background
                # daemon thread (HeartbeatThread). Removed the redundant
                # per-milestone call here — keeping it would race with the
                # daemon on `.workflow.lock.json` (deterministic `.tmp`
                # filename, finding #5 — scheduled for v1.3.5).
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
                    save_state(self._state_dir, self.state)
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

                # v1.3.20 — milestone_start ceiling gate. Per-milestone
                # projection is rough: total budget / remaining milestone
                # count. Better than nothing; the run_start gate already
                # caught full-budget overruns.
                remaining_ms = max(1, len(milestones) - i)
                per_ms_proj = max(0.0, projected_total - self.state.total_cost_usd) / remaining_ms
                self._check_cost_ceilings(
                    gate="milestone_start",
                    projected_run_cost_usd=per_ms_proj,
                    current_milestone=name,
                )

                decision = router.route(ms)
                if model_override:
                    ms_model = model_override
                elif self.config.get("model_routing", {}).get("enabled"):
                    ms_model = decision.model
                else:
                    ms_model = None

                for attempt in range(max_retries + 1):
                    if attempt > 0:
                        # v1.3.20 — phase_e_retry gate (the design's "overnight
                        # CI-fix loop" scenario). Re-evaluate before each retry
                        # so a runaway retry cycle cannot accumulate spend
                        # past the rolling ceiling.
                        self._check_cost_ceilings(
                            gate="phase_e_retry",
                            projected_run_cost_usd=per_ms_proj,
                            current_milestone=name,
                        )
                    try:
                        cost = self._run_milestone(ms, logger, model_override=ms_model)
                        # v1.3.4 #15: cost is now charged INCREMENTALLY by
                        # `_accumulate_cost` after every Claude call. The local
                        # `cost` is the per-milestone roll-up used by the
                        # MilestoneCompleted telemetry event below; do NOT
                        # add it to state.total_cost_usd here — that would
                        # double-count.
                        #
                        # v1.3.7 #1 fix: the append + save_state pair must be
                        # atomic with respect to SIGINT. Pre-fix, a Ctrl-C
                        # landing between them left the milestone completed
                        # in memory but absent from disk → re-billing on
                        # resume. The state lock serializes other threads;
                        # the signal handler installed by
                        # _install_shutdown_handlers performs its own
                        # save_state so a signal that interrupts here will
                        # still flush the state.
                        with self._state_lock:
                            self.state.completed.append(name)
                            self.state.current_step = None
                            save_state(self._state_dir, self.state)
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
                            save_state(self._state_dir, self.state)

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
            # v1.3.4 #9: stop heartbeat before releasing the lock.
            if getattr(self, "_heartbeat_thread", None):
                self._heartbeat_thread.stop()
            release_lock(self._state_dir)
            logger.close()
            if self._telemetry:
                self._telemetry.close()
            # v1.3.6 #20: dispose SQLAlchemy engine to release pool conns.
            if getattr(self, "_db_engine", None) is not None:
                import contextlib as _contextlib

                with _contextlib.suppress(Exception):
                    self._db_engine.dispose()

    def _notify(self, event: str, payload: dict) -> None:
        if self._slack_config:
            send_notification(self._slack_config, event, payload)

    def _install_shutdown_handlers(self) -> None:
        """v1.3.7 #4 fix: install SIGINT + SIGTERM handlers that flush state
        + release the lock + stop the heartbeat before letting the signal
        propagate. Without these, container orchestrators (k8s/Docker/systemd)
        leave the lock-file stranded for 10 min and silently re-bill already-
        completed milestones on the next pod start.

        Idempotent: re-installation is a no-op. Only installs on the main
        thread (signal handlers can only be set from the main thread).
        """
        import signal
        import threading as _threading

        if _threading.current_thread() is not _threading.main_thread():
            return  # only main thread can set handlers

        if getattr(self, "_shutdown_handlers_installed", False):
            return

        def _handler(signum, frame):
            # Best-effort cleanup. Don't raise; let the OS terminate naturally.
            import contextlib as _contextlib

            # v1.3.13 fix #10: terminate any in-flight `claude -p` children
            # BEFORE state save / lock release. Pre-v1.3.13, SystemExit
            # raised below slipped past runner's `except KeyboardInterrupt`,
            # orphaning the child and leaking API spend until init(1)
            # reaped it.
            from superpower_workflow.runner import _terminate_process_group

            with self._live_children_lock:
                children_snapshot = list(self._live_children)
            for child in children_snapshot:
                with _contextlib.suppress(Exception):
                    _terminate_process_group(child)

            with _contextlib.suppress(Exception):
                save_state(self._state_dir, self.state)
            with _contextlib.suppress(Exception):
                if getattr(self, "_heartbeat_thread", None):
                    self._heartbeat_thread.stop()
            with _contextlib.suppress(Exception):
                release_lock(self._state_dir)
            # Re-raise as SystemExit so finally blocks still get a chance.
            # 130 = SIGINT, 143 = SIGTERM (per UNIX convention).
            code = 130 if signum == signal.SIGINT else 143
            raise SystemExit(code)

        signal.signal(signal.SIGINT, _handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handler)
        self._shutdown_handlers_installed = True

    def _print_dry_run(self, milestones: list[dict]) -> None:
        from superpower_workflow.estimator import estimate

        cfg = self.config
        spec_path = cfg.get("spec") or cfg.get("spec_path") or "<unset>"
        verify = cfg.get("verify_commands", {})
        convergence = cfg.get("convergence", {})
        budgets = cfg.get("budgets", {})

        print(f"  Spec:                {spec_path}")
        print(f"  Project:             {cfg.get('project_name', Path(self.cwd).name)}")
        print()
        print(f"  Milestones to run:   {len(milestones)}")
        for i, ms in enumerate(milestones, 1):
            name = ms.get("name", f"m{i}")
            paths = ms.get("paths") or ms.get("module_paths") or []
            paths_str = (
                f"  [{', '.join(paths[:3])}{'…' if len(paths) > 3 else ''}]" if paths else ""
            )
            print(f"    {i:2d}. {name}{paths_str}")
        print()

        try:
            est = estimate({**cfg, "milestones": milestones}, project_root=Path(self.cwd))
            print("  Estimate (per-milestone × N):")
            print(
                f"    cost:              ${est['cost_optimistic']:.2f} – "
                f"${est['cost_pessimistic']:.2f}"
            )
            if "duration_optimistic_min" in est:
                print(
                    f"    duration:          {est['duration_optimistic_min']}–"
                    f"{est['duration_pessimistic_min']} min"
                )
        except Exception as e:
            print(f"  Estimate unavailable: {e}")
        print()

        print("  Convergence loops:")
        print(f"    ultrathink passes: max {convergence.get('max_ultrathink_passes', 3)}")
        print(f"    review passes:     max {convergence.get('max_review_passes', 3)}")
        print()

        print("  Budgets (per phase):")
        for phase in ("plan", "implement", "review", "push"):
            v = budgets.get(phase)
            if v is not None:
                print(f"    {phase:9s} ${v}")
        print()

        print("  Verify commands:")
        for name in ("lint", "test", "coverage", "sast", "dep_scan"):
            cmd = verify.get(name)
            shown = cmd if cmd else "<not configured>"
            print(f"    {name:9s} {shown}")
        print()
        print("  No claude -p calls will be made. Drop --dry-run to execute.")

    def _preflight_checks(self) -> bool:
        if not acquire_lock(self._state_dir):
            print("  FATAL: Another orchestration is running.")
            print("  Run 'sw lock status' to inspect, or 'sw lock force-clean' to release.")
            return False

        git_status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=self.cwd,
        )
        if git_status.stdout.strip():
            release_lock(self._state_dir)
            print("  FATAL: Uncommitted changes detected. Commit or stash before running.")
            return False

        verify = self.config.get("verify_commands", {})
        for name, cmd in verify.items():
            if cmd is None:
                continue
            result = subprocess.run(cmd, shell=True, capture_output=True, cwd=self.cwd)
            if result.returncode != 0:
                release_lock(self._state_dir)
                print(f"  FATAL: Verify command '{name}' failed: {cmd}")
                return False

        milestones = self.config.get("milestones", [])
        if not milestones:
            release_lock(self._state_dir)
            print("  FATAL: No milestones in workflow.json. Run: sw decompose")
            return False

        names = [m["name"] for m in milestones]
        for ms in milestones:
            for dep in ms.get("depends_on", []):
                if (
                    dep not in names or names.index(dep) >= names.index(ms["name"])
                ) and dep not in self.state.completed:
                    release_lock(self._state_dir)
                    print(f"  FATAL: Dependency '{dep}' for '{ms['name']}' not satisfied.")
                    return False

        max_budget = self.config.get("max_total_budget_usd", float("inf"))
        if self.state.total_cost_usd >= max_budget:
            release_lock(self._state_dir)
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

    def _run_claude(self, *args, **kwargs):
        """v1.3.11+v1.3.12: wrap `run_claude` with budget gating that
        actually binds across parallel workers.

        v1.3.11 made the budget gate check state, but state.total_cost_usd
        only updates when run_claude RETURNS — so N parallel workers
        could each spend `cap` in-flight before any of them returned.

        v1.3.12 adds per-attempt charging via a shared in-flight counter
        (`self._in_flight_cost`). Each worker's `charge_cost_fn` posts
        its attempt's cost to the shared counter; sibling workers'
        `budget_check_fn` reads that counter so the cap binds across
        workers within milliseconds.

        After `run_claude` returns, the wrapper subtracts this call's
        contribution from the shared counter — the caller's
        `_accumulate_cost(cost, r.cost_usd)` then transfers it to state
        as before. No double-charging.
        """
        max_total = self.config.get("max_total_budget_usd", float("inf"))
        my_charged = [0.0]  # this call's contribution to the shared counter

        def _ok(extra_this_call: float) -> bool:
            # accumulated_from_runner is this worker's local accumulator;
            # we already posted it to in_flight_cost via charge_cost_fn.
            # Subtract my own contribution to avoid double-counting, then
            # add `extra_this_call` to model the cost of the NEXT attempt.
            with self._in_flight_lock:
                others_in_flight = self._in_flight_cost - my_charged[0]
            return self.state.total_cost_usd + others_in_flight + extra_this_call < max_total

        def _charge(per_attempt_cost: float) -> None:
            # Make this attempt's spend visible to sibling workers' next
            # budget check.
            with self._in_flight_lock:
                self._in_flight_cost += per_attempt_cost
            my_charged[0] += per_attempt_cost

        # v1.3.13 fix #10: register Popen children with the live-children
        # registry so the shutdown handler can SIGTERM them on SIGINT/SIGTERM.
        def _on_started(child):
            with self._live_children_lock:
                self._live_children.add(child)

        def _on_ended(child):
            with self._live_children_lock:
                self._live_children.discard(child)

        kwargs.setdefault("budget_check_fn", _ok)
        kwargs.setdefault("charge_cost_fn", _charge)
        kwargs.setdefault("on_child_started", _on_started)
        kwargs.setdefault("on_child_ended", _on_ended)
        try:
            return run_claude(*args, **kwargs)
        finally:
            # Hand off this call's contribution: the caller will charge
            # `r.cost_usd` to state via `_accumulate_cost`, so the shared
            # counter must drop by the same amount to keep totals correct.
            with self._in_flight_lock:
                self._in_flight_cost -= my_charged[0]

    def _accumulate_cost(self, local_acc: float, delta: float) -> float:
        """v1.3.4 #15 fix: persist cost INCREMENTALLY after every Claude call.

        Pre-fix: a milestone that retried because Phase B raised _PhaseError
        threw away every dollar Phase A had already spent (cost was a local
        variable returned only on success). On retry, the budget check at
        line ~327 saw the OLD total, so a runaway spec could spend
        many * max_total_budget_usd before giving up.

        Now: every phase that adds to the milestone accumulator also charges
        persistent state via this helper. On _PhaseError, the cost is already
        in self.state.total_cost_usd; the next retry's budget check sees it.

        Returns the new local accumulator so callers can keep using the
        `cost = self._accumulate_cost(cost, delta)` idiom.
        """
        budget_alert_to_emit: BudgetAlert | None = None
        if delta:
            import contextlib

            # v1.3.5 #4: protect concurrent workers from torn writes to
            # the shared state.total_cost_usd float and the save_state
            # disk write. Uncontended acquire is ~50ns; contended workers
            # block briefly but no correctness loss.
            with self._state_lock:
                self.state.total_cost_usd += delta
                # v1.3.10 + v1.3.13: write state to the PARENT project's
                # .claude/ via `self._state_dir` (set once in __init__,
                # never thread-local). v1.3.8's `self.claude_dir` property
                # resolves to the worker's worktree inside a
                # `_worker_context`; using it here would route run-scoped
                # state to the wrong place. v1.3.10 narrow-fixed this site
                # by computing the parent path inline; v1.3.13 unifies all
                # save_state sites under `_state_dir`.
                with contextlib.suppress(OSError):
                    save_state(self._state_dir, self.state)

                # v1.3.17 / v1.1.9.1 — BudgetAlert threshold crossing.
                # Computed under the SAME lock so two parallel workers
                # crossing 50% simultaneously can't both fire — whoever
                # acquires the lock first bumps last_budget_alert_pct
                # and the other sees the updated value. Emission itself
                # happens OUTSIDE the lock to keep the in-flight gate's
                # latency unchanged.
                max_budget = self.config.get("max_total_budget_usd", 0)
                try:
                    max_budget_f = float(max_budget)
                except (TypeError, ValueError):
                    max_budget_f = 0.0
                if max_budget_f > 0 and math.isfinite(max_budget_f):
                    pct = (self.state.total_cost_usd / max_budget_f) * 100
                    new_bucket = max(
                        (t for t in (50, 75, 90, 100) if pct >= t),
                        default=0,
                    )
                    if new_bucket > self.state.last_budget_alert_pct:
                        self.state.last_budget_alert_pct = new_bucket
                        with contextlib.suppress(OSError):
                            save_state(self._state_dir, self.state)
                        budget_alert_to_emit = BudgetAlert(
                            milestone=self._current_milestone_name or "",
                            phase=self._current_phase_name or "",
                            current_spent_usd=round(self.state.total_cost_usd, 4),
                            max_budget_usd=max_budget_f,
                            percent_of_cap=round(pct, 2),
                            threshold=new_bucket,
                        )

        # Emit OUTSIDE the state_lock so the in-flight gate's hot path
        # isn't held while the telemetry emitter does its own I/O.
        if budget_alert_to_emit is not None and self._telemetry is not None:
            with contextlib.suppress(Exception):
                self._telemetry.emit(budget_alert_to_emit)
        return local_acc + delta

    def _emit_run_cost_projection(
        self,
        ctx,
        *,
        phase_just_completed: str,
        remaining_in_milestone: list[str],
        completed_in_milestone: list[str],
    ) -> None:
        """v1.3.17 / v1.1.9.1 — emit RunCostProjection after a phase completes.

        Best-effort: never raises. The projection module handles missing
        telemetry / zero history / degenerate cases.
        """
        if self._telemetry is None:
            return
        try:
            from superpower_workflow.projection import compute_projection

            telemetry_path = self.claude_dir / "sw-telemetry.jsonl"
            milestones = self.config.get("milestones", [])
            result = compute_projection(
                state_total_cost=self.state.total_cost_usd,
                milestones_total=len(milestones),
                milestones_completed=len(self.state.completed),
                milestones_failed=len(self.state.failed),
                milestones_skipped=len(self.state.skipped),
                remaining_phases=remaining_in_milestone,
                completed_phases_this_milestone=completed_in_milestone,
                telemetry_path=telemetry_path,
            )
            max_budget = self.config.get("max_total_budget_usd", 0)
            try:
                max_budget_f = float(max_budget)
            except (TypeError, ValueError):
                max_budget_f = 0.0
            pct_of_cap = (
                (self.state.total_cost_usd / max_budget_f) * 100 if max_budget_f > 0 else 0.0
            )
            self._telemetry.emit(
                RunCostProjection(
                    milestone=self._current_milestone_name or "",
                    milestones_completed=len(self.state.completed),
                    milestones_total=len(milestones),
                    current_spent_usd=round(self.state.total_cost_usd, 4),
                    projected_total_usd=round(result.projected_total, 4),
                    low_p10_usd=round(result.low_p10, 4),
                    high_p90_usd=round(result.high_p90, 4),
                    confidence=round(result.confidence, 4),
                    source=result.source,
                    max_budget_usd=max_budget_f,
                    pct_of_cap=round(pct_of_cap, 2),
                )
            )
        except Exception:  # noqa: BLE001
            # Best-effort — projection is observability, never fatal.
            pass

    def _emit_drift_for_phase(
        self,
        *,
        phase: str,
        cost_usd: float,
        duration_ms: float,
        tokens: dict,
    ) -> None:
        """v1.3.19 — emit DriftDetected after a phase completes.

        Best-effort: catches every exception and returns silently. Drift
        is observability; it must never break the milestone loop.

        Safety gates (drift.py + here):
        - skip if `self._in_parallel_worker` (parallel-mode v1 limitation)
        - skip if `drift_detection.enabled=false` (default true)
        - skip if `_telemetry` not initialized
        - baseline_floor (default 15) suppresses emission below
        - rate-limit dedup via `state.drift_alerts_emitted_this_milestone`
        - INFO severity suppressed under `mode='observation_only'` default
        """
        if getattr(self, "_in_parallel_worker", False):
            return
        if self._telemetry is None:
            return
        drift_cfg = self.config.get("drift_detection", {})
        if not drift_cfg.get("enabled", True):
            return

        try:
            from superpower_workflow.drift import (
                assess_all,
                bucket_key_for_phase,
                dedup_key,
            )
            from superpower_workflow.telemetry import DriftDetected

            model_id = self.config.get("model", "")
            telemetry_path = self.claude_dir / "sw-telemetry.jsonl"
            bucket = bucket_key_for_phase(phase, model_id)

            cache_hit_rate = float(tokens.get("cache_hit_rate", 0.0))
            pending = [
                ("cost_usd", bucket, float(cost_usd)),
                ("duration_ms", bucket, float(duration_ms)),
                ("cache_hit_rate", bucket, cache_hit_rate),
            ]
            mode = drift_cfg.get("mode", "observation_only")
            emit_info = bool(drift_cfg.get("emit_info", False))
            baseline_floor = int(drift_cfg.get("baseline_floor", 15))
            sample_cap = int(drift_cfg.get("sample_cap", 200))

            assessments = assess_all(
                telemetry_path=telemetry_path,
                pending_observations=pending,
                baseline_floor=baseline_floor,
                sample_cap=sample_cap,
                exclude_run_id=self.state.run_id,
                model_id_for_phase=model_id,
            )

            # Pre-load existing dedup set under the lock to avoid races
            # with sibling _accumulate_cost callers.
            for a in assessments:
                if a.severity == "ok":
                    continue
                # observation_only: filter INFO unless emit_info=true.
                if mode == "observation_only" and a.severity == "info" and not emit_info:
                    continue
                key = dedup_key(a.metric, a.bucket, a.severity, a.direction)
                with self._state_lock:
                    if key in self.state.drift_alerts_emitted_this_milestone:
                        continue
                    self.state.drift_alerts_emitted_this_milestone.append(key)
                self._telemetry.emit(
                    DriftDetected(
                        milestone=self._current_milestone_name or "",
                        metric=a.metric,
                        aggregation=a.aggregation,
                        bucket=a.bucket,
                        value=round(a.value, 4),
                        baseline_n=a.baseline_n,
                        baseline_mean=round(a.baseline_mean, 4),
                        baseline_sigma=round(a.baseline_sigma, 4),
                        z_score=round(a.z_score, 4),
                        severity=a.severity,
                        direction=a.direction,
                        recommendation=a.recommendation,
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    def _check_cost_ceilings(
        self,
        *,
        gate: str,
        projected_run_cost_usd: float,
        current_milestone: str = "",
    ) -> None:
        """v1.3.20 — rolling-window cost ceiling preflight check.

        Called at three gate points:
        - `run_start`: once before any milestone begins; projected = estimate.
        - `milestone_start`: at top of each milestone iteration; projected =
          per-milestone estimate.
        - `phase_e_retry`: at the top of each retry attempt > 0; projected =
          remaining retry attempts × per-milestone cost.

        On block decision (and no authorized bypass):
        - emits CostCeilingBlocked + records CEILING_BLOCK audit entry
        - raises SystemExit(EXIT_CEILING_BLOCKED).

        On bypass (--ignore-ceiling + SW_ALLOW_CEILING_BYPASS=1):
        - emits CostCeilingBlocked with override_used=True
        - records CEILING_BYPASS audit entry
        - allows the run to continue.

        Best-effort on all internal failures — a broken ceiling check must
        never break the run loop. Only the BLOCK decision raises.
        """
        try:
            from superpower_workflow.budget_ceiling import (
                EXIT_CEILING_BLOCKED,
                CeilingLock,
                build_bypass_audit_payload,
                evaluate_ceilings,
                is_bypass_authorized,
                parse_ceilings,
            )
            from superpower_workflow.telemetry import (
                CostCeilingBlocked,
                CostCeilingEvaluated,
            )
        except ImportError:
            return

        raw_ceilings = self.config.get("cost_ceilings")
        ceilings = parse_ceilings(raw_ceilings)
        if not ceilings.any_configured():
            return  # zero-cost no-op if no ceiling declared

        # Hard kill-switch (rollback lever #3 from design).
        if os.environ.get("SW_DISABLE_COST_CEILINGS") == "1":
            return

        telemetry_path = self.claude_dir / "sw-telemetry.jsonl"
        lock_path = self._state_dir / ".ceiling.lock"

        with CeilingLock(lock_path):
            result = evaluate_ceilings(
                telemetry_path,
                ceilings=ceilings,
                projected_run_cost_usd=projected_run_cost_usd,
            )

            # Emit one CostCeilingEvaluated per evaluation that has a
            # configured ceiling (skip unconfigured-window passthroughs).
            for ev in result.evaluations:
                if ev.ceiling_usd is None:
                    continue
                if self._telemetry is not None:
                    self._telemetry.emit(
                        CostCeilingEvaluated(
                            window=ev.window,
                            window_start_utc=ev.accounting.window_start_utc,
                            window_end_utc=ev.accounting.window_end_utc,
                            current_spend_usd=ev.accounting.current_spend_usd,
                            projected_run_cost_usd=ev.projected_run_cost_usd,
                            ceiling_usd=ev.ceiling_usd or 0.0,
                            headroom_usd=ev.headroom_usd,
                            contributing_runs=len(ev.accounting.contributing_runs),
                            mode=ev.mode,
                            decision=ev.decision,
                            source=ev.accounting.source,
                            preflight_gate=gate,
                        )
                    )

            if not result.blocked:
                return

            # Block decision. Check for authorized bypass.
            ignore_flag = bool(getattr(self, "_ignore_ceiling", False))
            authorized, auth_reason = is_bypass_authorized(
                ignore_flag=ignore_flag,
                env=dict(os.environ),
                stdin_is_tty=False,
                tty_confirm=None,
            )
            blocking = result.blocking_window or "day"
            blocking_eval = next(
                (e for e in result.evaluations if e.window == blocking),
                None,
            )
            current = blocking_eval.accounting.current_spend_usd if blocking_eval else 0.0
            ceiling_usd_v = blocking_eval.ceiling_usd if blocking_eval else 0.0
            proj = blocking_eval.projected_run_cost_usd if blocking_eval else 0.0

            if authorized:
                if self._telemetry is not None:
                    self._telemetry.emit(
                        CostCeilingBlocked(
                            window=blocking,
                            current_spend_usd=current,
                            ceiling_usd=ceiling_usd_v or 0.0,
                            projected_run_cost_usd=proj,
                            blocked_milestone=current_milestone,
                            override_used=True,
                            preflight_gate=gate,
                        )
                    )
                self._audit.append(
                    "CEILING_BYPASS",
                    run_id=self.state.run_id,
                    milestone=current_milestone,
                    data=build_bypass_audit_payload(
                        window=blocking,
                        current_spend_usd=current,
                        ceiling_usd=ceiling_usd_v or 0.0,
                        projected_run_cost_usd=proj,
                        auth_reason=auth_reason,
                    ),
                )
                return

            # No bypass — hard block.
            if self._telemetry is not None:
                self._telemetry.emit(
                    CostCeilingBlocked(
                        window=blocking,
                        current_spend_usd=current,
                        ceiling_usd=ceiling_usd_v or 0.0,
                        projected_run_cost_usd=proj,
                        blocked_milestone=current_milestone,
                        override_used=False,
                        preflight_gate=gate,
                    )
                )
            self._audit.append(
                "CEILING_BLOCK",
                run_id=self.state.run_id,
                milestone=current_milestone,
                data={
                    "window": blocking,
                    "current_spend_usd": round(current, 4),
                    "ceiling_usd": round(ceiling_usd_v or 0.0, 4),
                    "projected_run_cost_usd": round(proj, 4),
                    "gate": gate,
                },
            )
            print(
                f"  FATAL: Cost ceiling blocked run "
                f"({blocking} window: ${current:.2f} + ${proj:.2f} projected "
                f"= ${current + proj:.2f} >= ${ceiling_usd_v or 0.0:.2f}). "
                f"Use --ignore-ceiling with SW_ALLOW_CEILING_BYPASS=1 to override.",
            )
            raise SystemExit(EXIT_CEILING_BLOCKED)

    def _call_pre_phase(self, phase: str, milestone: dict) -> None:
        for plugin in self._plugins:
            plugin.pre_phase(phase, milestone)

    def _call_post_phase(self, phase: str, milestone: dict, result: dict) -> None:
        for plugin in self._plugins:
            plugin.post_phase(phase, milestone, result)

    def _call_pre_commit(self, milestone: dict, files: list[str]) -> None:
        for plugin in self._plugins:
            plugin.pre_commit(milestone, files)

    def _call_post_milestone(self, milestone: dict, cost: float) -> None:
        for plugin in self._plugins:
            plugin.post_milestone(milestone, cost)

    def _generate_docs(self, ms: dict) -> None:
        docs_config = self.config.get("docs", {})
        generated: list[str] = []

        if docs_config.get("changelog", {}).get("enabled", False):
            try:
                changelog = generate_changelog(cwd=self.cwd)
                if changelog:
                    cl_path = Path(self.cwd) / "CHANGELOG.md"
                    cl_path.write_text(changelog)
                    generated.append("CHANGELOG.md")
            except Exception:
                pass

        if docs_config.get("diagrams", {}).get("enabled", False):
            try:
                src_dir = Path(self.cwd) / "src"
                if src_dir.exists():
                    mermaid = generate_mermaid(src_dir)
                    output = docs_config["diagrams"].get("output", "docs/architecture.mmd")
                    out_path = Path(self.cwd) / output
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(mermaid)
                    generated.append(output)
            except Exception:
                pass

        api_config = docs_config.get("api", {})
        if api_config.get("tool"):
            try:
                src_dir = Path(self.cwd) / "src"
                out_dir = Path(self.cwd) / api_config.get("output_dir", "docs/api")
                if src_dir.exists():
                    build_api_docs(src_dir, out_dir, tool=api_config["tool"], cwd=self.cwd)
                    generated.append(api_config.get("output_dir", "docs/api"))
            except Exception:
                pass

        readme_config = docs_config.get("readme", {})
        if readme_config.get("enabled", False):
            try:
                content = generate_readme(
                    Path(self.cwd),
                    model=self.config["model"],
                    effort=self.config.get("effort", {}).get("review", "high"),
                    budget=self.config.get("budgets", {}).get("push", 3),
                    template=readme_config.get("template"),
                    sections=readme_config.get("sections"),
                    cwd=self.cwd,
                )
                if content:
                    (Path(self.cwd) / "README.md").write_text(content)
                    generated.append("README.md")
            except Exception:
                pass

        if generated:
            self._commit_docs(generated)

    def _commit_docs(self, files: list[str]) -> None:
        try:
            subprocess.run(
                ["git", "add"] + files,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=30,
            )
            model = self.config.get("model", "opus")
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "docs: update generated documentation",
                    "--trailer",
                    f"Generated-By: {model}",
                ],
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=30,
            )
        except Exception:
            pass

    def _run_milestone(
        self,
        ms: dict,
        logger: WorkflowLogger,
        cwd_override: str | None = None,
        model_override: str | None = None,
        num_agents: int | None = None,
    ) -> float:
        """Thin driver — orchestrates 6 phase classes per v1.2.0-real refactor.

        Each phase (PhaseA/B/TbV/C/D/E) consumes a PhaseContext and produces
        a PhaseResult. The driver threads ctx between phases via:

            ctx = ctx.update(
                accumulated_cost=ctx.accumulated_cost + result.cost_usd,
                **result.extras,
            )

        Pure-local arithmetic — driver NEVER calls _accumulate_cost. State
        has advanced incrementally INSIDE each phase via
        self._accumulate_cost(...) after every internal claude call,
        preserving the v1.3.12 in-flight budget gate and v1.3.4 #15 retry
        safety. The driver pattern was validated by the Task 1.x golden
        trace fixtures: post-refactor traces must deep-equal pre-refactor
        baseline + fix-loop fixtures.
        """
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

        # Build the initial PhaseContext for the phase loop.
        ctx = PhaseContext(
            milestone_name=name,
            milestone_dict=ms,
            spec=spec,
            sections=sections,
            model=model,
            fallback_model=fallback,
            budgets=budgets,
            effort=effort,
            verify=verify,
            convergence=convergence,
            validation=self.config.get("validation", {}),
            context_summary=context,
            plan_commit_sha=self.state.plan_commit_sha,
            logger=logger,
        )

        # v1.3.17 / v1.1.9.1 — track current milestone for BudgetAlert
        # + RunCostProjection event payloads.
        self._current_milestone_name = name

        # v1.3.19 — clear drift dedup at milestone start so each
        # milestone gets a fresh budget of one-event-per-(metric,
        # bucket, severity, direction).
        with self._state_lock:
            self.state.drift_alerts_emitted_this_milestone = []

        # Phases A → B → TbV → C → D: extras (plan_commit_sha,
        # context_summary, compliance_report, verification_report) thread
        # into PhaseContext via ctx.update(**result.extras). The Finding 3
        # extras-drift guard fires if a phase emits an extras key that
        # PhaseContext doesn't recognise.
        phase_sequence = (PhaseA, PhaseB, PhaseTbV, PhaseC, PhaseD)
        for phase_cls in phase_sequence:
            self._current_phase_name = phase_cls.name
            result = phase_cls(self).run(ctx)
            ctx = ctx.update(
                accumulated_cost=ctx.accumulated_cost + result.cost_usd,
                **result.extras,
            )
            # v1.3.17 — emit RunCostProjection after each PhaseCompleted.
            # Best-effort; failures don't break the loop.
            self._emit_run_cost_projection(
                ctx,
                phase_just_completed=phase_cls.name,
                remaining_in_milestone=[
                    p.name
                    for p in phase_sequence
                    if phase_sequence.index(p) > phase_sequence.index(phase_cls)
                    and p.name != "trust_but_verify"
                ],
                completed_in_milestone=[
                    p.name
                    for p in phase_sequence
                    if phase_sequence.index(p) <= phase_sequence.index(phase_cls)
                    and p.name != "trust_but_verify"
                ],
            )

            # v1.3.19 — drift detection after each PhaseCompleted.
            # Best-effort; never raises.
            self._emit_drift_for_phase(
                phase=phase_cls.name,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                tokens=result.tokens,
            )

        # Phase E: extras (ci_success, ci_enabled) are control-flow
        # signals consumed by the driver, NOT structural data that
        # threads to a subsequent phase. PhaseE has no downstream phase,
        # so we accumulate cost but discard extras.
        self._current_phase_name = PhaseE.name
        result_e = PhaseE(self).run(ctx)
        cost = ctx.accumulated_cost + result_e.cost_usd

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

        self._call_post_milestone(ms, cost)
        self._generate_docs(ms)

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
            save_state(self._state_dir, self.state)
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

                ms_index = next((i for i, m in enumerate(milestones) if m["name"] == name), 0)
                if self._telemetry:
                    self._telemetry.emit(MilestoneStarted(milestone=name, index=ms_index))
                ms_start = time.monotonic()

                try:
                    # v1.3.8 Edit A: set per-worker cwd/claude_dir overrides
                    # so every subprocess in _run_milestone (and its helpers)
                    # resolves to the worktree path rather than self.cwd
                    # (parent repo). The context manager restores the
                    # previous values on exit so nested overrides compose.
                    with self._worker_context(run_cwd, Path(run_cwd) / ".claude"):
                        cost = self._run_milestone(ms, logger, model_override=ms_model)
                    if self._telemetry:
                        self._telemetry.emit(
                            MilestoneCompleted(
                                milestone=name,
                                cost_usd=round(cost, 2),
                                duration_seconds=round(time.monotonic() - ms_start, 1),
                            )
                        )
                    return ParallelResult(
                        milestone=name, success=True, cost_usd=cost, worktree=run_cwd
                    )
                except Exception as e:
                    if self._telemetry:
                        self._telemetry.emit(
                            MilestoneFailed(
                                milestone=name,
                                phase="parallel",
                                reason=str(e),
                                attempts=1,
                            )
                        )
                    return ParallelResult(
                        milestone=name, success=False, error=str(e), worktree=run_cwd
                    )

            # v1.3.5 #6 fix: switch from execute_wave (shared cwd → shared
            # .claude/.gap-report.json, .spec-compliance.json, etc. across
            # parallel branches → torn writes and cross-milestone report
            # contamination) to execute_wave_isolated (per-milestone
            # worktree → per-milestone .claude/ → no shared files).
            #
            # On success, each worktree is merged back to main; on failure,
            # the worktree is removed cleanly. Cost telemetry / state
            # mutations remain consolidated post-wave via _state_lock (#4).
            try:
                results = executor.execute_wave_isolated(wave, run_fn=run_fn)
            except Exception:
                wt_mgr.cleanup_all()
                raise

            # v1.3.5 #4: merge wave results under self._state_lock so the
            # final list append + save_state happens atomically. Workers
            # themselves can't append to self.state.completed concurrently
            # — they return a ParallelResult, and the orchestrator merges
            # post-wave. The lock guards against any other thread (e.g.,
            # the heartbeat daemon's lock-meta save, dashboard polling)
            # that may snapshot state during this critical section.
            with self._state_lock:
                self.state.current_step = "parallel_merge"
                save_state(self._state_dir, self.state)

                for result in results:
                    if result.success:
                        self.state.completed.append(result.milestone)
                        # v1.3.4 #15: cost was already charged incrementally
                        # inside _run_milestone via _accumulate_cost. Adding
                        # result.cost_usd here would double-count.
                    else:
                        self.state.failed.append(result.milestone)
                        failed_set.add(result.milestone)
                save_state(self._state_dir, self.state)

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
        results_cache: dict[str, dict] = {}
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
                passed = result.returncode == 0
                if not passed:
                    detail = (result.stdout or result.stderr)[:500]
                    failures.append(f"{gate_name}: {detail}")
                    logger.log("QUALITY_GATE_FAILED", gate=gate_name)
                else:
                    detail = ""
                    logger.log("QUALITY_GATE_PASSED", gate=gate_name)
                results_cache[gate_name] = {"passed": passed, "detail": detail}
                if self._telemetry:
                    self._telemetry.emit(
                        QualityGateResult(
                            milestone=milestone,
                            checkpoint=checkpoint,
                            gate=gate_name,
                            passed=passed,
                            detail=detail if not passed else "",
                        )
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                results_cache[gate_name] = {"passed": False, "detail": str(e)}
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

        results_path = self.claude_dir / ".quality-gate-results.json"
        try:
            tmp = results_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(results_cache, indent=2))
            os.replace(str(tmp), str(results_path))
        except OSError:
            pass

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
                r = self._run_claude(
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
            total = data.get("total_gaps_found", 0)
            # Zero gaps trivially means convergence — the model may report
            # converged=False just because it didn't think to set the flag.
            converged = data.get("converged", False) or total == 0
            self._telemetry.emit(
                GapReport(
                    milestone=milestone,
                    phase=phase,
                    critical_gaps=data.get("critical_gaps", 0),
                    architectural_gaps=data.get("architectural_gaps", 0),
                    important_gaps=data.get("important_gaps", 0),
                    minor_gaps=data.get("minor_gaps", 0),
                    deferred_gaps=data.get("deferred_gaps", 0),
                    total_gaps_found=total,
                    converged=converged,
                )
            )
        except (json.JSONDecodeError, OSError):
            pass

    def _emit_gap_validation(self, milestone: str) -> None:
        validation_path = self.claude_dir / ".gap-validation.json"
        if not validation_path.exists():
            return
        try:
            data = json.loads(validation_path.read_text())
            self._telemetry.emit(
                GapValidationEvent(
                    milestone=milestone,
                    total=data.get("total_gaps", 0),
                    valid=data.get("valid_gaps", 0),
                    invalid=data.get("invalid_gaps", 0),
                    unverifiable=data.get("unverifiable_gaps", 0),
                    duplicate=data.get("duplicate_gaps", 0),
                )
            )
        except (json.JSONDecodeError, OSError):
            pass

    def _run_spec_compliance(self, name: str, ms: dict) -> tuple[dict | None, float]:
        validation = self.config.get("validation", {})
        if not validation.get("spec_compliance", False):
            return None, 0.0

        self.state.current_step = "spec_compliance"
        save_state(self._state_dir, self.state)

        from superpower_workflow.validation.spec_compliance import run_spec_compliance

        spec_path = self.config["spec"]
        sections = ms.get("spec_sections", "")
        budget = validation.get("spec_compliance_budget", 3.0)

        module_dirs = []
        src_dir = Path(self.cwd) / "src"
        if src_dir.exists():
            module_dirs.append("src/")
        else:
            module_dirs.append(".")
        try:
            report = run_spec_compliance(
                spec_path=spec_path,
                spec_sections=sections or "all",
                module_dirs=module_dirs,
                run_claude_fn=self._run_claude,
                model=self.config["model"],
                budget=budget,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
                output_path=self.claude_dir / ".spec-compliance.json",
            )
        except Exception:
            return None, 0.0

        cost = report.get("cost_usd", 0.0)
        self._telemetry.emit(
            SpecComplianceCompleted(
                milestone=name,
                total_requirements=report.get("total_requirements", 0),
                implemented=report.get("implemented", 0),
                missing=report.get("missing", 0),
                cost_usd=cost,
            )
        )

        return report, cost

    def _run_feature_verification(self, name: str) -> tuple[dict | None, float]:
        validation = self.config.get("validation", {})
        if not validation.get("feature_verification", False):
            return None, 0.0

        self.state.current_step = "feature_verify"
        save_state(self._state_dir, self.state)

        from superpower_workflow.validation.feature_tester import run_feature_verification

        budget = validation.get("feature_verification_budget", 5.0)
        compliance_path = self.claude_dir / ".spec-compliance.json"

        try:
            report = run_feature_verification(
                compliance_path=compliance_path,
                run_claude_fn=self._run_claude,
                model=self.config["model"],
                budget=budget,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
                output_path=self.claude_dir / ".feature-verification.json",
            )
        except Exception:
            return None, 0.0

        cost = report.get("cost_usd", 0.0)
        self._telemetry.emit(
            FeatureVerificationCompleted(
                milestone=name,
                total_features=report.get("total_features", 0),
                verified=report.get("verified_working", 0),
                broken=report.get("broken", 0),
                manual_review=report.get("manual_review", 0),
                cost_usd=cost,
            )
        )

        return report, cost

    def _run_gap_curator(self, name: str, phase: str) -> float:
        """Post-process raw .gap-report.json into a curated, scoped report.

        Reads raw gap report + spec + focused diff + (review only) spec compliance.
        Writes curated gap report back to .gap-report.json (raw preserved at
        .gap-report.raw.json). Returns cost added, 0.0 when curator disabled/skipped.

        Failure modes (claude error, parse error, IO error) all fall back to raw —
        the orchestrator never fails over a curator failure.
        """
        validation = self.config.get("validation", {})
        if not validation.get("gap_curator", False):
            return 0.0

        gap_path = self.claude_dir / GAP_REPORT_FILE
        if not gap_path.exists():
            return 0.0

        try:
            raw_report = json.loads(gap_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0.0

        raw_total = raw_report.get("total_gaps_found", 0)
        min_gaps = int(validation.get("curator_min_gaps", 5))
        if raw_total < min_gaps:
            return 0.0

        from superpower_workflow.validation.gap_curator import run_gap_curator

        spec_rel = self.config.get("spec") or self.config.get("spec_path", "")
        spec_path = Path(self.cwd) / spec_rel if spec_rel else None
        compliance_path = self.claude_dir / ".spec-compliance.json"
        budget = float(validation.get("curator_budget", 1.0))

        try:
            curated = run_gap_curator(
                raw_gap_report=raw_report,
                phase=phase,
                project_root=Path(self.cwd),
                spec_path=spec_path,
                compliance_path=compliance_path if phase == "review" else None,
                plan_sha=self.state.plan_commit_sha or "",
                run_claude_fn=self._run_claude,
                model=self.config["model"],
                budget=budget,
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
            )
        except Exception:
            return 0.0

        if curated is None:
            # Fall back to raw — leave .gap-report.json untouched
            return 0.0

        # Preserve raw, replace .gap-report.json with curated
        try:
            (self.claude_dir / GAP_REPORT_RAW_FILE).write_text(
                json.dumps(raw_report, indent=2), encoding="utf-8"
            )
            gap_path.write_text(json.dumps(curated, indent=2), encoding="utf-8")
        except OSError:
            return 0.0

        cost = float(curated.get("cost_usd", 0.0))
        curated_total = curated.get("total_gaps_found", 0)
        dropped = curated.get("dropped_reasons", {}) or {}
        attrition = ((raw_total - curated_total) / raw_total * 100.0) if raw_total > 0 else 0.0

        self._telemetry.emit(
            GapCurationCompleted(
                milestone=name,
                phase=phase,
                raw_total=raw_total,
                curated_total=curated_total,
                dropped_unanchored=int(dropped.get("unanchored", 0)),
                dropped_spec_duplicate=int(dropped.get("spec_duplicate", 0)),
                dropped_trivial=int(dropped.get("trivial", 0)),
                dropped_speculative=int(dropped.get("speculative", 0)),
                attrition_pct=round(attrition, 1),
                cost_usd=cost,
            )
        )

        return cost

    def _run_strict_mode_loop(
        self,
        name: str,
        ms: dict,
        model: str,
        fallback: str | None,
        initial_compliance: dict | None,
        initial_verification: dict | None,
        logger,
    ) -> float:
        """When validation.strict_mode is on, re-check compliance + verification after
        Phase C and loop with explicit findings until missing+broken == 0 or cap hit.

        Returns total cost added by strict iterations (0.0 when strict mode is off).
        """
        validation = self.config.get("validation", {})
        if not validation.get("strict_mode", False):
            return 0.0

        max_iterations = int(validation.get("max_strict_iterations", 2))
        if max_iterations <= 0:
            return 0.0

        compliance = initial_compliance or {}
        verification = initial_verification or {}
        total_cost = 0.0

        for iteration in range(1, max_iterations + 1):
            missing_items = [
                d for d in (compliance.get("details") or []) if d.get("status") == "missing"
            ]
            broken_items = [
                d
                for d in (verification.get("details") or [])
                if d.get("status") in ("fail", "broken")
            ]

            if not missing_items and not broken_items:
                if iteration > 1:
                    self._telemetry.emit(
                        StrictModeIteration(
                            milestone=name,
                            iteration=iteration - 1,
                            missing_requirements=0,
                            broken_features=0,
                            converged=True,
                            cost_usd=0.0,
                        )
                    )
                return total_cost

            fix_prompt_parts = [
                f"Trust-but-verify (strict mode, iteration {iteration}/{max_iterations}) "
                f"found unresolved issues in milestone {name}.",
                "",
            ]
            if missing_items:
                fix_prompt_parts.append("MISSING REQUIREMENTS (must implement):")
                for d in missing_items:
                    fix_prompt_parts.append(
                        f"  - {d.get('requirement', '?')}  (evidence: {d.get('evidence', '-')})"
                    )
                fix_prompt_parts.append("")
            if broken_items:
                fix_prompt_parts.append("BROKEN FEATURES (must fix):")
                for d in broken_items:
                    fix_prompt_parts.append(
                        f"  - {d.get('feature', '?')}  "
                        f"reason: {d.get('reason', '-')}  "
                        f"test: {d.get('test', '-')}"
                    )
                fix_prompt_parts.append("")
            fix_prompt_parts.append(
                "Implement and/or fix each item above with TDD (red then green). "
                "Commit each fix as a separate conventional-commits change. "
                "Do not refactor unrelated code."
            )
            fix_prompt = "\n".join(fix_prompt_parts)

            r = self._run_claude(
                fix_prompt,
                model=model,
                effort="high",
                budget=float(validation.get("strict_iteration_budget", 8.0)),
                cwd=self.cwd,
                system_prompt=self.sys_prompt,
                fallback_model=fallback,
            )
            total_cost += r.cost_usd
            logger.log(
                "STRICT_ITERATION",
                iteration=iteration,
                missing=len(missing_items),
                broken=len(broken_items),
                cost=round(r.cost_usd, 2),
            )

            new_compliance, c_cost = self._run_spec_compliance(name, ms)
            total_cost += c_cost
            new_verification, v_cost = self._run_feature_verification(name)
            total_cost += v_cost

            compliance = new_compliance or {}
            verification = new_verification or {}

            still_missing = compliance.get("missing", 0)
            still_broken = verification.get("broken", 0)
            converged = still_missing == 0 and still_broken == 0

            self._telemetry.emit(
                StrictModeIteration(
                    milestone=name,
                    iteration=iteration,
                    missing_requirements=still_missing,
                    broken_features=still_broken,
                    converged=converged,
                    cost_usd=r.cost_usd + c_cost + v_cost,
                )
            )

            if converged:
                return total_cost

        return total_cost

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
