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

    # v1.3.17 / v1.1.9.1 — observability event surface.
    # Latest RunCostProjection event field values (defaults = no data).
    projected_total_usd: float = 0.0
    projection_low_p10_usd: float = 0.0
    projection_high_p90_usd: float = 0.0
    projection_confidence: float = 0.0
    projection_source: str = ""  # cold_start | partial_history | full_history
    # Latest BudgetAlert threshold crossed (0 if none).
    last_budget_alert_threshold: int = 0
    max_budget_usd: float = 0.0  # 0.0 if no cap configured

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
        # v1.3.2 #3: route through shared resolver. Falls back to the safe
        # default path when the configured value escapes project root.
        from superpower_workflow.paths import (
            DEFAULT_TELEMETRY_REL,
            resolve_telemetry_path,
        )

        resolved = resolve_telemetry_path(self._root, config, quiet=True)
        if resolved is None:
            return (self._root / DEFAULT_TELEMETRY_REL).resolve()
        return resolved

    def _get_watched_paths(self, config: dict | None = None) -> list[Path]:
        if config is None:
            config = self._load_config()
        return [
            self._claude_dir / "workflow-state.json",
            self._telemetry_path(config),
        ]

    def _snapshot_mtimes(self) -> dict[str, tuple[float, int]]:
        """Snapshot (mtime, size) per watched path.

        Size is included because Windows NTFS mtime has 100ns granularity and
        Python 3.12+ has been observed to write fast enough that two distinct
        writes share an mtime tick. Comparing size catches those cases.
        """
        mtimes: dict[str, tuple[float, int]] = {}
        for p in self._get_watched_paths():
            try:
                st = p.stat()
                mtimes[str(p)] = (st.st_mtime, st.st_size)
            except OSError:
                mtimes[str(p)] = (0.0, 0)
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

        # v1.3.17 / v1.1.9.1 — extract latest RunCostProjection +
        # BudgetAlert from the telemetry log. Best-effort: missing or
        # unreadable telemetry leaves these at defaults.
        proj_total = proj_low = proj_high = proj_conf = 0.0
        proj_source = ""
        last_alert_threshold = state.last_budget_alert_pct
        max_budget_usd = float(config.get("max_total_budget_usd", 0.0) or 0.0)
        try:
            tel_path = self._telemetry_path(config)
            if tel_path.exists():
                for line in tel_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = ev.get("type")
                    if t == "run_cost_projection":
                        proj_total = ev.get("projected_total_usd", 0.0)
                        proj_low = ev.get("low_p10_usd", 0.0)
                        proj_high = ev.get("high_p90_usd", 0.0)
                        proj_conf = ev.get("confidence", 0.0)
                        proj_source = ev.get("source", "")
        except OSError:
            pass

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
            projected_total_usd=proj_total,
            projection_low_p10_usd=proj_low,
            projection_high_p90_usd=proj_high,
            projection_confidence=proj_conf,
            projection_source=proj_source,
            last_budget_alert_threshold=last_alert_threshold,
            max_budget_usd=max_budget_usd,
        )
