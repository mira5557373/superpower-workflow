from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


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
