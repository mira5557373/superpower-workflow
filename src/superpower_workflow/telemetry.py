from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import ClassVar


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
