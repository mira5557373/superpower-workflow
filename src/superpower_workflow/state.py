"""Atomic state persistence for workflow-state.json, workflow-phase.json, and lockfile."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

STATE_FILE = "workflow-state.json"
PHASE_FILE = ".workflow-phase.json"
GAP_REPORT_FILE = ".gap-report.json"
LOCK_FILE = ".workflow.lock"

VALID_STEPS = frozenset(
    {
        "plan",
        "implement",
        "review",
        "push",
        "quality_check_b",
        "quality_check_c",
        "spec_compliance",
        "feature_verify",
        "ci_wait",
        "ci_fix",
        "ci_fix_failed",
        "parallel_wait",
        "parallel_merge",
    }
)


@dataclass
class WorkflowState:
    current_milestone_index: int = 0
    current_step: str | None = None
    last_phase_session_id: str | None = None
    plan_commit_sha: str | None = None
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    spec_sha: str = ""
    run_id: str = ""
    started_at: str = ""


@dataclass
class PhaseState:
    phase: str
    iteration: int = 0
    max_iterations: int = 5
    previous_important_gaps: int | None = None
    previous_gap_summaries: list[str] = field(default_factory=list)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(path))


def load_state(claude_dir: Path) -> WorkflowState:
    path = claude_dir / STATE_FILE
    if not path.exists():
        return WorkflowState()
    try:
        raw = json.loads(path.read_text())
        return WorkflowState(
            **{k: v for k, v in raw.items() if k in WorkflowState.__dataclass_fields__}
        )
    except (json.JSONDecodeError, TypeError):
        return WorkflowState()


def save_state(claude_dir: Path, state: WorkflowState) -> None:
    claude_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(claude_dir / STATE_FILE, asdict(state))


def load_phase_state(claude_dir: Path) -> PhaseState | None:
    path = claude_dir / PHASE_FILE
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return PhaseState(**{k: v for k, v in raw.items() if k in PhaseState.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        return None


def save_phase_state(claude_dir: Path, phase: PhaseState) -> None:
    _atomic_write(claude_dir / PHASE_FILE, asdict(phase))


GAP_VALIDATION_FILE = ".gap-validation.json"
SPEC_COMPLIANCE_FILE = ".spec-compliance.json"
FEATURE_VERIFICATION_FILE = ".feature-verification.json"
QUALITY_GATE_RESULTS_FILE = ".quality-gate-results.json"


def clear_phase_state(claude_dir: Path) -> None:
    for name in (
        PHASE_FILE,
        GAP_REPORT_FILE,
        GAP_VALIDATION_FILE,
        SPEC_COMPLIANCE_FILE,
        FEATURE_VERIFICATION_FILE,
        QUALITY_GATE_RESULTS_FILE,
    ):
        p = claude_dir / name
        p.unlink(missing_ok=True)


_logger = logging.getLogger("superpower_workflow.state")

HEARTBEAT_STALE_SECONDS = 600  # 10 min — assume hung if no heartbeat
LOCK_META_FILE = ".workflow.lock.json"


def _process_identity(pid: int | None = None) -> dict:
    """Return composite identity (pid, start_time, hostname) for a process."""
    pid = pid if pid is not None else os.getpid()
    try:
        proc = psutil.Process(pid)
        return {
            "pid": pid,
            "start_time": proc.create_time(),
            "hostname": socket.gethostname(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"pid": pid, "start_time": 0.0, "hostname": socket.gethostname()}


def is_pid_alive(pid: int, expected_start_time: float | None = None) -> bool:
    """Check if a process is alive. Optionally verify start_time to detect PID reuse."""
    if pid <= 0:
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False
        return not (
            expected_start_time is not None and abs(proc.create_time() - expected_start_time) > 1.0
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _read_lock_meta(claude_dir: Path) -> dict | None:
    meta_path = claude_dir / LOCK_META_FILE
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_lock_meta(claude_dir: Path, meta: dict) -> None:
    _atomic_write(claude_dir / LOCK_META_FILE, meta)


def _is_lock_stale(meta: dict) -> tuple[bool, str]:
    """Return (is_stale, reason). A lock is stale if: dead PID, PID reuse, or stale heartbeat."""
    pid = meta.get("pid", 0)
    start_time = meta.get("start_time", 0.0)
    hostname = meta.get("hostname", "")
    heartbeat = meta.get("heartbeat", 0.0)
    current_host = socket.gethostname()
    if hostname and hostname != current_host:
        return False, f"lock held by different host: {hostname}"
    if not is_pid_alive(pid, expected_start_time=start_time):
        return True, f"PID {pid} dead or reused"
    age = time.time() - heartbeat
    if heartbeat > 0 and age > HEARTBEAT_STALE_SECONDS:
        return True, f"heartbeat stale ({int(age)}s old, process may be hung)"
    return False, "lock active"


def acquire_lock(claude_dir: Path, force: bool = False) -> bool:
    """Acquire the workflow lock atomically.

    Uses filelock for O_EXCL semantics + composite identity (pid, start_time,
    hostname) to detect stale locks across PID reuse and machine boundaries.
    """
    claude_dir.mkdir(parents=True, exist_ok=True)
    lock_path = claude_dir / LOCK_FILE
    file_lock = FileLock(str(lock_path) + ".filelock", timeout=0)
    try:
        file_lock.acquire(blocking=False)
    except Timeout:
        return False
    try:
        existing = _read_lock_meta(claude_dir)
        if existing and not force:
            stale, reason = _is_lock_stale(existing)
            if not stale:
                return False
            _logger.warning("Stale lock detected: %s. Cleaning and acquiring fresh lock.", reason)
        identity = _process_identity()
        identity["heartbeat"] = time.time()
        _write_lock_meta(claude_dir, identity)
        lock_path.write_text(str(os.getpid()))
        return True
    finally:
        file_lock.release()


def update_lock_heartbeat(claude_dir: Path) -> None:
    """Refresh the heartbeat timestamp on the active lock."""
    meta = _read_lock_meta(claude_dir)
    if meta is None:
        return
    meta["heartbeat"] = time.time()
    _write_lock_meta(claude_dir, meta)


def get_lock_status(claude_dir: Path) -> dict | None:
    """Return lock status for inspection (sw lock --status)."""
    meta = _read_lock_meta(claude_dir)
    if meta is None:
        return None
    stale, reason = _is_lock_stale(meta)
    return {
        "pid": meta.get("pid"),
        "hostname": meta.get("hostname"),
        "start_time": meta.get("start_time"),
        "heartbeat": meta.get("heartbeat"),
        "heartbeat_age_seconds": time.time() - meta.get("heartbeat", 0),
        "stale": stale,
        "reason": reason,
    }


def release_lock(claude_dir: Path) -> None:
    (claude_dir / LOCK_FILE).unlink(missing_ok=True)
    (claude_dir / LOCK_META_FILE).unlink(missing_ok=True)
    (claude_dir / (LOCK_FILE + ".filelock")).unlink(missing_ok=True)


def load_config(claude_dir: Path) -> dict:
    path = claude_dir / "workflow.json"
    if not path.exists():
        raise FileNotFoundError(f"workflow.json not found at {claude_dir}")
    return json.loads(path.read_text())


CLONE_FILES = frozenset({"workflow.json"})
SKIP_FILES = frozenset(
    {
        STATE_FILE,
        PHASE_FILE,
        GAP_REPORT_FILE,
        LOCK_FILE,
        GAP_VALIDATION_FILE,
        SPEC_COMPLIANCE_FILE,
        FEATURE_VERIFICATION_FILE,
        QUALITY_GATE_RESULTS_FILE,
    }
)


def clone_state_to_worktree(claude_dir: Path, worktree_root: Path) -> None:
    wt_claude = worktree_root / ".claude"
    wt_claude.mkdir(parents=True, exist_ok=True)
    for src in claude_dir.iterdir():
        if src.name in SKIP_FILES or src.name.startswith(".workflow"):
            continue
        if src.name in CLONE_FILES:
            shutil.copy2(src, wt_claude / src.name)
