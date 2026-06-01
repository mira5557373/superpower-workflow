from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, ClassVar


@dataclass
class TelemetryEvent:
    EVENT_TYPE: ClassVar[str] = "base"
    timestamp: str = ""
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict:
        d = {"type": self.EVENT_TYPE}
        d.update(asdict(self))
        return d

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class RunStarted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "run_started"
    spec_sha: str = ""
    model: str = ""
    milestone_count: int = 0
    max_budget_usd: float = 0.0


@dataclass
class RunCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "run_completed"
    status: str = ""
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    test_file_count: int = 0


@dataclass
class MilestoneStarted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "milestone_started"
    milestone: str = ""
    index: int = 0


@dataclass
class MilestoneCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "milestone_completed"
    milestone: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class MilestoneFailed(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "milestone_failed"
    milestone: str = ""
    phase: str = ""
    reason: str = ""
    attempts: int = 0


@dataclass
class MilestoneSkipped(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "milestone_skipped"
    milestone: str = ""
    reason: str = ""


@dataclass
class PhaseStarted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "phase_started"
    milestone: str = ""
    phase: str = ""


@dataclass
class PhaseCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "phase_completed"
    milestone: str = ""
    phase: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_hit_rate: float = 0.0


@dataclass
class QualityGateResult(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "quality_gate_result"
    milestone: str = ""
    checkpoint: str = ""
    gate: str = ""
    passed: bool = True
    detail: str = ""


@dataclass
class CoverageResult(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "coverage_result"
    milestone: str = ""
    coverage_pct: float = 0.0
    threshold: float = 0.0
    passed: bool = True


@dataclass
class RetryAttempt(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "retry_attempt"
    milestone: str = ""
    phase: str = ""
    attempt: int = 0
    reason: str = ""
    delay_seconds: int = 0


@dataclass
class GapReport(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "gap_report"
    milestone: str = ""
    phase: str = ""
    critical_gaps: int = 0
    architectural_gaps: int = 0
    important_gaps: int = 0
    minor_gaps: int = 0
    deferred_gaps: int = 0
    total_gaps_found: int = 0
    converged: bool = False


@dataclass
class ModelRouted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "model_routed"
    milestone: str = ""
    model: str = ""
    complexity_score: float = 0.0
    reason: str = ""


@dataclass
class ParallelWaveStarted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "parallel_wave_started"
    wave_index: int = 0
    milestones: list[str] = field(default_factory=list)
    worker_count: int = 0


@dataclass
class ParallelWaveCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "parallel_wave_completed"
    wave_index: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class WorktreeCreated(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "worktree_created"
    milestone: str = ""
    branch: str = ""
    worktree_path: str = ""


@dataclass
class WorktreeMerged(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "worktree_merged"
    milestone: str = ""
    branch: str = ""
    success: bool = True
    conflicts: int = 0


@dataclass
class BestOfNCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "best_of_n_completed"
    milestone: str = ""
    n: int = 0
    winner_index: int = 0
    winner_model: str = ""
    winner_score: float = 0.0
    total_cost_usd: float = 0.0


@dataclass
class RemoteExecution(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "remote_execution"
    milestone: str = ""
    host: str = ""
    success: bool = True
    cost_usd: float = 0.0


@dataclass
class DocsGenerated(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "docs_generated"
    doc_type: str = ""
    output_path: str = ""


@dataclass
class BootstrapCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "bootstrap_completed"
    project_type: str = ""
    files_created: int = 0


@dataclass
class PluginLoaded(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "plugin_loaded"
    plugin_name: str = ""
    plugin_version: str = ""


@dataclass
class PluginVetoed(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "plugin_vetoed"
    plugin_name: str = ""
    phase: str = ""
    reason: str = ""


@dataclass
class UpgradeChecked(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "upgrade_checked"
    outdated_count: int = 0
    breaking_count: int = 0


@dataclass
class GapValidationEvent(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "gap_validation"
    milestone: str = ""
    total: int = 0
    valid: int = 0
    invalid: int = 0
    unverifiable: int = 0
    duplicate: int = 0


@dataclass
class SpecComplianceCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "spec_compliance_completed"
    milestone: str = ""
    total_requirements: int = 0
    implemented: int = 0
    missing: int = 0
    cost_usd: float = 0.0


@dataclass
class FeatureVerificationCompleted(TelemetryEvent):
    EVENT_TYPE: ClassVar[str] = "feature_verification_completed"
    milestone: str = ""
    total_features: int = 0
    verified: int = 0
    broken: int = 0
    manual_review: int = 0
    cost_usd: float = 0.0


@dataclass
class SpecLintCompleted(TelemetryEvent):
    """Emitted when `sw lint-spec` or `sw decompose` runs the spec linter."""

    EVENT_TYPE: ClassVar[str] = "spec_lint_completed"
    spec_path: str = ""
    score: int = 0
    checks_passed: int = 0
    checks_warned: int = 0
    checks_failed: int = 0
    blocker_count: int = 0


@dataclass
class GapCurationCompleted(TelemetryEvent):
    """Emitted when the gap curator filters a raw gap report into curated, scoped gaps."""

    EVENT_TYPE: ClassVar[str] = "gap_curation_completed"
    milestone: str = ""
    phase: str = ""
    raw_total: int = 0
    curated_total: int = 0
    dropped_unanchored: int = 0
    dropped_spec_duplicate: int = 0
    dropped_trivial: int = 0
    dropped_speculative: int = 0
    attrition_pct: float = 0.0
    cost_usd: float = 0.0


@dataclass
class StrictModeIteration(TelemetryEvent):
    """Emitted when strict-mode loops Phase C on residual compliance/verification findings."""

    EVENT_TYPE: ClassVar[str] = "strict_mode_iteration"
    milestone: str = ""
    iteration: int = 0
    missing_requirements: int = 0
    broken_features: int = 0
    converged: bool = False
    cost_usd: float = 0.0


@dataclass
class RunCostProjection(TelemetryEvent):
    """v1.1.9.1 / v1.3.17 — mid-run cost projection.

    Emitted after each PhaseCompleted. Combines actual phase costs with
    historical per-phase ratios (or cold-start defaults) to project the
    run's total. `source` indicates the data quality: cold_start (no
    history), partial_history (3-9 historical samples), full_history
    (>=10 samples). Confidence is in [0,1] proportional to sample
    saturation.
    """

    EVENT_TYPE: ClassVar[str] = "run_cost_projection"
    milestone: str = ""
    milestones_completed: int = 0
    milestones_total: int = 0
    current_spent_usd: float = 0.0
    projected_total_usd: float = 0.0
    low_p10_usd: float = 0.0
    high_p90_usd: float = 0.0
    confidence: float = 0.0
    source: str = "cold_start"  # cold_start | partial_history | full_history
    max_budget_usd: float = 0.0  # 0.0 == no cap configured
    pct_of_cap: float = 0.0  # 0.0 when max_budget_usd <= 0


@dataclass
class DriftDetected(TelemetryEvent):
    """v1.3.19 — drift detector found a per-metric deviation.

    Fires from the orchestrator's post-phase / post-milestone hook
    when a sigma-band threshold is crossed. Subject to the safety
    gates in `drift.py`: baseline_floor (default 15 samples),
    observation_only mode (INFO suppressed by default), parallel-
    mode skip, and per-(metric,bucket,severity) rate-limit per
    milestone.

    `bucket` carries the partitioning key — `"<phase>|<model_id>"`
    for per-phase metrics, `"__global__|<model_id>"` for per-milestone.
    Operators can use this to filter alerts to the current model.
    """

    EVENT_TYPE: ClassVar[str] = "drift_detected"
    milestone: str = ""
    metric: str = (
        ""  # cost_usd / duration_ms / cache_hit_rate / gap_attrition_pct / strict_iterations
    )
    aggregation: str = ""  # per_phase | per_milestone
    bucket: str = ""  # phase|model_id  or  __global__|model_id
    value: float = 0.0  # observed value
    baseline_n: int = 0  # sample count backing the baseline
    baseline_mean: float = 0.0  # mean in original units (de-logged for cost/duration)
    baseline_sigma: float = 0.0
    z_score: float = 0.0  # signed (positive = higher than baseline)
    severity: str = "ok"  # info | warn | critical
    direction: str = "neutral"  # high | low | neutral
    recommendation: str = ""


@dataclass
class BudgetAlert(TelemetryEvent):
    """v1.1.9.1 / v1.3.17 — budget threshold crossing.

    Fires inside Orchestrator._accumulate_cost when state.total_cost_usd
    crosses UP to a new threshold (50/75/90/100). Monotonic — once a
    threshold has fired, cost oscillating around it (refunds, parallel
    rebalance) does NOT re-fire. Leap-skip: cost jumping 40% → 80% emits
    exactly ONE BudgetAlert(threshold=75), not separate 50+75 events;
    the raw percent_of_cap field carries the actual crossing value.
    """

    EVENT_TYPE: ClassVar[str] = "budget_alert"
    milestone: str = ""
    phase: str = ""
    current_spent_usd: float = 0.0
    max_budget_usd: float = 0.0
    percent_of_cap: float = 0.0  # actual computed pct at crossing time
    threshold: int = 0  # 50 | 75 | 90 | 100


@dataclass
class CostCeilingEvaluated(TelemetryEvent):
    """v1.3.20 — emitted once per (configured ceiling, preflight gate).

    Distinct from BudgetAlert (v1.3.17), which is WITHIN-run percent-of-cap
    crossings. This is ACROSS-run absolute spend over a rolling window:
    rolling 24h (day), 7d (week), 30d (month). Both can fire independently
    in a single run that crosses both thresholds.

    `decision`:
    - `allow` — under ceiling
    - `warn` — over ceiling but mode=warn (advisory only)
    - `block` — over ceiling and mode=block (run aborted, exit 7)
    - `no_history` — telemetry missing/empty; defaults to allow
    - `bypass` — over+block but user passed `--ignore-ceiling` (with env auth)
    """

    EVENT_TYPE: ClassVar[str] = "cost_ceiling_evaluated"
    window: str = ""  # day | week | month
    window_start_utc: str = ""
    window_end_utc: str = ""
    current_spend_usd: float = 0.0
    projected_run_cost_usd: float = 0.0
    ceiling_usd: float = 0.0  # 0.0 if window not configured
    headroom_usd: float = 0.0
    contributing_runs: int = 0
    mode: str = "block"  # warn | block
    decision: str = "allow"  # allow | warn | block | no_history | bypass
    source: str = "telemetry"  # telemetry | no_history | partial_history
    preflight_gate: str = "run_start"  # run_start | milestone_start | phase_e_retry


@dataclass
class CostCeilingBlocked(TelemetryEvent):
    """v1.3.20 — fires only when a `block`-mode ceiling halts a run start
    (or would have, before override). Precedes process exit 7."""

    EVENT_TYPE: ClassVar[str] = "cost_ceiling_blocked"
    window: str = ""
    current_spend_usd: float = 0.0
    ceiling_usd: float = 0.0
    projected_run_cost_usd: float = 0.0
    blocked_milestone: str = ""
    override_used: bool = False
    preflight_gate: str = "run_start"


@dataclass
class ClaudeInvocationFailed(TelemetryEvent):
    """v1.3.21 — typed subprocess-error event from runner.

    Addresses verdict revision #5 from the v1.3.21 design bake-off:
    the rule-only classifier should NOT regex-parse free-text MilestoneFailed
    reason strings. Instead, the runner emits this typed event whenever a
    `claude -p` invocation fails terminally (after retries exhausted), so
    rules 08/09 can read a stable `error_kind` field instead of brittle
    string patterns that rot on every SDK upgrade.

    error_kind ∈ {"timeout", "is_error", "nonzero_exit", "mcp_crash",
                  "auth", "unknown"}.
    """

    EVENT_TYPE: ClassVar[str] = "claude_invocation_failed"
    milestone: str = ""
    phase: str = ""
    error_kind: str = "unknown"
    timed_out: bool = False
    returncode: int = 0
    message: str = ""  # truncated to 300 chars
    attempt: int = 0
    max_attempts: int = 0


@dataclass
class FailureTriaged(TelemetryEvent):
    """v1.3.21 — classifier output: one per terminal failure anchor.

    Emitted online by the orchestrator hook immediately after a
    MilestoneFailed (or CostCeilingBlocked / WorktreeMerged{success=false}
    / each entry in ParallelWaveCompleted.failed[]). Also produced offline
    by `sw triage` CLI replay over .claude/sw-telemetry.jsonl.

    `confidence` ∈ {1.0 hard-signal, 0.7 corroborated, 0.4 fallback}.
    `secondary_classes` is a list of (FailureClass | SecondaryTag) values
    that co-occurred independently. DRIFT_CORRELATED is the canonical
    secondary tag that NEVER appears as primary.

    `triage_version` lets future rule-set changes be detected on replay.
    """

    EVENT_TYPE: ClassVar[str] = "failure_triaged"
    milestone: str = ""
    phase: str = ""
    primary_class: str = "unknown"
    secondary_classes: list[str] = field(default_factory=list)
    confidence: float = 0.4
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    anchor_seq: int = 0
    anchor_type: str = ""
    triage_version: int = 1
    raw_reason: str = ""  # truncated 300 chars, only populated for UNKNOWN


class TelemetryEmitter:
    """v1.3.5 #3 fix: thread-safe writes for parallel orchestrator branches.

    Pre-fix: `emit` opened the file lazily and called `self._file.write` +
    `.flush` without any lock. When `parallel.enabled=true`, all worker
    threads shared `self._telemetry` and concurrent emit() calls could
    interleave bytes mid-line, producing un-parseable JSONL.

    Now: a `threading.Lock` serializes the entire emit() body — lazy file
    open + write + flush — so a single event always lands atomically.
    """

    def __init__(self, path: Path | None, run_id: str) -> None:
        import threading

        self._path = path
        self._run_id = run_id
        self._file: IO[str] | None = None
        self._enabled = path is not None
        self._lock = threading.Lock()

    def emit(self, event: TelemetryEvent) -> None:
        if not self._enabled:
            return
        event.run_id = self._run_id
        with self._lock:
            try:
                if self._file is None:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
                self._file.write(event.to_json_line() + "\n")
                self._file.flush()
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    @classmethod
    def disabled(cls) -> TelemetryEmitter:
        return cls(path=None, run_id="")


class TelemetryReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def events(self) -> list[dict]:
        if not self._path.exists():
            return []
        result = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    def events_by_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events() if e.get("type") == event_type]

    def events_for_run(self, run_id: str) -> list[dict]:
        return [e for e in self.events() if e.get("run_id") == run_id]

    def latest_run_id(self) -> str | None:
        started = self.events_by_type("run_started")
        if not started:
            return None
        return started[-1].get("run_id")

    def cost_by_milestone(self, run_id: str | None = None) -> dict[str, float]:
        source = self.events_for_run(run_id) if run_id else self.events()
        costs: dict[str, float] = {}
        for e in source:
            if e.get("type") == "milestone_completed":
                costs[e["milestone"]] = e.get("cost_usd", 0.0)
        return costs

    def cost_by_phase(self, run_id: str | None = None) -> dict[str, float]:
        source = self.events_for_run(run_id) if run_id else self.events()
        costs: dict[str, float] = {}
        for e in source:
            if e.get("type") == "phase_completed":
                phase = e.get("phase", "unknown")
                costs[phase] = costs.get(phase, 0.0) + e.get("cost_usd", 0.0)
        return costs

    def cost_per_successful_task(self, run_id: str | None = None) -> float:
        source = self.events_for_run(run_id) if run_id else self.events()
        total_cost = 0.0
        total_completed = 0
        for e in source:
            if e.get("type") == "run_completed":
                total_cost += e.get("total_cost_usd", 0.0)
                total_completed += e.get("completed_count", 0)
        return total_cost / total_completed if total_completed > 0 else 0.0

    def total_cost(self, run_id: str | None = None) -> float:
        source = self.events_for_run(run_id) if run_id else self.events()
        return sum(e.get("total_cost_usd", 0.0) for e in source if e.get("type") == "run_completed")

    def rework_rate(self, run_id: str | None = None) -> float:
        source = self.events_for_run(run_id) if run_id else self.events()
        milestones = [e for e in source if e.get("type") == "milestone_started"]
        retries = [e for e in source if e.get("type") == "retry_attempt"]
        if not milestones:
            return 0.0
        return len(retries) / len(milestones)

    def defect_density(self, run_id: str | None = None) -> float:
        source = self.events_for_run(run_id) if run_id else self.events()
        gate_results = [e for e in source if e.get("type") == "quality_gate_result"]
        if not gate_results:
            return 0.0
        failures = sum(1 for e in gate_results if not e.get("passed", True))
        return failures / len(gate_results)

    def quality_trend(self, run_id: str | None = None) -> list[dict]:
        source = self.events_for_run(run_id) if run_id else self.events()
        return [
            {
                "milestone": e.get("milestone", ""),
                "phase": e.get("phase", ""),
                "total_gaps_found": e.get("total_gaps_found", 0),
                "critical_gaps": e.get("critical_gaps", 0),
                "converged": e.get("converged", False),
            }
            for e in source
            if e.get("type") == "gap_report"
        ]

    def duration_by_milestone(self, run_id: str | None = None) -> dict[str, float]:
        source = self.events_for_run(run_id) if run_id else self.events()
        durations: dict[str, float] = {}
        for e in source:
            if e.get("type") == "milestone_completed":
                durations[e["milestone"]] = e.get("duration_seconds", 0.0)
        return durations

    def duration_by_phase(self, run_id: str | None = None) -> dict[str, int]:
        source = self.events_for_run(run_id) if run_id else self.events()
        durations: dict[str, int] = {}
        for e in source:
            if e.get("type") == "phase_completed":
                phase = e.get("phase", "unknown")
                durations[phase] = durations.get(phase, 0) + e.get("duration_ms", 0)
        return durations

    def total_duration(self, run_id: str | None = None) -> float:
        source = self.events_for_run(run_id) if run_id else self.events()
        return sum(
            e.get("duration_seconds", 0.0) for e in source if e.get("type") == "run_completed"
        )
