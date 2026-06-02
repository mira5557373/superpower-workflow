"""Atomic state persistence for workflow-state.json, workflow-phase.json, and lockfile."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

STATE_FILE = "workflow-state.json"
PHASE_FILE = ".workflow-phase.json"
GAP_REPORT_FILE = ".gap-report.json"
GAP_REPORT_RAW_FILE = ".gap-report.raw.json"
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
    # v1.3.17 / v1.1.9.1 — highest BudgetAlert threshold already fired
    # (50/75/90/100). Monotonic non-decreasing; survives state reload
    # so a resume doesn't re-fire crossed alerts.
    last_budget_alert_pct: int = 0
    # v1.3.19 — rate-limit dedup for DriftDetected events. Set of
    # dedup keys (f"{metric}|{bucket}|{severity}|{direction}") already
    # emitted in the CURRENT milestone. Cleared by the orchestrator
    # on each MilestoneStarted. Persists to disk so a resume mid-
    # milestone doesn't refire alerts already shown.
    drift_alerts_emitted_this_milestone: list[str] = field(default_factory=list)
    # v1.3.26 — Classed Circuit Breaker rolling failure window. Each
    # entry is a dict serialized from `circuit_breaker.BreakerWindowEntry`
    # (kept as plain dicts for forward/backward-compat JSON loading).
    # Loaded pre-v1.3.26 state files MUST default to empty list — verified
    # by `tests/test_breaker_state_migration.py`.
    breaker_window: list[dict] = field(default_factory=list)


@dataclass
class PhaseState:
    phase: str
    iteration: int = 0
    max_iterations: int = 5
    previous_important_gaps: int | None = None
    previous_gap_summaries: list[str] = field(default_factory=list)


# v1.3.5 #5 + #14 fix: per-writer-unique tmp filename + per-path lock.
#
# Pre-fix: every caller wrote to `<path>.json.tmp` — a single deterministic
# suffix. Two concurrent writers (the v1.3.4 heartbeat daemon + the
# orchestrator; or N parallel milestone workers; or sw watch + sw run)
# would race: first writer's tmp gets unlinked by os.replace, second
# writer's tmp.write_text might land on a partially-deleted file or
# `os.replace(src, dst)` would fail with `PermissionError: [WinError 32]`
# on Windows because the dst file is being held by another process.
#
# Now: each writer gets a uniquely-suffixed tmp file (pid + thread id +
# 8 random hex). A module-level `dict[Path, threading.Lock]` serializes
# concurrent writers to the SAME destination path, eliminating the
# rename collision on Windows.
#
# v1.3.13 #11: orphaned `.tmp.*` files from crashed writers are cleaned
# up by `acquire_lock` (which calls `_cleanup_orphan_tmp_files`) at the
# top of every `sw run`. `_atomic_write` does NOT clean its own siblings
# because (a) the writer can't safely delete another writer's in-flight
# tmp, and (b) the orphans are harmless beyond cosmetic clutter — but
# unbounded accumulation is still bad, so periodic GC at lock acquire
# keeps the directory tidy. The v1.3.5 #5 comment claimed this cleanup
# existed; v1.3.13 actually implemented it.
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _get_path_lock(path: Path) -> threading.Lock:
    """Return a process-wide lock for serializing writes to `path`."""
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[key] = lock
        return lock


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic write of JSON `data` to `path`.

    v1.3.5 #5: uses a per-writer unique tmp filename so concurrent writers
    to the same destination don't collide on the .tmp suffix. A per-path
    threading.Lock further serializes the write+rename pair so the second
    writer's os.replace doesn't fail with Windows ERROR_SHARING_VIOLATION.

    v1.3.6 hardening: on Windows, even with our per-path lock, os.replace
    can transiently fail with PermissionError (WinError 5/13/32) when
    antivirus or the search indexer briefly holds the destination handle
    just after our previous os.replace. Retry up to 5 times with a small
    backoff; the lock guarantees we're the only writer, so any failure
    is from an external process and is genuinely transient.
    """
    suffix = f".json.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
    tmp = path.with_suffix(suffix)
    lock = _get_path_lock(path)
    with lock:
        tmp.write_text(json.dumps(data, indent=2))
        last_err: Exception | None = None
        for attempt in range(5):
            try:
                os.replace(str(tmp), str(path))
                return
            except PermissionError as e:
                last_err = e
                # Windows transient: antivirus / indexer briefly held the
                # destination. Brief backoff with jitter from the uuid
                # suffix avoids thundering herd.
                time.sleep(0.01 * (attempt + 1))
        # Clean up the stale tmp so we don't accumulate orphans, then raise.
        import contextlib as _contextlib

        with _contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise last_err  # type: ignore[misc]


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
    # v1.3.13: ensure the target directory exists, mirroring save_state's
    # behavior. Pre-v1.3.13, save_phase_state silently relied on a prior
    # save_state(claude_dir, ...) call to mkdir; v1.3.13's _state_dir
    # routing made save_state target the parent project while
    # save_phase_state still targets the per-milestone claude_dir
    # (worker worktree in parallel). Without the mkdir, the parallel
    # worker's first save_phase_state fails with FileNotFoundError.
    claude_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(claude_dir / PHASE_FILE, asdict(phase))


GAP_VALIDATION_FILE = ".gap-validation.json"
SPEC_COMPLIANCE_FILE = ".spec-compliance.json"
FEATURE_VERIFICATION_FILE = ".feature-verification.json"
QUALITY_GATE_RESULTS_FILE = ".quality-gate-results.json"

REPORT_FILES = (
    GAP_REPORT_FILE,
    GAP_REPORT_RAW_FILE,
    GAP_VALIDATION_FILE,
    SPEC_COMPLIANCE_FILE,
    FEATURE_VERIFICATION_FILE,
    QUALITY_GATE_RESULTS_FILE,
)


def archive_reports(claude_dir: Path, milestone: str, phase: str) -> None:
    """Copy report files to .claude/reports/<milestone>/<phase>/ before clearing.

    Reports are short-lived in their canonical location (clear_phase_state wipes them
    between phases). Archiving preserves them for post-run audit.
    """
    import shutil

    safe_milestone = "".join(c if c.isalnum() or c in "-_." else "_" for c in milestone)
    safe_phase = "".join(c if c.isalnum() or c in "-_." else "_" for c in phase)
    dest = claude_dir / "reports" / safe_milestone / safe_phase
    dest.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILES:
        src = claude_dir / name
        if src.exists():
            shutil.copy2(src, dest / name.lstrip("."))


def clear_phase_state(claude_dir: Path) -> None:
    for name in (PHASE_FILE, *REPORT_FILES):
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


def _cleanup_orphan_tmp_files(claude_dir: Path) -> int:
    """v1.3.13 fix #11: clean up orphan `.tmp.*` files from crashed writers.

    The v1.3.5 #5 fix made `_atomic_write` use per-writer-unique tmp
    suffixes so concurrent writers don't collide on the rename. A
    side-effect: if a writer crashes between `tmp.write_text` and
    `os.replace`, the tmp file is left behind. The v1.3.5 comment
    claimed "orphaned .tmp.* files from crashed writers are cleaned up
    by callers that walk .claude/ at startup (acquire_lock, sw clean)"
    — but the actual implementation never did this cleanup. The audit
    flagged the lying comment.

    This helper actually walks `claude_dir` for `*.tmp` files older
    than HEARTBEAT_STALE_SECONDS (10 minutes), unlinks them, and
    returns the count cleaned. Called from `acquire_lock` so every
    sw run effectively garbage-collects orphans.
    """
    if not claude_dir.exists():
        return 0
    threshold = time.time() - HEARTBEAT_STALE_SECONDS
    cleaned = 0
    # Use glob with safe iteration; ignore stat errors.
    for orphan in claude_dir.glob("*.tmp*"):
        try:
            if orphan.stat().st_mtime < threshold:
                orphan.unlink(missing_ok=True)
                cleaned += 1
        except OSError:
            continue
    if cleaned > 0:
        _logger.info("Cleaned up %d orphan .tmp file(s) under %s", cleaned, claude_dir)
    return cleaned


def acquire_lock(claude_dir: Path, force: bool = False) -> bool:
    """Acquire the workflow lock atomically.

    Uses filelock for O_EXCL semantics + composite identity (pid, start_time,
    hostname) to detect stale locks across PID reuse and machine boundaries.

    v1.3.13 fix #11: also walks claude_dir for orphan .tmp files (from
    crashed writers in prior runs) and unlinks any older than
    HEARTBEAT_STALE_SECONDS. The v1.3.5 #5 comment claimed this happened
    but the code never did it.
    """
    claude_dir.mkdir(parents=True, exist_ok=True)
    # v1.3.13 #11: opportunistic orphan cleanup at acquire time.
    _cleanup_orphan_tmp_files(claude_dir)
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


# v1.3.4 #9 fix: background-timer heartbeat. Previously the orchestrator
# called `update_lock_heartbeat` only at the top of each milestone iteration.
# A single Phase B running longer than HEARTBEAT_STALE_SECONDS (600s) would
# let another orchestrator decide the first was hung and force-clean the
# lock — two orchestrators concurrently rewriting state, double-billing,
# and corrupting git history.
#
# A daemon thread now refreshes the heartbeat independent of phase boundaries.


class HeartbeatThread:
    """Background daemon thread that refreshes the lock heartbeat every
    `interval` seconds while the orchestrator runs. Stopped via `stop()`
    or by program exit (daemon=True).

    Safe to call start()/stop() multiple times; idempotent. If the lock
    meta file is missing or write fails, the thread silently continues —
    a transient I/O hiccup must not crash the orchestrator.
    """

    def __init__(self, claude_dir: Path, interval: float = 60.0):
        import threading

        self._claude_dir = claude_dir
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import threading

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="sw-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        import contextlib

        while not self._stop_event.is_set():
            with contextlib.suppress(Exception):
                update_lock_heartbeat(self._claude_dir)
            # wait() returns True if stop_event set; False on timeout.
            if self._stop_event.wait(self._interval):
                return


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
