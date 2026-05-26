"""Atomic state persistence for workflow-state.json, workflow-phase.json, and lockfile."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

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


def acquire_lock(claude_dir: Path) -> bool:
    lock = claude_dir / LOCK_FILE
    if lock.exists():
        return False
    lock.write_text(str(os.getpid()))
    return True


def release_lock(claude_dir: Path) -> None:
    (claude_dir / LOCK_FILE).unlink(missing_ok=True)


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
