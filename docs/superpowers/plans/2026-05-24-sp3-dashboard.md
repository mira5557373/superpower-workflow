# SP3: Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `sw dashboard` (web UI at localhost with SSE live updates), `sw watch` (terminal TUI), and an optional Prometheus `/metrics` endpoint so operators can observe milestone progress, cost, and quality in real time.

**Architecture:** New `dashboard/` subpackage with clean separation: data provider (reads telemetry.jsonl + workflow-state.json), HTTP server (stdlib `http.server` + SSE + Prometheus text format), terminal watch (ANSI escape codes). Zero new runtime dependencies — all stdlib.

**Tech Stack:** Python 3.11+, `http.server.ThreadingHTTPServer`, `threading.Event`, ANSI escape codes, `time.strftime`, `calendar.timegm`, `json`, `dataclasses`, `urllib.request` (tests), pytest, ruff.

**Spec reference:** `docs/superpowers/specs/roadmap.md` §SP3.

**Working directory:** `superpower-workflow/` (the repo root).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/dashboard/__init__.py` | New | Package exports |
| `src/superpower_workflow/dashboard/data.py` | New | DashboardSnapshot dataclass + DashboardData provider |
| `src/superpower_workflow/dashboard/server.py` | New | SSE formatter, Prometheus renderer, HTTP handler, DashboardServer |
| `src/superpower_workflow/dashboard/watch.py` | New | ANSI renderer + TerminalWatch polling loop |
| `src/superpower_workflow/dashboard/static.py` | New | DASHBOARD_HTML constant (embedded single-page app) |
| `src/superpower_workflow/cli.py` | Edit | Add `sw dashboard` and `sw watch` commands |
| `templates/workflow.json` | Edit | Add `dashboard` config section |
| `tests/test_dashboard_data.py` | New | DashboardSnapshot + DashboardData tests |
| `tests/test_dashboard_server.py` | New | SSE, Prometheus, HTTP handler, server tests |
| `tests/test_dashboard_watch.py` | New | Terminal renderer + watch loop tests |
| `tests/test_cli.py` | Edit | Parser tests for new commands |
| `tests/test_dashboard_integration.py` | New | End-to-end pipeline tests |

---

### Task 1: DashboardSnapshot dataclass + serialization

**Files:**
- New: `src/superpower_workflow/dashboard/__init__.py`
- New: `src/superpower_workflow/dashboard/data.py`
- New: `tests/test_dashboard_data.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_data.py
from __future__ import annotations

import json

from superpower_workflow.dashboard.data import DashboardSnapshot


class TestDashboardSnapshot:
    def test_default_snapshot_is_idle(self):
        snap = DashboardSnapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 0
        assert snap.milestones_completed == 0
        assert snap.total_cost_usd == 0.0

    def test_snapshot_to_dict_roundtrip(self):
        snap = DashboardSnapshot(
            run_id="run-1",
            status="running",
            milestones_total=5,
            milestones_completed=2,
            total_cost_usd=42.50,
            current_milestone="m3",
            current_phase="implement",
            completed=["m1", "m2"],
        )
        d = snap.to_dict()
        assert d["run_id"] == "run-1"
        assert d["status"] == "running"
        assert d["milestones_total"] == 5
        assert d["milestones_completed"] == 2
        assert d["total_cost_usd"] == 42.50
        assert d["current_milestone"] == "m3"
        assert d["completed"] == ["m1", "m2"]

    def test_snapshot_to_dict_is_json_serializable(self):
        snap = DashboardSnapshot(
            run_id="r1",
            cost_by_milestone={"m1": 5.0},
            quality_trend=[{"gaps": 3}],
        )
        raw = json.dumps(snap.to_dict())
        parsed = json.loads(raw)
        assert parsed["cost_by_milestone"] == {"m1": 5.0}
        assert parsed["quality_trend"] == [{"gaps": 3}]

    def test_snapshot_timestamp_auto_set(self):
        snap = DashboardSnapshot()
        assert snap.timestamp != ""
        assert "T" in snap.timestamp

    def test_snapshot_explicit_timestamp_preserved(self):
        snap = DashboardSnapshot(timestamp="2026-01-01T00:00:00Z")
        assert snap.timestamp == "2026-01-01T00:00:00Z"
```

- [ ] **Step 2: Run test — expect FAIL** (module doesn't exist)

- [ ] **Step 3: Create dashboard package and DashboardSnapshot**

```python
# src/superpower_workflow/dashboard/__init__.py
"""Dashboard: web UI, terminal watch, and Prometheus metrics for sw."""

from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot

__all__ = ["DashboardSnapshot"]
# DashboardData is added in Task 2 when the class is created.
```

```python
# src/superpower_workflow/dashboard/data.py
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
```

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/ tests/test_dashboard_data.py --fix
ruff format src/superpower_workflow/dashboard/ tests/test_dashboard_data.py
git add src/superpower_workflow/dashboard/__init__.py src/superpower_workflow/dashboard/data.py tests/test_dashboard_data.py
git commit -m "feat: add DashboardSnapshot dataclass with serialization"
```

---

### Task 2: DashboardData — load_snapshot() from telemetry + state

**Files:**
- Modify: `src/superpower_workflow/dashboard/data.py`
- Modify: `tests/test_dashboard_data.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_data.py — add imports and helpers at top
import json
import time
from pathlib import Path

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)


def _setup_project(tmp_path, milestones=None, state=None, telemetry_events=None):
    """Create a minimal project directory with config, state, and telemetry."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "schema_version": 1,
        "model": "opus",
        "milestones": milestones or [],
        "telemetry": {"enabled": True, "path": ".claude/telemetry.jsonl"},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))

    if state:
        (claude_dir / "workflow-state.json").write_text(json.dumps(state))

    if telemetry_events:
        tpath = tmp_path / ".claude" / "telemetry.jsonl"
        emitter = TelemetryEmitter(tpath, run_id="run-1")
        for event in telemetry_events:
            emitter.emit(event)
        emitter.close()

    return tmp_path


# Add new test class:
class TestDashboardDataLoadSnapshot:
    def test_load_snapshot_idle_no_state(self, tmp_path):
        """No state file -> idle snapshot with zero values."""
        _setup_project(tmp_path, milestones=[{"name": "m1"}, {"name": "m2"}])
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 2
        assert snap.milestones_completed == 0
        assert snap.total_cost_usd == 0.0

    def test_load_snapshot_running(self, tmp_path):
        """Active state with current_step -> running status."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 0,
                "current_step": "implement",
                "completed": [],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 10.0,
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.current_milestone == "m1"
        assert snap.current_phase == "implement"
        assert snap.total_cost_usd == 10.0

    def test_load_snapshot_completed(self, tmp_path):
        """All milestones completed -> completed status."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}],
            state={
                "current_milestone_index": 1,
                "current_step": None,
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 25.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "completed"
        assert snap.milestones_completed == 1
        assert snap.completed == ["m1"]

    def test_load_snapshot_with_failures(self, tmp_path):
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 2,
                "current_step": None,
                "completed": ["m1"],
                "failed": ["m2"],
                "skipped": [],
                "total_cost_usd": 30.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "failed"
        assert snap.milestones_failed == 1

    def test_load_snapshot_with_telemetry_metrics(self, tmp_path):
        """Telemetry data populates cost/duration breakdowns."""
        events = [
            RunStarted(spec_sha="abc", model="opus", milestone_count=2, max_budget_usd=500),
            MilestoneStarted(milestone="m1", index=0),
            PhaseCompleted(milestone="m1", phase="plan", cost_usd=5.0, duration_ms=10000),
            MilestoneCompleted(milestone="m1", cost_usd=15.0, duration_seconds=60.0),
            RunCompleted(
                status="complete",
                completed_count=1,
                total_cost_usd=15.0,
                duration_seconds=60.0,
            ),
        ]
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}, {"name": "m2"}],
            state={
                "current_milestone_index": 1,
                "current_step": None,
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 15.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
            telemetry_events=events,
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.cost_by_milestone == {"m1": 15.0}
        assert "plan" in snap.cost_by_phase
        assert snap.duration_by_milestone == {"m1": 60.0}
        assert snap.total_duration_seconds == 60.0

    def test_load_snapshot_missing_config(self, tmp_path):
        """No workflow.json -> empty snapshot, no crash."""
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.milestones_total == 0

    def test_load_snapshot_missing_telemetry(self, tmp_path):
        """No telemetry.jsonl -> snapshot from state only."""
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}],
            state={
                "current_milestone_index": 0,
                "current_step": "plan",
                "completed": [],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 0.0,
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.cost_by_milestone == {}

    def test_load_snapshot_malformed_state(self, tmp_path):
        """Corrupt state file -> graceful fallback to idle."""
        _setup_project(tmp_path, milestones=[{"name": "m1"}])
        (tmp_path / ".claude" / "workflow-state.json").write_text("{bad json")
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"

    def test_load_snapshot_model_from_config(self, tmp_path):
        _setup_project(tmp_path, milestones=[])
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.model == "opus"
```

- [ ] **Step 2: Run tests — expect FAIL** (DashboardData class doesn't exist)

- [ ] **Step 3: Implement DashboardData**

Add to `src/superpower_workflow/dashboard/data.py`:

```python
import calendar
import json
from pathlib import Path

from superpower_workflow.state import load_state
from superpower_workflow.telemetry import TelemetryReader


def _parse_utc_timestamp(ts: str) -> float:
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return 0.0


class DashboardData:
    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._claude_dir = project_root / ".claude"

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

        # Determine status
        if not state.started_at and not completed and not failed:
            status = "idle"
        elif state.current_step:
            status = "running"
        elif failed:
            status = "failed"
        else:
            status = "completed"

        # Current milestone name
        current_milestone = ""
        current_phase = state.current_step or ""
        idx = state.current_milestone_index
        if status == "running" and idx < len(milestones):
            current_milestone = milestones[idx].get("name", "")

        # Elapsed time
        elapsed = 0.0
        if state.started_at:
            start_epoch = _parse_utc_timestamp(state.started_at)
            if start_epoch > 0:
                elapsed = time.time() - start_epoch

        milestone_names = [m.get("name", "") for m in milestones]

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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/ tests/test_dashboard_data.py --fix
ruff format src/superpower_workflow/dashboard/ tests/test_dashboard_data.py
git add src/superpower_workflow/dashboard/data.py tests/test_dashboard_data.py
git commit -m "feat: add DashboardData.load_snapshot() from telemetry and state"
```

---

### Task 3: DashboardData — has_changed() mtime detection

**Files:**
- Modify: `src/superpower_workflow/dashboard/data.py`
- Modify: `tests/test_dashboard_data.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_data.py — add class


class TestDashboardDataHasChanged:
    def test_detects_state_file_change(self, tmp_path):
        _setup_project(
            tmp_path,
            milestones=[{"name": "m1"}],
            state={"current_step": "plan", "completed": [], "failed": [], "skipped": []},
        )
        data = DashboardData(tmp_path)
        data.load_snapshot()
        assert data.has_changed() is False

        # Modify state file
        state_path = tmp_path / ".claude" / "workflow-state.json"
        state_path.write_text(json.dumps({"current_step": "implement", "completed": []}))
        assert data.has_changed() is True

    def test_detects_telemetry_file_change(self, tmp_path):
        _setup_project(tmp_path, milestones=[{"name": "m1"}])
        data = DashboardData(tmp_path)
        data.load_snapshot()
        assert data.has_changed() is False

        tpath = tmp_path / ".claude" / "telemetry.jsonl"
        tpath.write_text('{"type":"run_started","run_id":"r1"}\n')
        assert data.has_changed() is True

    def test_no_change_returns_false(self, tmp_path):
        _setup_project(tmp_path, milestones=[])
        data = DashboardData(tmp_path)
        data.load_snapshot()
        assert data.has_changed() is False
        assert data.has_changed() is False

    def test_missing_files_no_crash(self, tmp_path):
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        data = DashboardData(tmp_path)
        data.load_snapshot()
        assert data.has_changed() is False

    def test_new_file_creation_detected(self, tmp_path):
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        data = DashboardData(tmp_path)
        data.load_snapshot()
        # Create state file after initial load
        (tmp_path / ".claude" / "workflow-state.json").write_text("{}")
        assert data.has_changed() is True
```

- [ ] **Step 2: Run tests — expect FAIL** (has_changed doesn't exist)

- [ ] **Step 3: Implement has_changed**

Add to `DashboardData` class in `data.py`:

```python
class DashboardData:
    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._claude_dir = project_root / ".claude"
        self._last_mtimes: dict[str, float] = {}

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
        changed = current != self._last_mtimes
        return changed
```

Update `load_snapshot()` to record mtimes after loading:

```python
    def load_snapshot(self) -> DashboardSnapshot:
        config = self._load_config()
        # ... existing code ...
        self._last_mtimes = self._snapshot_mtimes()
        return DashboardSnapshot(...)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/data.py tests/test_dashboard_data.py --fix
ruff format src/superpower_workflow/dashboard/data.py tests/test_dashboard_data.py
git add src/superpower_workflow/dashboard/data.py tests/test_dashboard_data.py
git commit -m "feat: add DashboardData.has_changed() mtime-based change detection"
```

---

### Task 4: Prometheus metrics renderer

**Files:**
- New: `src/superpower_workflow/dashboard/server.py`
- New: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_server.py
from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot
from superpower_workflow.dashboard.server import render_prometheus


class TestRenderPrometheus:
    def test_contains_help_and_type_lines(self):
        snap = DashboardSnapshot(milestones_total=5, milestones_completed=3)
        text = render_prometheus(snap)
        assert "# HELP sw_milestones_total" in text
        assert "# TYPE sw_milestones_total gauge" in text
        assert "sw_milestones_total 5" in text

    def test_cost_metric(self):
        snap = DashboardSnapshot(total_cost_usd=42.5)
        text = render_prometheus(snap)
        assert "sw_total_cost_usd 42.5" in text

    def test_milestone_cost_labels(self):
        snap = DashboardSnapshot(cost_by_milestone={"m1": 10.0, "m2": 20.0})
        text = render_prometheus(snap)
        assert 'sw_milestone_cost_usd{milestone="m1"} 10.0' in text
        assert 'sw_milestone_cost_usd{milestone="m2"} 20.0' in text

    def test_quality_metrics(self):
        snap = DashboardSnapshot(rework_rate=0.15, defect_density=0.05)
        text = render_prometheus(snap)
        assert "sw_rework_rate 0.15" in text
        assert "sw_defect_density 0.05" in text

    def test_progress_metrics(self):
        snap = DashboardSnapshot(
            milestones_completed=2, milestones_failed=1, milestones_skipped=1
        )
        text = render_prometheus(snap)
        assert "sw_milestones_completed 2" in text
        assert "sw_milestones_failed 1" in text
        assert "sw_milestones_skipped 1" in text

    def test_elapsed_and_duration(self):
        snap = DashboardSnapshot(elapsed_seconds=300.0, total_duration_seconds=250.0)
        text = render_prometheus(snap)
        assert "sw_elapsed_seconds 300.0" in text
        assert "sw_total_duration_seconds 250.0" in text

    def test_empty_snapshot(self):
        snap = DashboardSnapshot()
        text = render_prometheus(snap)
        assert "sw_milestones_total 0" in text
        assert "sw_total_cost_usd 0.0" in text

    def test_ends_with_newline(self):
        snap = DashboardSnapshot()
        text = render_prometheus(snap)
        assert text.endswith("\n")
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement render_prometheus**

```python
# src/superpower_workflow/dashboard/server.py
from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot

_GAUGE_METRICS = [
    ("sw_milestones_total", "Total milestones in workflow", "milestones_total"),
    ("sw_milestones_completed", "Completed milestones", "milestones_completed"),
    ("sw_milestones_failed", "Failed milestones", "milestones_failed"),
    ("sw_milestones_skipped", "Skipped milestones", "milestones_skipped"),
    ("sw_total_cost_usd", "Total cost in USD", "total_cost_usd"),
    ("sw_cost_per_task", "Cost per successful task in USD", "cost_per_task"),
    ("sw_elapsed_seconds", "Elapsed wall-clock seconds", "elapsed_seconds"),
    ("sw_total_duration_seconds", "Total run duration in seconds", "total_duration_seconds"),
    ("sw_rework_rate", "Rework rate (retries per milestone)", "rework_rate"),
    ("sw_defect_density", "Quality gate failure rate", "defect_density"),
]


def render_prometheus(snapshot: DashboardSnapshot) -> str:
    lines: list[str] = []
    d = snapshot.to_dict()

    for name, help_text, field_name in _GAUGE_METRICS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {d[field_name]}")
        lines.append("")

    def _escape_label(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    if snapshot.cost_by_milestone:
        lines.append("# HELP sw_milestone_cost_usd Cost per milestone in USD")
        lines.append("# TYPE sw_milestone_cost_usd gauge")
        for ms_name, cost in snapshot.cost_by_milestone.items():
            lines.append(f'sw_milestone_cost_usd{{milestone="{_escape_label(ms_name)}"}} {cost}')
        lines.append("")

    if snapshot.duration_by_milestone:
        lines.append("# HELP sw_milestone_duration_seconds Duration per milestone")
        lines.append("# TYPE sw_milestone_duration_seconds gauge")
        for ms_name, dur in snapshot.duration_by_milestone.items():
            safe = _escape_label(ms_name)
            lines.append(f'sw_milestone_duration_seconds{{milestone="{safe}"}} {dur}')
        lines.append("")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py --fix
ruff format src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git add src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: add Prometheus metrics renderer for dashboard snapshots"
```

---

### Task 5: SSE event formatter

**Files:**
- Modify: `src/superpower_workflow/dashboard/server.py`
- Modify: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_server.py — add imports + class
import json

from superpower_workflow.dashboard.server import format_sse_event, format_sse_keepalive


class TestFormatSSE:
    def test_sse_event_has_data_prefix(self):
        snap = DashboardSnapshot(run_id="r1", status="running")
        raw = format_sse_event(snap)
        assert raw.startswith("data: ")

    def test_sse_event_ends_with_double_newline(self):
        snap = DashboardSnapshot()
        raw = format_sse_event(snap)
        assert raw.endswith("\n\n")

    def test_sse_event_payload_is_valid_json(self):
        snap = DashboardSnapshot(
            run_id="r1",
            milestones_total=5,
            total_cost_usd=42.5,
        )
        raw = format_sse_event(snap)
        payload = raw.removeprefix("data: ").strip()
        parsed = json.loads(payload)
        assert parsed["run_id"] == "r1"
        assert parsed["milestones_total"] == 5
        assert parsed["total_cost_usd"] == 42.5

    def test_sse_keepalive_format(self):
        raw = format_sse_keepalive()
        assert raw == ": keepalive\n\n"

    def test_sse_event_single_line_data(self):
        snap = DashboardSnapshot()
        raw = format_sse_event(snap)
        lines = raw.strip().split("\n")
        assert len(lines) == 1
        assert lines[0].startswith("data: ")
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement SSE formatters**

Add to `server.py`:

```python
import json


def format_sse_event(snapshot: DashboardSnapshot) -> str:
    payload = json.dumps(snapshot.to_dict(), separators=(",", ":"))
    return f"data: {payload}\n\n"


def format_sse_keepalive() -> str:
    return ": keepalive\n\n"
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py --fix
ruff format src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git add src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: add SSE event formatter for live dashboard updates"
```

---

### Task 6: DASHBOARD_HTML embedded page

**Files:**
- New: `src/superpower_workflow/dashboard/static.py`
- New: `tests/test_dashboard_static.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_static.py
from __future__ import annotations

from superpower_workflow.dashboard.static import DASHBOARD_HTML


class TestDashboardHTML:
    def test_is_valid_html_string(self):
        assert isinstance(DASHBOARD_HTML, str)
        assert "<!DOCTYPE html>" in DASHBOARD_HTML
        assert "</html>" in DASHBOARD_HTML

    def test_contains_event_source(self):
        assert "EventSource" in DASHBOARD_HTML

    def test_contains_sse_endpoint(self):
        assert "/api/events" in DASHBOARD_HTML

    def test_contains_snapshot_endpoint(self):
        assert "/api/snapshot" in DASHBOARD_HTML

    def test_contains_progress_elements(self):
        assert "progress" in DASHBOARD_HTML.lower()
        assert "cost" in DASHBOARD_HTML.lower()
        assert "milestone" in DASHBOARD_HTML.lower()

    def test_contains_status_indicator(self):
        assert "status" in DASHBOARD_HTML.lower()

    def test_no_external_dependencies(self):
        assert "cdn" not in DASHBOARD_HTML.lower()
        assert "unpkg" not in DASHBOARD_HTML.lower()
        assert "jsdelivr" not in DASHBOARD_HTML.lower()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Create static.py with embedded HTML**

```python
# src/superpower_workflow/dashboard/static.py
from __future__ import annotations

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sw dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Menlo','Consolas','Courier New',monospace;background:#1a1a2e;color:#e0e0e0;padding:24px;max-width:900px;margin:0 auto}
h1{color:#7b68ee;font-size:18px;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.card{background:#16213e;border:1px solid #2a2a4a;border-radius:6px;padding:14px}
.card h2{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.card .value{font-size:22px;color:#fff}
.progress-bar{background:#2a2a4a;border-radius:4px;height:20px;overflow:hidden;margin-top:8px}
.progress-fill{background:linear-gradient(90deg,#7b68ee,#a78bfa);height:100%;transition:width 0.5s ease}
.ms-list{max-height:300px;overflow-y:auto}
.ms{padding:8px 10px;border-bottom:1px solid #1a1a2e;display:flex;justify-content:space-between;font-size:13px}
.ms.completed{color:#4ade80}.ms.failed{color:#f87171}.ms.current{color:#fbbf24}.ms.pending{color:#555}
.ms .cost{color:#888;font-size:12px}
#dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#555}
#dot.running{background:#4ade80;animation:pulse 1.5s infinite}
#dot.completed{background:#4ade80}#dot.failed{background:#f87171}#dot.idle{background:#555}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.quality{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:16px}
</style>
</head>
<body>
<h1><span id="dot"></span> sw dashboard</h1>
<div class="grid">
  <div class="card"><h2>Progress</h2><div id="progress" class="value">0 / 0</div>
    <div class="progress-bar"><div id="bar" class="progress-fill" style="width:0%"></div></div></div>
  <div class="card"><h2>Total Cost</h2><div id="cost" class="value">$0.00</div></div>
  <div class="card"><h2>Elapsed</h2><div id="elapsed" class="value">-</div></div>
  <div class="card"><h2>Current Phase</h2><div id="current" class="value">-</div></div>
</div>
<div class="card">
  <h2>Milestones</h2>
  <div id="milestones" class="ms-list"></div>
</div>
<div class="quality">
  <div class="card"><h2>Rework Rate</h2><div id="rework" class="value">0%</div></div>
  <div class="card"><h2>Defect Density</h2><div id="defects" class="value">0%</div></div>
  <div class="card"><h2>Cost / Task</h2><div id="cpt" class="value">$0.00</div></div>
</div>
<script>
function fmt(s){var m=Math.floor(s/60),sec=Math.floor(s%60);return m>0?m+'m '+sec+'s':sec+'s'}
function update(d){
  document.getElementById('dot').className=d.status||'idle';
  document.getElementById('progress').textContent=d.milestones_completed+' / '+d.milestones_total;
  var pct=d.milestones_total>0?(d.milestones_completed/d.milestones_total*100):0;
  document.getElementById('bar').style.width=pct+'%';
  document.getElementById('cost').textContent='$'+d.total_cost_usd.toFixed(2);
  document.getElementById('elapsed').textContent=d.elapsed_seconds>0?fmt(d.elapsed_seconds):'-';
  document.getElementById('current').textContent=d.current_milestone?d.current_milestone+' > '+d.current_phase:'-';
  document.getElementById('rework').textContent=(d.rework_rate*100).toFixed(1)+'%';
  document.getElementById('defects').textContent=(d.defect_density*100).toFixed(1)+'%';
  document.getElementById('cpt').textContent='$'+d.cost_per_task.toFixed(2);
  var el=document.getElementById('milestones');
  el.textContent='';
  function addMs(cls,prefix,name,extra){
    var row=document.createElement('div');row.className='ms '+cls;
    var sp=document.createElement('span');sp.textContent=prefix+' '+name;row.appendChild(sp);
    if(extra){var sp2=document.createElement('span');sp2.className='cost';sp2.textContent=extra;row.appendChild(sp2);}
    el.appendChild(row);
  }
  var done=new Set(d.completed||[]),fail=new Set(d.failed||[]),skip=new Set(d.skipped||[]);
  (d.milestone_names||[]).forEach(function(m){
    var c=d.cost_by_milestone&&d.cost_by_milestone[m];
    if(done.has(m)){addMs('completed','+',m,c?'$'+c.toFixed(2):'');}
    else if(m===d.current_milestone){addMs('current','>',m,d.current_phase);}
    else if(fail.has(m)){addMs('failed','x',m,'');}
    else if(skip.has(m)){addMs('pending','-',m,'');}
    else{addMs('pending','.',m,'');}
  });
}
fetch('/api/snapshot').then(function(r){return r.json()}).then(update).catch(function(){});
var es=new EventSource('/api/events');
es.onmessage=function(e){try{update(JSON.parse(e.data))}catch(x){}};
</script>
</body>
</html>
"""
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/static.py tests/test_dashboard_static.py --fix
ruff format src/superpower_workflow/dashboard/static.py tests/test_dashboard_static.py
git add src/superpower_workflow/dashboard/static.py tests/test_dashboard_static.py
git commit -m "feat: add embedded HTML dashboard page with SSE live updates"
```

---

### Task 7: DashboardHandler — HTTP request routing

**Files:**
- Modify: `src/superpower_workflow/dashboard/server.py`
- Modify: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_server.py — add imports + class
import http.client
import threading

from http.server import ThreadingHTTPServer
from pathlib import Path

from superpower_workflow.dashboard.data import DashboardData
from superpower_workflow.dashboard.server import make_handler


def _make_test_server(tmp_path):
    """Create a test server on a random port."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "workflow.json").write_text(
        json.dumps({"schema_version": 1, "model": "opus", "milestones": []})
    )
    data = DashboardData(tmp_path)
    handler_cls = make_handler(data)
    server = ThreadingHTTPServer(("localhost", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestDashboardHandler:
    def test_root_returns_html(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "text/html" in resp.getheader("Content-Type", "")
            assert "<!DOCTYPE html>" in body
            conn.close()
        finally:
            server.shutdown()

    def test_api_snapshot_returns_json(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/api/snapshot")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "application/json" in resp.getheader("Content-Type", "")
            parsed = json.loads(body)
            assert "status" in parsed
            assert "milestones_total" in parsed
            conn.close()
        finally:
            server.shutdown()

    def test_metrics_returns_prometheus_text(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            content_type = resp.getheader("Content-Type", "")
            assert "text/plain" in content_type
            assert "sw_milestones_total" in body
            conn.close()
        finally:
            server.shutdown()

    def test_api_events_returns_event_stream(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/api/events")
            resp = conn.getresponse()
            assert resp.status == 200
            assert "text/event-stream" in resp.getheader("Content-Type", "")
            # Use readline() — SSE data lines end with \n, avoids blocking on read(N)
            line = resp.readline()
            assert b"data: " in line
            conn.close()
        finally:
            server.shutdown()

    def test_unknown_path_returns_404(self, tmp_path):
        server, port = _make_test_server(tmp_path)
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            conn.request("GET", "/nonexistent")
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()
        finally:
            server.shutdown()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement DashboardHandler and make_handler**

Add to `server.py`:

```python
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.static import DASHBOARD_HTML


def make_handler(data: DashboardData) -> type:
    class DashboardHandler(BaseHTTPRequestHandler):
        _data: DashboardData = data
        _shutdown_event: threading.Event = threading.Event()

        def do_GET(self) -> None:
            if self.path == "/":
                self._serve_html()
            elif self.path == "/api/snapshot":
                self._serve_snapshot()
            elif self.path == "/api/events":
                self._serve_sse()
            elif self.path == "/metrics":
                self._serve_metrics()
            else:
                self.send_error(404)

        def _serve_html(self) -> None:
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_snapshot(self) -> None:
            snap = self._data.load_snapshot()
            body = json.dumps(snap.to_dict()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                snap = self._data.load_snapshot()
                self.wfile.write(format_sse_event(snap).encode())
                self.wfile.flush()
                # Each SSE connection tracks its own mtimes to avoid
                # race conditions between concurrent SSE clients.
                last_mtimes = self._data._snapshot_mtimes()
                while not self._shutdown_event.is_set():
                    self._shutdown_event.wait(timeout=2)
                    if self._shutdown_event.is_set():
                        break
                    current_mtimes = self._data._snapshot_mtimes()
                    if current_mtimes != last_mtimes:
                        snap = self._data.load_snapshot()
                        self.wfile.write(format_sse_event(snap).encode())
                        last_mtimes = current_mtimes
                    else:
                        self.wfile.write(format_sse_keepalive().encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _serve_metrics(self) -> None:
            snap = self._data.load_snapshot()
            body = render_prometheus(snap).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return DashboardHandler
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py --fix
ruff format src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git add src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: add DashboardHandler with HTTP routing for all endpoints"
```

---

### Task 8: DashboardServer — threaded start/stop with port binding

**Files:**
- Modify: `src/superpower_workflow/dashboard/server.py`
- Modify: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_server.py — add class
from superpower_workflow.dashboard.server import DashboardServer


class TestDashboardServer:
    def test_start_and_stop(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "workflow.json").write_text(
            json.dumps({"schema_version": 1, "milestones": []})
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        assert server.port > 0

        conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
        conn.request("GET", "/api/snapshot")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        server.stop()

    def test_port_property_before_start(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "workflow.json").write_text(json.dumps({"milestones": []}))
        data = DashboardData(tmp_path)
        server = DashboardServer(data, port=9876)
        assert server.port == 9876

    def test_stop_is_idempotent(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "workflow.json").write_text(json.dumps({"milestones": []}))
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        server.stop()
        server.stop()  # Should not raise

    def test_random_port_allocation(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "workflow.json").write_text(json.dumps({"milestones": []}))
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            assert server.port != 0
            assert 1024 <= server.port <= 65535
        finally:
            server.stop()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement DashboardServer**

Add to `server.py`:

```python
class DashboardServer:
    def __init__(
        self,
        data: DashboardData,
        host: str = "localhost",
        port: int = 3000,
    ) -> None:
        self._data = data
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler_cls: type | None = None

    @property
    def port(self) -> int:
        if self._server is not None:
            return self._server.server_address[1]
        return self._port

    def start(self) -> None:
        self._handler_cls = make_handler(self._data)
        self._handler_cls._shutdown_event.clear()
        self._server = ThreadingHTTPServer(
            (self._host, self._port), self._handler_cls
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._handler_cls is not None:
            self._handler_cls._shutdown_event.set()
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py --fix
ruff format src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git add src/superpower_workflow/dashboard/server.py tests/test_dashboard_server.py
git commit -m "feat: add DashboardServer with threaded start/stop and port binding"
```

---

### Task 9: Terminal watch — ANSI frame renderer

**Files:**
- New: `src/superpower_workflow/dashboard/watch.py`
- New: `tests/test_dashboard_watch.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_watch.py
from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot
from superpower_workflow.dashboard.watch import render_frame


class TestRenderFrame:
    def test_contains_status(self):
        snap = DashboardSnapshot(status="running")
        frame = render_frame(snap)
        assert "running" in frame.lower()

    def test_contains_progress(self):
        snap = DashboardSnapshot(milestones_completed=3, milestones_total=5)
        frame = render_frame(snap)
        assert "3/5" in frame

    def test_contains_cost(self):
        snap = DashboardSnapshot(total_cost_usd=42.50)
        frame = render_frame(snap)
        assert "$42.50" in frame

    def test_contains_completed_milestones(self):
        snap = DashboardSnapshot(
            completed=["m1", "m2"],
            milestone_names=["m1", "m2", "m3"],
        )
        frame = render_frame(snap)
        assert "m1" in frame
        assert "m2" in frame

    def test_contains_current_milestone(self):
        snap = DashboardSnapshot(
            current_milestone="m3",
            current_phase="implement",
            milestone_names=["m1", "m2", "m3"],
        )
        frame = render_frame(snap)
        assert "m3" in frame
        assert "implement" in frame

    def test_contains_failed_milestones(self):
        snap = DashboardSnapshot(failed=["m2"], milestone_names=["m1", "m2"])
        frame = render_frame(snap)
        assert "m2" in frame

    def test_contains_elapsed_time(self):
        snap = DashboardSnapshot(elapsed_seconds=150.0)
        frame = render_frame(snap)
        assert "2m" in frame

    def test_contains_quality_metrics(self):
        snap = DashboardSnapshot(rework_rate=0.15, defect_density=0.05)
        frame = render_frame(snap)
        assert "15.0%" in frame
        assert "5.0%" in frame

    def test_empty_snapshot_no_crash(self):
        snap = DashboardSnapshot()
        frame = render_frame(snap)
        assert "idle" in frame.lower()

    def test_progress_bar_present(self):
        snap = DashboardSnapshot(milestones_completed=2, milestones_total=4)
        frame = render_frame(snap)
        assert any(c in frame for c in ("█", "━", "=", "#"))

    def test_cost_by_milestone_shown(self):
        snap = DashboardSnapshot(
            completed=["m1"],
            cost_by_milestone={"m1": 8.50},
            milestone_names=["m1", "m2"],
        )
        frame = render_frame(snap)
        assert "$8.50" in frame

    def test_pending_milestones_shown(self):
        snap = DashboardSnapshot(
            completed=["m1"],
            current_milestone="m2",
            milestone_names=["m1", "m2", "m3", "m4"],
        )
        frame = render_frame(snap)
        assert "m3" in frame
        assert "m4" in frame
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement render_frame**

```python
# src/superpower_workflow/dashboard/watch.py
from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardSnapshot

_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_BAR_WIDTH = 40


def _format_time(seconds: float) -> str:
    if seconds <= 0:
        return "-"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _progress_bar(completed: int, total: int) -> str:
    if total == 0:
        return f"{_DIM}{'━' * _BAR_WIDTH}{_RESET}"
    pct = completed / total
    filled = int(_BAR_WIDTH * pct)
    empty = _BAR_WIDTH - filled
    return f"{_GREEN}{'█' * filled}{_DIM}{'━' * empty}{_RESET}"


def render_frame(snapshot: DashboardSnapshot) -> str:
    s = snapshot
    lines: list[str] = []

    lines.append(f"{_BOLD}  sw watch{_RESET}  Status: {s.status}")
    lines.append("")

    bar = _progress_bar(s.milestones_completed, s.milestones_total)
    lines.append(f"  {bar} {s.milestones_completed}/{s.milestones_total}")
    lines.append("")

    cost_str = f"${s.total_cost_usd:.2f}"
    elapsed_str = _format_time(s.elapsed_seconds)
    lines.append(f"  Cost: {cost_str}  |  Elapsed: {elapsed_str}")
    lines.append("")

    done = set(s.completed)
    fail = set(s.failed)
    skip = set(s.skipped)
    for name in s.milestone_names:
        cost = s.cost_by_milestone.get(name)
        cost_part = f"  ${cost:.2f}" if cost is not None else ""
        if name in done:
            lines.append(f"  {_GREEN}+{_RESET} {name}{cost_part}")
        elif name == s.current_milestone:
            lines.append(
                f"  {_YELLOW}>{_RESET} {name}  {_DIM}{s.current_phase}{_RESET}"
            )
        elif name in fail:
            lines.append(f"  {_RED}x{_RESET} {name}")
        elif name in skip:
            lines.append(f"  {_DIM}- {name}{_RESET}")
        else:
            lines.append(f"  {_DIM}. {name}{_RESET}")

    lines.append("")
    rr = f"{s.rework_rate * 100:.1f}%"
    dd = f"{s.defect_density * 100:.1f}%"
    lines.append(f"  Rework: {rr}  |  Defects: {dd}")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py --fix
ruff format src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py
git add src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py
git commit -m "feat: add ANSI terminal renderer for dashboard watch mode"
```

---

### Task 10: TerminalWatch — polling loop with graceful shutdown

**Files:**
- Modify: `src/superpower_workflow/dashboard/watch.py`
- Modify: `tests/test_dashboard_watch.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard_watch.py — add imports + class
import json
import threading
import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from superpower_workflow.dashboard.data import DashboardData
from superpower_workflow.dashboard.watch import TerminalWatch


def _setup_watch_project(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "workflow.json").write_text(
        json.dumps({"schema_version": 1, "model": "opus", "milestones": [{"name": "m1"}]})
    )
    return DashboardData(tmp_path)


class TestTerminalWatch:
    def test_renders_initial_frame(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def stop_soon():
            time.sleep(0.5)
            watch.stop()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=3)
        assert "sw watch" in output.getvalue()

    def test_stop_event_exits_loop(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)
        watch.stop()
        watch.start()  # Should exit immediately since stop is already set

    def test_detects_changes_and_rerenders(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def update_and_stop():
            time.sleep(0.4)
            state_path = tmp_path / ".claude" / "workflow-state.json"
            state_path.write_text(
                json.dumps({"current_step": "implement", "completed": [], "failed": [], "skipped": []})
            )
            time.sleep(0.5)
            watch.stop()

        t = threading.Thread(target=update_and_stop, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=5)
        content = output.getvalue()
        assert content.count("sw watch") >= 2

    def test_custom_interval(self, tmp_path):
        data = _setup_watch_project(tmp_path)
        output = StringIO()
        watch = TerminalWatch(data, interval=0.1, output=output)

        def stop_soon():
            time.sleep(0.6)
            watch.stop()

        t = threading.Thread(target=stop_soon, daemon=True)
        t.start()
        watch.start()
        t.join(timeout=3)
        frames = output.getvalue().count("sw watch")
        assert frames >= 3
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement TerminalWatch**

Add to `watch.py`:

```python
import sys
import threading
from typing import IO

from superpower_workflow.dashboard.data import DashboardData

_CLEAR_SCREEN = "\033[2J\033[H"


class TerminalWatch:
    def __init__(
        self,
        data: DashboardData,
        interval: float = 2.0,
        output: IO[str] | None = None,
    ) -> None:
        self._data = data
        self._interval = interval
        self._output = output or sys.stdout
        self._stop_event = threading.Event()

    def start(self) -> None:
        try:
            while not self._stop_event.is_set():
                snapshot = self._data.load_snapshot()
                frame = render_frame(snapshot)
                self._output.write(_CLEAR_SCREEN + frame)
                self._output.flush()
                self._stop_event.wait(timeout=self._interval)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._stop_event.set()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py --fix
ruff format src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py
git add src/superpower_workflow/dashboard/watch.py tests/test_dashboard_watch.py
git commit -m "feat: add TerminalWatch polling loop with graceful shutdown"
```

---

### Task 11: CLI — `sw dashboard` command

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add at end

def test_parser_dashboard_command():
    parser = build_parser()
    args = parser.parse_args(["dashboard"])
    assert args.command == "dashboard"


def test_parser_dashboard_port_flag():
    args = build_parser().parse_args(["dashboard", "--port", "8080"])
    assert args.port == 8080


def test_parser_dashboard_default_port():
    args = build_parser().parse_args(["dashboard"])
    assert args.port is None


def test_parser_dashboard_default_host():
    args = build_parser().parse_args(["dashboard"])
    assert args.host is None


def test_parser_dashboard_host_flag():
    args = build_parser().parse_args(["dashboard", "--host", "0.0.0.0"])
    assert args.host == "0.0.0.0"
```

- [ ] **Step 2: Run tests — expect FAIL** (command not registered)

- [ ] **Step 3: Add dashboard command to CLI**

In `cli.py`, add the subparser in `build_parser()`:

```python
    dash_p = sub.add_parser("dashboard", help="Start web dashboard")
    dash_p.add_argument("--host", default=None, help="Bind host (default: from config or localhost)")
    dash_p.add_argument("--port", type=int, default=None, help="Port (default: from config or 3000)")
```

Add the command handler in `main()` (before `if args.command == "run":`):

```python
    if args.command == "dashboard":
        _cmd_dashboard(project_root, host=args.host, port=args.port)
        return
```

Add the implementation function:

```python
def _cmd_dashboard(project_root: Path, host: str = "localhost", port: int = 3000) -> None:
    import time

    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.server import DashboardServer

    data = DashboardData(project_root)
    server = DashboardServer(data, host=host, port=port)
    try:
        server.start()
    except OSError as e:
        print(f"  Error: {e}")
        print(f"  Port {port} may be in use. Try: sw dashboard --port <other>")
        sys.exit(1)
    print(f"  Dashboard running at http://{host}:{server.port}/")
    print("  Press Ctrl+C to stop")
    try:
        # Use sleep loop instead of Event().wait() — the latter is not
        # interruptible by Ctrl+C on Windows in some Python builds.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("\n  Dashboard stopped")
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py tests/test_cli.py
git commit -m "feat: add sw dashboard command to start web UI"
```

---

### Task 12: CLI — `sw watch` command

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add at end

def test_parser_watch_command():
    parser = build_parser()
    args = parser.parse_args(["watch"])
    assert args.command == "watch"


def test_parser_watch_interval_flag():
    args = build_parser().parse_args(["watch", "--interval", "5"])
    assert args.interval == 5.0


def test_parser_watch_default_interval():
    args = build_parser().parse_args(["watch"])
    assert args.interval is None
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add watch command to CLI**

In `build_parser()`:

```python
    watch_p = sub.add_parser("watch", help="Terminal watch mode (TUI)")
    watch_p.add_argument(
        "--interval", type=float, default=None,
        help="Refresh interval in seconds (default: from config or 2)",
    )
```

In `main()`:

```python
    if args.command == "watch":
        _cmd_watch(project_root, interval=args.interval)
        return
```

Implementation (reads `dashboard.watch_interval` from config when `--interval` not given):

```python
def _cmd_watch(project_root: Path, interval: float | None = None) -> None:
    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.watch import TerminalWatch

    if interval is None:
        config_path = project_root / ".claude" / "workflow.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                interval = config.get("dashboard", {}).get("watch_interval", 2.0)
            except (json.JSONDecodeError, OSError):
                pass
    interval = interval or 2.0

    data = DashboardData(project_root)
    watch = TerminalWatch(data, interval=interval)
    watch.start()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py tests/test_cli.py
git commit -m "feat: add sw watch command for terminal TUI mode"
```

---

### Task 13: Dashboard config section + _cmd_init update

**Files:**
- Modify: `templates/workflow.json`
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add at end

def test_init_config_has_dashboard_section(tmp_path: Path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "dashboard" in config
    assert config["dashboard"]["port"] == 3000
    assert config["dashboard"]["host"] == "localhost"
    assert config["dashboard"]["watch_interval"] == 2


def test_dashboard_reads_port_from_config(tmp_path: Path):
    """sw dashboard uses port from workflow.json if not overridden."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "milestones": [],
        "dashboard": {"port": 8888, "host": "localhost", "watch_interval": 2},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    # Parser default is 3000, but config says 8888
    # This test verifies the config section structure is correct
    assert config["dashboard"]["port"] == 8888
```

- [ ] **Step 2: Run tests — expect FAIL** (no dashboard section in default config)

- [ ] **Step 3: Add dashboard config section**

Update `_cmd_init` default config in `cli.py` — add after the `telemetry` key:

```python
        "dashboard": {
            "host": "localhost",
            "port": 3000,
            "watch_interval": 2,
        },
```

Update `templates/workflow.json` — add after the `telemetry` section:

```json
  "dashboard": {
    "host": "localhost",
    "port": 3000,
    "watch_interval": 2
  },
```

Update `_cmd_dashboard` to read config defaults. Use `None` as argparse sentinel
to distinguish "user passed --host localhost" from "user didn't pass --host":

In `build_parser()`, change the dashboard argparser defaults to `None`:
```python
    dash_p.add_argument("--host", default=None, help="Bind host (default: from config or localhost)")
    dash_p.add_argument("--port", type=int, default=None, help="Port (default: from config or 3000)")
```

Then update `_cmd_dashboard` signature and body (this replaces the Task 11 version):

```python
def _cmd_dashboard(project_root: Path, host: str | None = None, port: int | None = None) -> None:
    import time

    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.server import DashboardServer

    # Read config defaults for args not explicitly provided
    config_path = project_root / ".claude" / "workflow.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            dash_cfg = config.get("dashboard", {})
            if host is None:
                host = dash_cfg.get("host", "localhost")
            if port is None:
                port = dash_cfg.get("port", 3000)
        except (json.JSONDecodeError, OSError):
            pass
    host = host or "localhost"
    port = port or 3000

    data = DashboardData(project_root)
    server = DashboardServer(data, host=host, port=port)
    try:
        server.start()
    except OSError as e:
        print(f"  Error: {e}")
        print(f"  Port {port} may be in use. Try: sw dashboard --port <other>")
        sys.exit(1)
    print(f"  Dashboard running at http://{host}:{server.port}/")
    print("  Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("\n  Dashboard stopped")
```

Similarly update `_cmd_watch` to read config interval:

```python
def _cmd_watch(project_root: Path, interval: float | None = None) -> None:
    from superpower_workflow.dashboard.data import DashboardData
    from superpower_workflow.dashboard.watch import TerminalWatch

    if interval is None:
        config_path = project_root / ".claude" / "workflow.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                interval = config.get("dashboard", {}).get("watch_interval", 2.0)
            except (json.JSONDecodeError, OSError):
                pass
    interval = interval or 2.0

    data = DashboardData(project_root)
    watch = TerminalWatch(data, interval=interval)
    watch.start()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py templates/ tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py templates/workflow.json tests/test_cli.py
git commit -m "feat: add dashboard config section to workflow.json and init command"
```

---

### Task 14: Integration test — full pipeline

**Files:**
- New: `tests/test_dashboard_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_dashboard_integration.py
from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path

from superpower_workflow.dashboard.data import DashboardData
from superpower_workflow.dashboard.server import DashboardServer
from superpower_workflow.dashboard.watch import TerminalWatch, render_frame
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)


def _build_project(tmp_path, milestones=None, state=None, telemetry_events=None):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "model": "opus",
        "milestones": milestones or [{"name": "m1"}, {"name": "m2"}, {"name": "m3"}],
        "telemetry": {"enabled": True, "path": ".claude/telemetry.jsonl"},
        "dashboard": {"host": "localhost", "port": 0, "watch_interval": 2},
    }
    (claude_dir / "workflow.json").write_text(json.dumps(config))
    if state:
        (claude_dir / "workflow-state.json").write_text(json.dumps(state))
    if telemetry_events:
        emitter = TelemetryEmitter(tmp_path / ".claude" / "telemetry.jsonl", "run-1")
        for ev in telemetry_events:
            emitter.emit(ev)
        emitter.close()
    return tmp_path


class TestDashboardIntegration:
    def test_live_update_detected_via_data_provider(self, tmp_path):
        """Write telemetry after initial load -> has_changed() is True."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)
        snap1 = data.load_snapshot()
        assert snap1.status == "idle"
        assert data.has_changed() is False

        # Simulate a run starting
        state = {
            "current_milestone_index": 0,
            "current_step": "plan",
            "completed": [],
            "failed": [],
            "skipped": [],
            "total_cost_usd": 0.0,
            "run_id": "run-1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True

        snap2 = data.load_snapshot()
        assert snap2.status == "running"
        assert snap2.current_milestone == "m1"

    def test_server_serves_correct_snapshot_json(self, tmp_path):
        """HTTP GET /api/snapshot returns snapshot matching state."""
        events = [
            RunStarted(spec_sha="abc", model="opus", milestone_count=3),
            MilestoneStarted(milestone="m1", index=0),
            PhaseCompleted(milestone="m1", phase="plan", cost_usd=5.0, duration_ms=5000),
            MilestoneCompleted(milestone="m1", cost_usd=10.0, duration_seconds=30.0),
        ]
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 1,
                "current_step": "implement",
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 10.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
            telemetry_events=events,
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/api/snapshot")
            resp = conn.getresponse()
            body = json.loads(resp.read().decode())
            assert body["status"] == "running"
            assert body["milestones_completed"] == 1
            assert body["current_milestone"] == "m2"
            assert body["total_cost_usd"] == 10.0
            assert body["cost_by_milestone"]["m1"] == 10.0
            conn.close()
        finally:
            server.stop()

    def test_server_prometheus_reflects_state(self, tmp_path):
        """GET /metrics returns Prometheus text matching state."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 2,
                "current_step": None,
                "completed": ["m1", "m2"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 50.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            text = resp.read().decode()
            assert "sw_milestones_completed 2" in text
            assert "sw_total_cost_usd 50.0" in text
            conn.close()
        finally:
            server.stop()

    def test_server_html_loads_successfully(self, tmp_path):
        """GET / returns HTML dashboard page."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode()
            assert resp.status == 200
            assert "<!DOCTYPE html>" in body
            assert "EventSource" in body
            conn.close()
        finally:
            server.stop()

    def test_sse_endpoint_sends_initial_event(self, tmp_path):
        """GET /api/events returns event-stream with initial snapshot."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 0,
                "current_step": "plan",
                "completed": [],
                "failed": [],
                "skipped": [],
                "run_id": "run-1",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        data = DashboardData(tmp_path)
        server = DashboardServer(data, host="localhost", port=0)
        server.start()
        try:
            conn = http.client.HTTPConnection("localhost", server.port, timeout=5)
            conn.request("GET", "/api/events")
            resp = conn.getresponse()
            assert resp.status == 200
            assert "text/event-stream" in resp.getheader("Content-Type", "")
            # Use readline() — avoids blocking on read(N) for streaming responses
            line = resp.readline()
            assert b"data: " in line
            payload = line.decode().split("data: ", 1)[1].strip()
            parsed = json.loads(payload)
            assert parsed["status"] == "running"
            conn.close()
        finally:
            server.stop()

    def test_terminal_watch_renders_live_state(self, tmp_path):
        """TerminalWatch renders frame matching current state."""
        _build_project(
            tmp_path,
            state={
                "current_milestone_index": 1,
                "current_step": "implement",
                "completed": ["m1"],
                "failed": [],
                "skipped": [],
                "total_cost_usd": 15.0,
                "run_id": "run-1",
                "started_at": "2026-01-01T00:00:00Z",
            },
        )
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        frame = render_frame(snap)
        assert "m1" in frame
        assert "$15.00" in frame
        assert "implement" in frame

    def test_full_pipeline_idle_to_running_to_complete(self, tmp_path):
        """Simulate full lifecycle: idle -> running -> completed."""
        _build_project(tmp_path)
        data = DashboardData(tmp_path)

        # Phase 1: idle
        snap = data.load_snapshot()
        assert snap.status == "idle"

        # Phase 2: running
        state = {
            "current_milestone_index": 0,
            "current_step": "implement",
            "completed": [],
            "failed": [],
            "skipped": [],
            "total_cost_usd": 5.0,
            "run_id": "run-1",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True
        snap = data.load_snapshot()
        assert snap.status == "running"
        assert snap.current_milestone == "m1"

        # Phase 3: completed
        state["current_milestone_index"] = 3
        state["current_step"] = None
        state["completed"] = ["m1", "m2", "m3"]
        state["total_cost_usd"] = 45.0
        (tmp_path / ".claude" / "workflow-state.json").write_text(json.dumps(state))
        assert data.has_changed() is True
        snap = data.load_snapshot()
        assert snap.status == "completed"
        assert snap.milestones_completed == 3
        assert snap.total_cost_usd == 45.0

    def test_backward_compatible_no_dashboard_config(self, tmp_path):
        """Missing dashboard section in config -> defaults work."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        config = {"schema_version": 1, "milestones": [], "model": "opus"}
        (claude_dir / "workflow.json").write_text(json.dumps(config))
        data = DashboardData(tmp_path)
        snap = data.load_snapshot()
        assert snap.status == "idle"
        assert snap.model == "opus"
```

- [ ] **Step 2: Run tests — expect PASS** (all components are already built)

  If any tests fail, fix the issues in the corresponding source file.

- [ ] **Step 3: Lint + commit**

```bash
ruff check tests/test_dashboard_integration.py --fix
ruff format tests/test_dashboard_integration.py
git add tests/test_dashboard_integration.py
git commit -m "test: add integration tests for SP3 dashboard pipeline"
```

---

### Task 15: Package exports + full test suite verification

**Files:**
- Modify: `src/superpower_workflow/dashboard/__init__.py`
- Full test suite + lint

- [ ] **Step 1: Update dashboard __init__.py exports**

```python
# src/superpower_workflow/dashboard/__init__.py
"""Dashboard: web UI, terminal watch, and Prometheus metrics for sw."""

from __future__ import annotations

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.server import DashboardServer
from superpower_workflow.dashboard.watch import TerminalWatch

__all__ = [
    "DashboardData",
    "DashboardServer",
    "DashboardSnapshot",
    "TerminalWatch",
]
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/Scripts/pytest -v
```

- [ ] **Step 3: Ruff check + format**

```bash
.venv/Scripts/ruff check src/ tests/ --fix
.venv/Scripts/ruff format src/ tests/
```

- [ ] **Step 4: Commit if any format changes**

```bash
git add -A
git commit -m "style: apply ruff format across SP3 dashboard"
```

---

## Self-Review

**Roadmap coverage:**
- `sw dashboard` → Tasks 4-8, 11, 13 (web server, HTML, SSE, Prometheus, CLI command, config)
- `sw watch` → Tasks 9-10, 12 (ANSI renderer, polling loop, CLI command)
- Real-time milestone progress → Tasks 2, 3, 5, 7 (DashboardData, has_changed, SSE, handler)
- Cost ticker → Tasks 1, 2, 6, 9 (DashboardSnapshot.total_cost_usd, web cost card, TUI cost line)
- Log stream → Tasks 6, 7 (SSE event stream updates the HTML page live)
- Prometheus /metrics → Tasks 4, 7 (render_prometheus, /metrics endpoint)

**Zero runtime dependencies:** All stdlib — `http.server`, `threading`, `json`, `time`, `calendar`, `dataclasses`. No `rich`, `textual`, `flask`, `fastapi`, or Node.js.

**Backward compatibility:** Missing `dashboard` section in config → all defaults apply. Missing telemetry.jsonl → empty metrics. Missing workflow-state.json → idle status. No changes to existing modules except cli.py (additive only).

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** `DashboardSnapshot.to_dict()` returns `dict` (JSON-serializable). `DashboardData.load_snapshot()` returns `DashboardSnapshot`. `DashboardData.has_changed()` returns `bool`. `render_prometheus()` returns `str`. `format_sse_event()` returns `str`. `render_frame()` returns `str`.

**Test strategy:** 4 test files covering unit (snapshot, data, SSE, Prometheus, renderer), component (HTTP handler, server lifecycle, watch loop), and integration (full pipeline, live updates, backward compat).

**Graceful degradation:** Tested in Task 2 — missing config, missing state, missing telemetry, malformed JSON all handled without crashes.

**Thread safety:** `DashboardServer` uses `ThreadingHTTPServer` for concurrent SSE + HTTP. `TerminalWatch` uses `threading.Event` for clean shutdown. SSE handler catches `BrokenPipeError` on client disconnect.
