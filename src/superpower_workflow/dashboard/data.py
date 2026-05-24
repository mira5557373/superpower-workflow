from __future__ import annotations

import calendar
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from superpower_workflow.state import load_state
from superpower_workflow.telemetry import TelemetryReader


@dataclass
class DashboardSnapshot:
    timestamp: str = ""
    run_id: str = ""
    status: str = "idle"
    model: str = ""

    milestones_total: int = 0
    milestones_completed: int = 0
    milestones_failed: int = 0
    milestones_skipped: int = 0
    current_milestone: str = ""
    current_phase: str = ""
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    total_cost_usd: float = 0.0
    cost_by_milestone: dict[str, float] = field(default_factory=dict)
    cost_by_phase: dict[str, float] = field(default_factory=dict)
    cost_per_task: float = 0.0

    elapsed_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    duration_by_milestone: dict[str, float] = field(default_factory=dict)
    duration_by_phase: dict[str, int] = field(default_factory=dict)

    rework_rate: float = 0.0
    defect_density: float = 0.0
    quality_trend: list[dict] = field(default_factory=list)

    milestone_names: list[str] = field(default_factory=list)
    started_at: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_utc_timestamp(ts: str) -> float:
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return 0.0


class DashboardData:
    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._claude_dir = project_root / ".claude"
        self._last_mtimes: dict[str, float] = {}

    def _load_config(self) -> dict:
        path = self._claude_dir / "workflow.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _telemetry_path(self, config: dict) -> Path:
        rel = config.get("telemetry", {}).get("path", ".claude/telemetry.jsonl")
        return self._root / rel

    def _get_watched_paths(self, config: dict | None = None) -> list[Path]:
        if config is None:
            config = self._load_config()
        return [
            self._claude_dir / "workflow-state.json",
            self._telemetry_path(config),
        ]

    def _snapshot_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for p in self._get_watched_paths():
            try:
                mtimes[str(p)] = p.stat().st_mtime
            except OSError:
                mtimes[str(p)] = 0.0
        return mtimes

    def has_changed(self) -> bool:
        current = self._snapshot_mtimes()
        return current != self._last_mtimes

    def load_snapshot(self) -> DashboardSnapshot:
        config = self._load_config()
        milestones = config.get("milestones", [])
        model = config.get("model", "")

        state = load_state(self._claude_dir)
        reader = TelemetryReader(self._telemetry_path(config))
        run_id = state.run_id or reader.latest_run_id() or ""

        completed = list(state.completed)
        failed = list(state.failed)
        skipped = list(state.skipped)

        if not state.started_at and not completed and not failed:
            status = "idle"
        elif state.current_step:
            status = "running"
        elif failed:
            status = "failed"
        else:
            status = "completed"

        current_milestone = ""
        current_phase = state.current_step or ""
        idx = state.current_milestone_index
        if status == "running" and idx < len(milestones):
            current_milestone = milestones[idx].get("name", "")

        elapsed = 0.0
        if state.started_at:
            start_epoch = _parse_utc_timestamp(state.started_at)
            if start_epoch > 0:
                elapsed = time.time() - start_epoch

        milestone_names = [m.get("name", "") for m in milestones]

        self._last_mtimes = self._snapshot_mtimes()
        return DashboardSnapshot(
            run_id=run_id,
            status=status,
            model=model,
            milestones_total=len(milestones),
            milestones_completed=len(completed),
            milestones_failed=len(failed),
            milestones_skipped=len(skipped),
            current_milestone=current_milestone,
            current_phase=current_phase,
            completed=completed,
            failed=failed,
            skipped=skipped,
            total_cost_usd=state.total_cost_usd,
            cost_by_milestone=reader.cost_by_milestone(run_id=run_id) if run_id else {},
            cost_by_phase=reader.cost_by_phase(run_id=run_id) if run_id else {},
            cost_per_task=reader.cost_per_successful_task(run_id=run_id) if run_id else 0.0,
            elapsed_seconds=elapsed,
            total_duration_seconds=reader.total_duration(run_id=run_id) if run_id else 0.0,
            duration_by_milestone=reader.duration_by_milestone(run_id=run_id) if run_id else {},
            duration_by_phase=reader.duration_by_phase(run_id=run_id) if run_id else {},
            rework_rate=reader.rework_rate(run_id=run_id) if run_id else 0.0,
            defect_density=reader.defect_density(run_id=run_id) if run_id else 0.0,
            quality_trend=reader.quality_trend(run_id=run_id) if run_id else [],
            milestone_names=milestone_names,
            started_at=state.started_at,
        )
