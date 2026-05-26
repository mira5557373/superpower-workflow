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


class TelemetryEmitter:
    def __init__(self, path: Path | None, run_id: str) -> None:
        self._path = path
        self._run_id = run_id
        self._file: IO[str] | None = None
        self._enabled = path is not None

    def emit(self, event: TelemetryEvent) -> None:
        if not self._enabled:
            return
        event.run_id = self._run_id
        try:
            if self._file is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
            self._file.write(event.to_json_line() + "\n")
            self._file.flush()
        except OSError:
            pass

    def close(self) -> None:
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
