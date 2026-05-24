# SP2: Telemetry & Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured JSONL telemetry that records cost, duration, tokens, test count, gap count, and quality gate results per phase per milestone. Provide a query API (TelemetryReader) for SP3 dashboard consumption. Add `sw metrics` CLI command for human/JSON output.

**Architecture:** New `telemetry.py` module with dataclass event types, append-only JSONL emitter, and read-side query API. Orchestrator emits events at every phase boundary, quality checkpoint, retry, and run start/complete. Optional `telemetry` config section; defaults to enabled for zero-config adoption.

**Tech Stack:** Python 3.11+, dataclasses (ClassVar for event type tags), json (JSONL I/O), time (timestamps + duration), pytest, ruff.

**Spec reference:** `docs/superpowers/specs/roadmap.md` — SP2 section. No dedicated spec; this plan IS the spec.

**Working directory:** `superpower-workflow/` (the repo root).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/telemetry.py` | New | TelemetryEvent hierarchy, TelemetryEmitter, TelemetryReader, metric methods |
| `src/superpower_workflow/orchestrator.py` | Edit | Emit telemetry events at all checkpoints |
| `src/superpower_workflow/cli.py` | Edit | Add `sw metrics` subcommand |
| `tests/test_telemetry.py` | New | Full test coverage for telemetry module |
| `tests/test_orchestrator.py` | Edit | Test telemetry integration in orchestrator |
| `tests/test_cli.py` | Edit | Test `sw metrics` command |

---

### Task 1: TelemetryEvent base dataclass and serialization

**Files:**
- Create: `src/superpower_workflow/telemetry.py`
- Create: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py
import json

from superpower_workflow.telemetry import TelemetryEvent


class TestTelemetryEventBase:
    def test_auto_timestamp(self):
        e = TelemetryEvent(run_id="r1")
        assert e.timestamp != ""
        assert "T" in e.timestamp
        assert e.timestamp.endswith("Z")

    def test_explicit_timestamp(self):
        e = TelemetryEvent(timestamp="2026-01-01T00:00:00Z", run_id="r1")
        assert e.timestamp == "2026-01-01T00:00:00Z"

    def test_to_dict_includes_type(self):
        e = TelemetryEvent(run_id="r1")
        d = e.to_dict()
        assert d["type"] == "base"
        assert d["run_id"] == "r1"
        assert "timestamp" in d

    def test_to_json_line_valid_json(self):
        e = TelemetryEvent(run_id="r1")
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "base"
        assert "\n" not in line

    def test_to_json_line_no_trailing_newline(self):
        e = TelemetryEvent(run_id="r1")
        line = e.to_json_line()
        assert not line.endswith("\n")
```

- [ ] **Step 2: Run tests — expect FAIL** (module doesn't exist)

- [ ] **Step 3: Implement TelemetryEvent**

```python
# src/superpower_workflow/telemetry.py
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass
class TelemetryEvent:
    """Base telemetry event with common fields."""

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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add TelemetryEvent base dataclass with JSONL serialization"
```

---

### Task 2: Run-level event types (RunStarted, RunCompleted)

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add imports and class
from superpower_workflow.telemetry import RunCompleted, RunStarted


class TestRunEvents:
    def test_run_started_type(self):
        e = RunStarted(
            run_id="r1",
            spec_sha="abc123",
            model="opus",
            milestone_count=5,
            max_budget_usd=500.0,
        )
        d = e.to_dict()
        assert d["type"] == "run_started"
        assert d["spec_sha"] == "abc123"
        assert d["model"] == "opus"
        assert d["milestone_count"] == 5
        assert d["max_budget_usd"] == 500.0

    def test_run_completed_type(self):
        e = RunCompleted(
            run_id="r1",
            status="complete",
            completed_count=3,
            failed_count=1,
            skipped_count=0,
            total_cost_usd=42.50,
            duration_seconds=1200.0,
            test_file_count=10,
        )
        d = e.to_dict()
        assert d["type"] == "run_completed"
        assert d["status"] == "complete"
        assert d["completed_count"] == 3
        assert d["total_cost_usd"] == 42.50
        assert d["test_file_count"] == 10

    def test_run_events_serialize_to_valid_jsonl(self):
        for event in [
            RunStarted(run_id="r1", model="opus"),
            RunCompleted(run_id="r1", status="complete"),
        ]:
            parsed = json.loads(event.to_json_line())
            assert "type" in parsed
            assert "run_id" in parsed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement RunStarted and RunCompleted**

Add to `telemetry.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add RunStarted and RunCompleted telemetry events"
```

---

### Task 3: Milestone-level event types

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add imports and class
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
)


class TestMilestoneEvents:
    def test_milestone_started(self):
        e = MilestoneStarted(run_id="r1", milestone="m1", index=0)
        d = e.to_dict()
        assert d["type"] == "milestone_started"
        assert d["milestone"] == "m1"
        assert d["index"] == 0

    def test_milestone_completed(self):
        e = MilestoneCompleted(
            run_id="r1", milestone="m1", cost_usd=15.0, duration_seconds=300.0
        )
        d = e.to_dict()
        assert d["type"] == "milestone_completed"
        assert d["cost_usd"] == 15.0
        assert d["duration_seconds"] == 300.0

    def test_milestone_failed(self):
        e = MilestoneFailed(
            run_id="r1", milestone="m1", phase="Phase B", reason="timeout", attempts=3
        )
        d = e.to_dict()
        assert d["type"] == "milestone_failed"
        assert d["phase"] == "Phase B"
        assert d["attempts"] == 3

    def test_milestone_skipped(self):
        e = MilestoneSkipped(
            run_id="r1", milestone="m2", reason="depends on failed: ['m1']"
        )
        d = e.to_dict()
        assert d["type"] == "milestone_skipped"
        assert "m1" in d["reason"]
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement milestone events**

Add to `telemetry.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add milestone-level telemetry events"
```

---

### Task 4: Phase-level event types

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add imports and class
from superpower_workflow.telemetry import PhaseCompleted, PhaseStarted


class TestPhaseEvents:
    def test_phase_started(self):
        e = PhaseStarted(run_id="r1", milestone="m1", phase="plan")
        d = e.to_dict()
        assert d["type"] == "phase_started"
        assert d["milestone"] == "m1"
        assert d["phase"] == "plan"

    def test_phase_completed(self):
        e = PhaseCompleted(
            run_id="r1",
            milestone="m1",
            phase="implement",
            cost_usd=25.0,
            duration_ms=60000,
            session_id="s1",
            input_tokens=5000,
            output_tokens=3000,
        )
        d = e.to_dict()
        assert d["type"] == "phase_completed"
        assert d["cost_usd"] == 25.0
        assert d["duration_ms"] == 60000
        assert d["session_id"] == "s1"
        assert d["input_tokens"] == 5000
        assert d["output_tokens"] == 3000

    def test_phase_completed_defaults_tokens_to_zero(self):
        e = PhaseCompleted(run_id="r1", milestone="m1", phase="plan")
        d = e.to_dict()
        assert d["input_tokens"] == 0
        assert d["output_tokens"] == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement phase events**

Add to `telemetry.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add phase-level telemetry events with token tracking"
```

---

### Task 5: Quality and operational event types

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add imports and class
from superpower_workflow.telemetry import (
    CoverageResult,
    GapReport,
    QualityGateResult,
    RetryAttempt,
)


class TestQualityEvents:
    def test_quality_gate_result(self):
        e = QualityGateResult(
            run_id="r1",
            milestone="m1",
            checkpoint="quality_check_b",
            gate="lint",
            passed=False,
            detail="E501 line too long",
        )
        d = e.to_dict()
        assert d["type"] == "quality_gate_result"
        assert d["passed"] is False
        assert d["gate"] == "lint"

    def test_coverage_result(self):
        e = CoverageResult(
            run_id="r1",
            milestone="m1",
            coverage_pct=85.0,
            threshold=80.0,
            passed=True,
        )
        d = e.to_dict()
        assert d["type"] == "coverage_result"
        assert d["coverage_pct"] == 85.0

    def test_retry_attempt(self):
        e = RetryAttempt(
            run_id="r1",
            milestone="m1",
            phase="Phase B",
            attempt=2,
            reason="timeout",
            delay_seconds=120,
        )
        d = e.to_dict()
        assert d["type"] == "retry_attempt"
        assert d["attempt"] == 2
        assert d["delay_seconds"] == 120

    def test_gap_report(self):
        e = GapReport(
            run_id="r1",
            milestone="m1",
            phase="plan",
            critical_gaps=0,
            important_gaps=3,
            total_gaps_found=12,
            converged=True,
        )
        d = e.to_dict()
        assert d["type"] == "gap_report"
        assert d["critical_gaps"] == 0
        assert d["total_gaps_found"] == 12
        assert d["converged"] is True
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement quality/operational events**

Add to `telemetry.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add quality gate, coverage, retry, and gap report events"
```

---

### Task 6: TelemetryEmitter (write JSONL + disabled factory)

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add class
from superpower_workflow.telemetry import TelemetryEmitter


class TestTelemetryEmitter:
    def test_emit_creates_file(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert path.exists()

    def test_emit_writes_valid_jsonl(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.emit(RunCompleted(status="complete", total_cost_usd=10.0))
        emitter.close()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert parsed["run_id"] == "r1"

    def test_emit_sets_run_id(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "run-42")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        parsed = json.loads(path.read_text().strip())
        assert parsed["run_id"] == "run-42"

    def test_emit_appends_to_existing(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        path.write_text('{"type":"old","run_id":"r0"}\n')
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["run_id"] == "r0"
        assert json.loads(lines[1])["run_id"] == "r1"

    def test_disabled_emitter_writes_nothing(self, tmp_path):
        emitter = TelemetryEmitter.disabled()
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert not (tmp_path / "telemetry.jsonl").exists()

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        assert path.exists()

    def test_close_is_idempotent(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        emitter = TelemetryEmitter(path, "r1")
        emitter.emit(RunStarted(model="opus"))
        emitter.close()
        emitter.close()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement TelemetryEmitter**

Add to `telemetry.py`:

```python
from pathlib import Path
from typing import IO


class TelemetryEmitter:
    """Append-only JSONL telemetry writer."""

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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add TelemetryEmitter with JSONL append and disabled factory"
```

---

### Task 7: Integrate emitter into Orchestrator.run() — run-level events

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add import and class
import json as json_mod


class TestTelemetryRunEvents:
    def test_telemetry_file_created(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
        assert telemetry_path.exists()

    def test_run_started_event_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        started = [e for e in events if e["type"] == "run_started"]
        assert len(started) == 1
        assert started[0]["model"] == "opus"
        assert started[0]["milestone_count"] == 1

    def test_run_completed_event_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        completed = [e for e in events if e["type"] == "run_completed"]
        assert len(completed) == 1
        assert completed[0]["status"] == "complete"
        assert completed[0]["completed_count"] == 1

    def test_telemetry_disabled_by_config(self, tmp_path):
        config = _config(tmp_path)
        config["telemetry"] = {"enabled": False}
        (tmp_path / ".claude" / "workflow.json").write_text(json_mod.dumps(config))
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "telemetry.jsonl").exists()
```

Add test helper at top of file:

```python
def _read_telemetry(tmp_path):
    path = tmp_path / ".claude" / "telemetry.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line.strip()]
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add telemetry to Orchestrator.run()**

Add imports at top of `orchestrator.py`:

```python
from superpower_workflow.telemetry import (
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)
```

In `Orchestrator.__init__`, add:

```python
self._telemetry: TelemetryEmitter | None = None
self._run_start: float = 0.0
```

In `Orchestrator.run()`, after `run_id = time.strftime(...)` and before the milestone loop, add:

```python
telemetry_config = self.config.get("telemetry", {})
telemetry_path = Path(self.cwd) / telemetry_config.get("path", ".claude/telemetry.jsonl")
if telemetry_config.get("enabled", True):
    self._telemetry = TelemetryEmitter(telemetry_path, run_id)
else:
    self._telemetry = TelemetryEmitter.disabled()

self._telemetry.emit(RunStarted(
    spec_sha=self.state.spec_sha,
    model=self.config["model"],
    milestone_count=len(milestones),
    max_budget_usd=self.config.get("max_total_budget_usd", 0),
))
self._run_start = time.monotonic()
```

In `_completion_notification`, before the webhook block, add:

```python
if self._telemetry:
    from superpower_workflow.context import _count_test_files
    self._telemetry.emit(RunCompleted(
        status=status,
        completed_count=len(self.state.completed),
        failed_count=len(self.state.failed),
        skipped_count=len(self.state.skipped),
        total_cost_usd=round(self.state.total_cost_usd, 2),
        duration_seconds=round(time.monotonic() - self._run_start, 1),
        test_file_count=_count_test_files(self.root),
    ))
    self._telemetry.close()
```

Also update the `finally` block in `run()` to close telemetry:

```python
finally:
    release_lock(self.claude_dir)
    logger.close()
    if self._telemetry:
        self._telemetry.close()
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: emit RunStarted and RunCompleted telemetry events"
```

---

### Task 8: Integrate milestone and phase events into _run_milestone

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestTelemetryMilestonePhaseEvents:
    def test_milestone_started_and_completed(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        ms_started = [e for e in events if e["type"] == "milestone_started"]
        ms_completed = [e for e in events if e["type"] == "milestone_completed"]
        assert len(ms_started) == 1
        assert ms_started[0]["milestone"] == "m1"
        assert len(ms_completed) == 1
        assert ms_completed[0]["milestone"] == "m1"
        assert ms_completed[0]["cost_usd"] > 0

    def test_all_four_phases_emitted(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        phase_started = [e for e in events if e["type"] == "phase_started"]
        phase_completed = [e for e in events if e["type"] == "phase_completed"]
        phases = [e["phase"] for e in phase_started]
        assert "plan" in phases
        assert "implement" in phases
        assert "review" in phases
        assert "push" in phases
        assert len(phase_completed) == 4

    def test_phase_completed_has_cost_and_session(self, tmp_path):
        _config(tmp_path)
        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                return_value=_ok_result(cost=5.0),
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        plan_done = [
            e for e in events if e["type"] == "phase_completed" and e["phase"] == "plan"
        ]
        assert len(plan_done) == 1
        assert plan_done[0]["cost_usd"] == 5.0
        assert plan_done[0]["session_id"] == "s1"

    def test_milestone_skipped_event(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        skipped = [e for e in events if e["type"] == "milestone_skipped"]
        assert any(e["milestone"] == "m2" for e in skipped)
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add telemetry emission to orchestrator**

Add imports at top of `orchestrator.py`:

```python
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneFailed,
    MilestoneSkipped,
    MilestoneStarted,
    PhaseCompleted,
    PhaseStarted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)
```

In `run()`, inside the milestone loop, after `logger.log("MILESTONE_START", name=name)`:

```python
self._telemetry.emit(MilestoneStarted(milestone=name, index=i))
milestone_start = time.monotonic()
```

After `logger.log("MILESTONE_COMPLETE", ...)`:

```python
self._telemetry.emit(MilestoneCompleted(
    milestone=name,
    cost_usd=round(cost, 2),
    duration_seconds=round(time.monotonic() - milestone_start, 1),
))
```

In the skip block after `logger.log("MILESTONE_SKIPPED", ...)`:

```python
self._telemetry.emit(MilestoneSkipped(
    milestone=name,
    reason=f"depends on failed: {deps_failed}",
))
```

In `_run_milestone`, before each `r = run_claude(...)` call and after each `logger.log("PHASE_X_COMPLETE", ...)`:

```python
# Before Phase A run_claude:
self._telemetry.emit(PhaseStarted(milestone=name, phase="plan"))

# After Phase A result:
self._telemetry.emit(PhaseCompleted(
    milestone=name, phase="plan",
    cost_usd=r.cost_usd, duration_ms=r.duration_ms, session_id=r.session_id,
    input_tokens=r.raw.get("input_tokens", 0) if r.raw else 0,
    output_tokens=r.raw.get("output_tokens", 0) if r.raw else 0,
))
```

Repeat the same pattern for phases B ("implement"), C ("review"), D ("push").

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: emit milestone and phase telemetry events from orchestrator"
```

---

### Task 9: Integrate quality, coverage, retry, and gap report events

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestTelemetryQualityEvents:
    def test_quality_gate_events_emitted(self, tmp_path):
        _config_with_gates(tmp_path)
        success = CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch("superpower_workflow.orchestrator.subprocess.run", side_effect=lambda cmd, **kw: (
                success if isinstance(cmd, str) else _smart_subprocess(cmd, **kw)
            )),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        gate_events = [e for e in events if e["type"] == "quality_gate_result"]
        assert len(gate_events) >= 2
        assert all(e["passed"] for e in gate_events)

    def test_retry_event_emitted_on_failure(self, tmp_path):
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        retries = [e for e in events if e["type"] == "retry_attempt"]
        assert len(retries) >= 1
        assert retries[0]["attempt"] >= 1

    def test_milestone_failed_event_emitted(self, tmp_path):
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        failed = [e for e in events if e["type"] == "milestone_failed"]
        assert len(failed) == 1
        assert failed[0]["milestone"] == "m1"

    def test_gap_report_captured_after_phase_a(self, tmp_path):
        _config(tmp_path)
        gap_data = {
            "critical_gaps": 0,
            "important_gaps": 2,
            "total_gaps_found": 5,
            "converged": True,
        }
        (tmp_path / ".claude" / ".gap-report.json").write_text(json.dumps(gap_data))

        call_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                (tmp_path / ".claude" / ".gap-report.json").write_text(
                    json.dumps(gap_data)
                )
            return _ok_result()

        with (
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        gaps = [e for e in events if e["type"] == "gap_report"]
        assert len(gaps) >= 1
        assert gaps[0]["important_gaps"] == 2
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Wire quality events into orchestrator**

Add imports to `orchestrator.py`:

```python
from superpower_workflow.telemetry import (
    CoverageResult,
    GapReport,
    QualityGateResult,
    RetryAttempt,
    # ... (all previous imports stay)
)
```

Update `_verify_quality_gates` to accept milestone/checkpoint and emit events:

```python
def _verify_quality_gates(
    self, logger: WorkflowLogger, milestone: str = "", checkpoint: str = "",
) -> tuple[bool, list[str]]:
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
                cmd, shell=True, capture_output=True, text=True,
                cwd=self.cwd, timeout=300,
            )
            passed = result.returncode == 0
            detail = "" if passed else (result.stdout or result.stderr)[:500]
            if not passed:
                failures.append(f"{gate_name}: {detail}")
                logger.log("QUALITY_GATE_FAILED", gate=gate_name)
            else:
                logger.log("QUALITY_GATE_PASSED", gate=gate_name)
            if self._telemetry:
                self._telemetry.emit(QualityGateResult(
                    milestone=milestone, checkpoint=checkpoint,
                    gate=gate_name, passed=passed, detail=detail,
                ))
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            failures.append(f"{gate_name}: {e}")
            logger.log("QUALITY_GATE_ERROR", gate=gate_name, error=str(e))
            if self._telemetry:
                self._telemetry.emit(QualityGateResult(
                    milestone=milestone, checkpoint=checkpoint,
                    gate=gate_name, passed=False, detail=str(e),
                ))
    return len(failures) == 0, failures
```

Update callers to pass milestone/checkpoint:

```python
passed, failures = self._verify_quality_gates(logger, milestone=name, checkpoint="quality_check_b")
# and
passed, failures = self._verify_quality_gates(logger, milestone=name, checkpoint="quality_check_c")
```

Update `_check_coverage` to accept `milestone` and emit CoverageResult:

```python
def _check_coverage(
    self, logger: WorkflowLogger, milestone: str = "",
) -> tuple[bool, float]:
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
                cmd, shell=True, capture_output=True,
                cwd=self.cwd, timeout=600,
            )
            if result.returncode != 0:
                logger.log("COVERAGE_CMD_FAILED", returncode=result.returncode, attempt=attempt + 1)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.log("COVERAGE_CMD_ERROR", error=str(e), attempt=attempt + 1)
        coverage = self._parse_coverage(report_path)
        if coverage >= threshold:
            logger.log("COVERAGE_PASSED", coverage=coverage, threshold=threshold)
            if self._telemetry:
                self._telemetry.emit(CoverageResult(
                    milestone=milestone, coverage_pct=coverage,
                    threshold_pct=threshold, passed=True,
                ))
            return True, extra_cost
        logger.log("COVERAGE_BELOW", coverage=coverage, threshold=threshold, attempt=attempt + 1)
        if self._telemetry:
            self._telemetry.emit(CoverageResult(
                milestone=milestone, coverage_pct=coverage,
                threshold_pct=threshold, passed=False,
            ))
        if attempt < max_attempts - 1:
            r = run_claude(
                f"Branch coverage is {coverage}% (threshold: {threshold}%). "
                f"Write additional tests for uncovered code. "
                f"Attempt {attempt + 1}/{max_attempts}.",
                model=self.config["model"], effort="high", budget=10.0,
                cwd=self.cwd, system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
            )
            extra_cost += r.cost_usd
    return False, extra_cost
```

Update `_check_coverage` callers to pass milestone:

```python
_, cov_cost = self._check_coverage(logger, milestone=name)
```

In the retry catch block in `run()`, emit RetryAttempt:

```python
except _PhaseError as e:
    if attempt < max_retries:
        delay = milestone_retry_delays[attempt]
        if self._telemetry:
            self._telemetry.emit(RetryAttempt(
                milestone=name, phase=e.phase, attempt=attempt + 1,
                reason=str(e), delay_seconds=delay,
            ))
        # ... existing log + sleep
    else:
        if self._telemetry:
            self._telemetry.emit(MilestoneFailed(
                milestone=name, phase=e.phase, reason=str(e), attempts=max_retries + 1,
            ))
```

In `_run_milestone`, after each `r = run_claude(phase_a_prompt(...))` and before `clear_phase_state`, read and emit gap report:

```python
self._emit_gap_report(name, "plan")
clear_phase_state(self.claude_dir)
```

Similarly after Phase C, before clear:

```python
self._emit_gap_report(name, "review")
clear_phase_state(self.claude_dir)
```

Add helper method:

```python
def _emit_gap_report(self, milestone: str, phase: str) -> None:
    if not self._telemetry:
        return
    gap_path = self.claude_dir / GAP_REPORT_FILE
    if not gap_path.exists():
        return
    try:
        data = json.loads(gap_path.read_text())
        self._telemetry.emit(GapReport(
            milestone=milestone, phase=phase,
            critical_gaps=data.get("critical_gaps", 0),
            architectural_gaps=data.get("architectural_gaps", 0),
            important_gaps=data.get("important_gaps", 0),
            minor_gaps=data.get("minor_gaps", 0),
            deferred_gaps=data.get("deferred_gaps", 0),
            total_gaps_found=data.get("total_gaps_found", 0),
            converged=data.get("converged", False),
        ))
    except (json.JSONDecodeError, OSError):
        pass
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: emit quality gate, retry, failure, and gap report telemetry events"
```

---

### Task 10: TelemetryReader — load and filter events

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add class


class TestTelemetryReader:
    def _write_events(self, path, events):
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_reads_all_events(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        assert len(reader.events()) == 2

    def test_empty_file_returns_empty(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        path.write_text("")
        reader = TelemetryReader(path)
        assert reader.events() == []

    def test_missing_file_returns_empty(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.events() == []

    def test_filter_by_type(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "phase_completed", "run_id": "r1", "phase": "plan"},
                {"type": "phase_completed", "run_id": "r1", "phase": "implement"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        phases = reader.events_by_type("phase_completed")
        assert len(phases) == 2

    def test_filter_by_run_id(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_started", "run_id": "r2"},
                {"type": "run_completed", "run_id": "r1"},
            ],
        )
        reader = TelemetryReader(path)
        r1_events = reader.events_for_run("r1")
        assert len(r1_events) == 2

    def test_skips_malformed_lines(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        path.write_text(
            '{"type":"run_started","run_id":"r1"}\nnot-json\n{"type":"run_completed","run_id":"r1"}\n'
        )
        reader = TelemetryReader(path)
        assert len(reader.events()) == 2

    def test_latest_run_id(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_started", "run_id": "r1"},
                {"type": "run_completed", "run_id": "r1"},
                {"type": "run_started", "run_id": "r2"},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.latest_run_id() == "r2"

    def test_latest_run_id_empty(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.latest_run_id() is None
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement TelemetryReader**

Add to `telemetry.py`:

```python
class TelemetryReader:
    """Read and query JSONL telemetry data."""

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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add TelemetryReader with event loading and filtering"
```

---

### Task 11: Cost metrics

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add class


class TestCostMetrics:
    def _write_events(self, path, events):
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_cost_by_milestone(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "milestone_completed", "run_id": "r1", "milestone": "m1", "cost_usd": 15.0},
                {"type": "milestone_completed", "run_id": "r1", "milestone": "m2", "cost_usd": 25.0},
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_milestone()
        assert costs == {"m1": 15.0, "m2": 25.0}

    def test_cost_by_phase(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 5.0},
                {"type": "phase_completed", "run_id": "r1", "phase": "implement", "cost_usd": 20.0},
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 3.0},
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_phase()
        assert costs == {"plan": 8.0, "implement": 20.0}

    def test_cost_per_successful_task(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_completed", "run_id": "r1", "total_cost_usd": 50.0, "completed_count": 5},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.cost_per_successful_task() == 10.0

    def test_cost_per_successful_task_no_completions(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_completed", "run_id": "r1", "total_cost_usd": 50.0, "completed_count": 0},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.cost_per_successful_task() == 0.0

    def test_total_cost(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_completed", "run_id": "r1", "total_cost_usd": 30.0},
                {"type": "run_completed", "run_id": "r2", "total_cost_usd": 20.0},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.total_cost() == 50.0

    def test_cost_by_milestone_filtered_by_run(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "milestone_completed", "run_id": "r1", "milestone": "m1", "cost_usd": 10.0},
                {"type": "milestone_completed", "run_id": "r2", "milestone": "m1", "cost_usd": 15.0},
            ],
        )
        reader = TelemetryReader(path)
        costs = reader.cost_by_milestone(run_id="r2")
        assert costs == {"m1": 15.0}
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement cost metrics on TelemetryReader**

Add methods to `TelemetryReader`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add cost metrics to TelemetryReader"
```

---

### Task 12: Quality and rework metrics

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add class


class TestQualityMetrics:
    def _write_events(self, path, events):
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_rework_rate(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "milestone_started", "run_id": "r1", "milestone": "m1"},
                {"type": "milestone_started", "run_id": "r1", "milestone": "m2"},
                {"type": "retry_attempt", "run_id": "r1", "milestone": "m1", "attempt": 1},
                {"type": "retry_attempt", "run_id": "r1", "milestone": "m1", "attempt": 2},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.rework_rate() == 1.0

    def test_rework_rate_no_milestones(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.rework_rate() == 0.0

    def test_defect_density(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "quality_gate_result", "run_id": "r1", "passed": True},
                {"type": "quality_gate_result", "run_id": "r1", "passed": False},
                {"type": "quality_gate_result", "run_id": "r1", "passed": True},
                {"type": "quality_gate_result", "run_id": "r1", "passed": False},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.defect_density() == 0.5

    def test_defect_density_no_checks(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.defect_density() == 0.0

    def test_quality_trend(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "gap_report", "run_id": "r1", "milestone": "m1", "phase": "plan", "total_gaps_found": 12, "critical_gaps": 2, "converged": False},
                {"type": "gap_report", "run_id": "r1", "milestone": "m1", "phase": "review", "total_gaps_found": 5, "critical_gaps": 0, "converged": True},
                {"type": "gap_report", "run_id": "r1", "milestone": "m2", "phase": "plan", "total_gaps_found": 8, "critical_gaps": 1, "converged": False},
            ],
        )
        reader = TelemetryReader(path)
        trend = reader.quality_trend()
        assert len(trend) == 3
        assert trend[0]["total_gaps_found"] == 12
        assert trend[1]["total_gaps_found"] == 5
        assert trend[2]["critical_gaps"] == 1
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement quality metrics on TelemetryReader**

Add methods to `TelemetryReader`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add quality and rework metrics to TelemetryReader"
```

---

### Task 13: Duration metrics

**Files:**
- Modify: `src/superpower_workflow/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry.py — add class


class TestDurationMetrics:
    def _write_events(self, path, events):
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_duration_by_milestone(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "milestone_completed", "run_id": "r1", "milestone": "m1", "duration_seconds": 300.0},
                {"type": "milestone_completed", "run_id": "r1", "milestone": "m2", "duration_seconds": 600.0},
            ],
        )
        reader = TelemetryReader(path)
        durations = reader.duration_by_milestone()
        assert durations == {"m1": 300.0, "m2": 600.0}

    def test_duration_by_phase(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "duration_ms": 60000},
                {"type": "phase_completed", "run_id": "r1", "phase": "implement", "duration_ms": 120000},
                {"type": "phase_completed", "run_id": "r1", "phase": "plan", "duration_ms": 30000},
            ],
        )
        reader = TelemetryReader(path)
        durations = reader.duration_by_phase()
        assert durations == {"plan": 90000, "implement": 120000}

    def test_total_duration(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "telemetry.jsonl"
        self._write_events(
            path,
            [
                {"type": "run_completed", "run_id": "r1", "duration_seconds": 1200.0},
                {"type": "run_completed", "run_id": "r2", "duration_seconds": 800.0},
            ],
        )
        reader = TelemetryReader(path)
        assert reader.total_duration() == 2000.0

    def test_duration_empty_file(self, tmp_path):
        from superpower_workflow.telemetry import TelemetryReader

        path = tmp_path / "nonexistent.jsonl"
        reader = TelemetryReader(path)
        assert reader.duration_by_milestone() == {}
        assert reader.duration_by_phase() == {}
        assert reader.total_duration() == 0.0
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement duration metrics on TelemetryReader**

Add methods to `TelemetryReader`:

```python
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
        e.get("duration_seconds", 0.0)
        for e in source
        if e.get("type") == "run_completed"
    )
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/telemetry.py tests/test_telemetry.py --fix
ruff format src/superpower_workflow/telemetry.py tests/test_telemetry.py
git add src/superpower_workflow/telemetry.py tests/test_telemetry.py
git commit -m "feat: add duration metrics to TelemetryReader"
```

---

### Task 14: CLI: sw metrics command

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add imports and tests
import json

from superpower_workflow.cli import build_parser


def test_metrics_subcommand_exists():
    parser = build_parser()
    args = parser.parse_args(["metrics"])
    assert args.command == "metrics"


def test_metrics_json_flag():
    parser = build_parser()
    args = parser.parse_args(["metrics", "--json"])
    assert args.json_output is True


def test_metrics_no_telemetry_file(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    _cmd_metrics(tmp_path)
    captured = capsys.readouterr()
    assert "No telemetry data" in captured.out


def test_metrics_human_output(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True)
    events = [
        {"type": "run_started", "run_id": "r1", "model": "opus", "milestone_count": 2},
        {"type": "milestone_completed", "run_id": "r1", "milestone": "m1", "cost_usd": 10.0, "duration_seconds": 300.0},
        {"type": "milestone_completed", "run_id": "r1", "milestone": "m2", "cost_usd": 15.0, "duration_seconds": 400.0},
        {"type": "phase_completed", "run_id": "r1", "phase": "plan", "cost_usd": 5.0, "duration_ms": 60000},
        {"type": "phase_completed", "run_id": "r1", "phase": "implement", "cost_usd": 20.0, "duration_ms": 120000},
        {"type": "run_completed", "run_id": "r1", "status": "complete", "total_cost_usd": 25.0, "completed_count": 2, "duration_seconds": 700.0},
    ]
    with open(telemetry_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    _cmd_metrics(tmp_path)
    captured = capsys.readouterr()
    assert "$25.0" in captured.out or "25.0" in captured.out
    assert "m1" in captured.out
    assert "complete" in captured.out


def test_metrics_json_output(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_metrics

    telemetry_path = tmp_path / ".claude" / "telemetry.jsonl"
    telemetry_path.parent.mkdir(parents=True)
    events = [
        {"type": "run_completed", "run_id": "r1", "status": "complete", "total_cost_usd": 25.0, "completed_count": 2, "duration_seconds": 700.0},
    ]
    with open(telemetry_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    _cmd_metrics(tmp_path, json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "total_cost" in data
    assert "cost_per_task" in data
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement sw metrics command**

In `cli.py`, add the subparser in `build_parser()`:

```python
metrics_p = sub.add_parser("metrics", help="Show telemetry metrics")
metrics_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
```

Add the handler function:

```python
def _cmd_metrics(project_root: Path, json_output: bool = False) -> None:
    from superpower_workflow.telemetry import TelemetryReader

    path = project_root / ".claude" / "telemetry.jsonl"
    reader = TelemetryReader(path)
    events = reader.events()

    if not events:
        print("  No telemetry data. Run: sw run")
        return

    if json_output:
        metrics = {
            "total_cost": reader.total_cost(),
            "cost_per_task": reader.cost_per_successful_task(),
            "cost_by_milestone": reader.cost_by_milestone(),
            "cost_by_phase": reader.cost_by_phase(),
            "duration_by_milestone": reader.duration_by_milestone(),
            "rework_rate": reader.rework_rate(),
            "defect_density": reader.defect_density(),
            "quality_trend": reader.quality_trend(),
            "total_duration": reader.total_duration(),
        }
        print(json.dumps(metrics, indent=2))
        return

    run_id = reader.latest_run_id()
    completed = reader.events_by_type("run_completed")
    latest = completed[-1] if completed else {}

    print(f"  Status: {latest.get('status', 'unknown')}")
    print(f"  Total cost: ${reader.total_cost():.2f}")
    print(f"  Cost per task: ${reader.cost_per_successful_task():.2f}")
    print(f"  Total duration: {reader.total_duration():.0f}s")
    print(f"  Rework rate: {reader.rework_rate():.1%}")
    print(f"  Defect density: {reader.defect_density():.1%}")

    cost_ms = reader.cost_by_milestone(run_id=run_id)
    if cost_ms:
        print("  Cost by milestone:")
        for name, cost in cost_ms.items():
            print(f"    {name}: ${cost:.2f}")

    cost_ph = reader.cost_by_phase(run_id=run_id)
    if cost_ph:
        print("  Cost by phase:")
        for phase, cost in cost_ph.items():
            print(f"    {phase}: ${cost:.2f}")
```

Wire into `main()`:

```python
if args.command == "metrics":
    _cmd_metrics(project_root, json_output=getattr(args, "json_output", False))
    return
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py tests/test_cli.py
git commit -m "feat: add sw metrics CLI command with human and JSON output"
```

---

### Task 15: Config: telemetry section + gitignore update

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `templates/workflow.json`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add tests


def test_init_adds_telemetry_to_gitignore(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "telemetry.jsonl" in gitignore


def test_init_default_config_has_telemetry(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "telemetry" in config
    assert config["telemetry"]["enabled"] is True


def test_orchestrator_backward_compatible_no_telemetry_key(tmp_path):
    """Config without telemetry section still works (defaults to enabled)."""
    config = {
        "schema_version": 1,
        "spec": "spec.md",
        "model": "opus",
        "budgets": {"plan": 25, "implement": 100, "review": 40, "push": 3},
        "milestones": [{"name": "m1", "spec_sections": "1", "depends_on": []}],
        "verify_commands": {"test": None, "lint": None, "format": None},
        "delay_between_phases_seconds": 0,
        "git_strategy": "main",
    }
    cd = tmp_path / ".claude"
    cd.mkdir()
    (cd / "workflow.json").write_text(json.dumps(config))

    from unittest.mock import patch

    from superpower_workflow.orchestrator import Orchestrator
    from superpower_workflow.runner import ClaudeResult

    ok = ClaudeResult(text="done", cost_usd=1.0, session_id="s1")

    def smart(cmd, **kwargs):
        from subprocess import CompletedProcess

        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1] == "status":
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1] == "rev-parse":
            return CompletedProcess(args=cmd, returncode=0, stdout="abc\n", stderr="")
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=ok),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=smart),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    from superpower_workflow.state import load_state

    state = load_state(tmp_path / ".claude")
    assert "m1" in state.completed
    assert (tmp_path / ".claude" / "telemetry.jsonl").exists()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Update config and gitignore**

In `cli.py`, update `_cmd_init` default config to include:

```python
"telemetry": {
    "enabled": True,
    "path": ".claude/telemetry.jsonl",
},
```

Add to the `entries` list in `_cmd_init`:

```python
".claude/telemetry.jsonl",
```

Update `templates/workflow.json` to add the telemetry section:

```json
"telemetry": {
  "enabled": true,
  "path": ".claude/telemetry.jsonl"
},
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py templates/workflow.json tests/test_cli.py
git commit -m "feat: add telemetry config section and gitignore entry"
```

---

### Task 16: Full integration test + backward compatibility

**Files:**
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_orchestrator.py — add class


class TestTelemetryIntegration:
    def test_full_run_event_sequence(self, tmp_path):
        """Complete run emits events in correct order."""
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        types = [e["type"] for e in events]
        assert types[0] == "run_started"
        assert types[-1] == "run_completed"
        assert "milestone_started" in types
        assert "milestone_completed" in types
        assert "phase_started" in types
        assert "phase_completed" in types

    def test_multi_milestone_run(self, tmp_path):
        _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        ms_completed = [e for e in events if e["type"] == "milestone_completed"]
        assert len(ms_completed) == 2
        milestones = [e["milestone"] for e in ms_completed]
        assert "m1" in milestones
        assert "m2" in milestones

    def test_all_run_ids_consistent(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        run_ids = {e["run_id"] for e in events}
        assert len(run_ids) == 1

    def test_existing_tests_still_pass_without_telemetry_config(self, tmp_path):
        """Backward compatibility: config without telemetry key works."""
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_telemetry_survives_milestone_failure(self, tmp_path):
        """Telemetry written even when milestones fail."""
        _config(tmp_path)
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        events = _read_telemetry(tmp_path)
        assert any(e["type"] == "run_started" for e in events)
        assert any(e["type"] == "run_completed" for e in events)
        assert any(
            e["type"] in ("milestone_failed", "retry_attempt") for e in events
        )
```

- [ ] **Step 2: Run tests — expect PASS** (all integration points already wired)

- [ ] **Step 3: Run full test suite**

```bash
.venv/Scripts/pytest -v
```

- [ ] **Step 4: Ruff check + format**

```bash
.venv/Scripts/ruff check src/ tests/ --fix
.venv/Scripts/ruff format src/ tests/
```

- [ ] **Step 5: Commit if any format changes**

```bash
git add -A
git commit -m "test: add full integration tests for SP2 telemetry pipeline"
```

---

## Self-Review

**Roadmap coverage:**
- "Structured telemetry (JSONL)" → Tasks 1-6 (event types + JSONL emitter)
- "Quality trend tracking" → Task 12 (`quality_trend()` from GapReport events)
- "Rework rate" → Task 12 (`rework_rate()` from RetryAttempt events)
- "Defect density" → Task 12 (`defect_density()` from QualityGateResult events)
- "Cost-per-successful-task" → Task 11 (`cost_per_successful_task()`)
- "Writes to `.claude/telemetry.jsonl`" → Task 6 (TelemetryEmitter) + Task 7 (integration)
- "Provides data API for SP3" → Tasks 10-13 (TelemetryReader with all metrics)
- "Tracks: tokens, cost, duration, test count, lint score, gap count" → Task 4 (tokens in PhaseCompleted), Task 2 (test_file_count in RunCompleted), Tasks 5/9 (gap counts), Tasks 11/13 (cost/duration)

**SP1 dependency:**
- Quality gate data (QualityGateResult, CoverageResult) flows from SP1's `_verify_quality_gates` and `_check_coverage` into telemetry events (Task 9)

**SP3 forward compatibility:**
- TelemetryReader is the data API that SP3's dashboard will consume
- JSONL format supports append-only writes, streaming reads, and file rotation

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** All event fields have explicit types with defaults. `ClassVar[str]` for EVENT_TYPE excluded from `asdict()`. `TelemetryEmitter(path=None)` for disabled mode. `TelemetryReader` methods accept optional `run_id` filter.

**Backward compatibility:** No telemetry config → enabled by default. Existing tests unaffected (no assertions on telemetry file absence). Method signature changes to `_verify_quality_gates` and `_check_coverage` use default parameters.

**Cost tracking:** PhaseCompleted captures `cost_usd` from ClaudeResult. MilestoneCompleted captures summed cost. RunCompleted captures total_cost_usd.

**Event count:** 12 event types covering all orchestrator lifecycle points.

**Test count estimate:** ~60-70 new tests across test_telemetry.py, test_orchestrator.py, test_cli.py.
