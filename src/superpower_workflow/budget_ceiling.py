"""Rolling Cost Ceilings v1.3.20 — pure-functional cross-run cost accountant.

Reads `telemetry.jsonl` for `RunCompleted` events, sums `total_cost_usd`
over three rolling windows (24h / 7d / 30d ending at now-UTC), and
evaluates configured ceilings declared in workflow.json under
`cost_ceilings.{daily, weekly, monthly}`.

Distinct from BudgetAlert (v1.3.17) — that's WITHIN-run percent-of-cap
crossings; this is ACROSS-run absolute spend over rolling windows.

Design provenance: 4-architect + 4-verdict workflow (wcpy1qzhh) picked
this as the v1.3.20 reliability survivor. Six adversarial-review
revisions baked into this implementation:

1. Deterministic synthetic-replay test seeded with fixed-seed lognormal
   spend, asserts zero false-positive blocks at ceiling = 2× p95.
2. CostCeilingEvaluated coexists with BudgetAlert — they signal
   different things and both fire independently per design.
3. `--ignore-ceiling` requires `SW_ALLOW_CEILING_BYPASS=1` env var OR
   TTY confirmation; bare flag in non-TTY shell with no env exits 8.
4. `sw budget reset --confirm` emits CEILING_RESET audit event with
   prior_spend; the reset checkpoint is hash-chained.
5. Preflight runs at THREE gates: run_start, milestone_start,
   phase_e_retry — explicit `preflight_gate` field on every event.
6. Missing/corrupt telemetry defaults to ALLOW with
   `source="no_history"`, never blocks on unverifiable history.

The accountant is pure-functional — no mutation, no caching. Concurrency
safety is a separate `.claude/.ceiling.lock` held only for the
evaluate→decide→emit window. This prevents racing run starts past the
cap without blocking long-running phases.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# ---- type aliases ----

WindowName = Literal["day", "week", "month"]
CeilingMode = Literal["warn", "block"]
CeilingDecision = Literal["allow", "warn", "block", "no_history", "bypass"]
PreflightGate = Literal["run_start", "milestone_start", "phase_e_retry"]
SourceKind = Literal["telemetry", "no_history", "partial_history"]

WINDOW_DURATIONS: dict[WindowName, timedelta] = {
    "day": timedelta(hours=24),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}

WINDOW_ORDER: tuple[WindowName, ...] = ("day", "week", "month")

CONFIG_KEY_BY_WINDOW: dict[WindowName, str] = {
    "day": "daily",
    "week": "weekly",
    "month": "monthly",
}

# Exit codes
EXIT_CEILING_BLOCKED: int = 7
EXIT_BYPASS_UNAUTHORIZED: int = 8


# ---- dataclasses ----


@dataclass(frozen=True)
class ContributingRun:
    run_id: str
    total_cost_usd: float
    completed_at_utc: str  # ISO8601


@dataclass(frozen=True)
class WindowAccounting:
    """Snapshot of spend in one rolling window."""

    window: WindowName
    window_start_utc: str
    window_end_utc: str
    current_spend_usd: float
    contributing_runs: tuple[ContributingRun, ...]
    source: SourceKind


@dataclass(frozen=True)
class CeilingEvaluation:
    """Decision for one (window, ceiling) pair."""

    window: WindowName
    accounting: WindowAccounting
    ceiling_usd: float | None  # None => ceiling not configured for this window
    projected_run_cost_usd: float
    headroom_usd: float
    mode: CeilingMode
    decision: CeilingDecision


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of a preflight check across all configured windows."""

    evaluations: tuple[CeilingEvaluation, ...]
    blocked: bool
    blocking_window: WindowName | None
    bypass_used: bool = False


@dataclass
class CeilingConfig:
    """One ceiling: amount + mode. Parsed from workflow.json dict."""

    usd: float = 0.0
    mode: CeilingMode = "block"


@dataclass
class CostCeilingsConfig:
    """All three optional ceilings. Built from workflow.json[cost_ceilings]."""

    daily: CeilingConfig | None = None
    weekly: CeilingConfig | None = None
    monthly: CeilingConfig | None = None
    # Reset checkpoints: per-window timestamps; events completed at or
    # before this timestamp are excluded from the window sum.
    reset_checkpoints: dict[str, str] = field(default_factory=dict)

    def for_window(self, window: WindowName) -> CeilingConfig | None:
        if window == "day":
            return self.daily
        if window == "week":
            return self.weekly
        if window == "month":
            return self.monthly
        return None

    def any_configured(self) -> bool:
        return any(self.for_window(w) is not None for w in WINDOW_ORDER)


# ---- config parsing ----


def parse_ceilings(raw: dict | None) -> CostCeilingsConfig:
    """Parse `cost_ceilings` block from workflow.json (dict, not pydantic)."""
    if not raw:
        return CostCeilingsConfig()

    def _one(key: str) -> CeilingConfig | None:
        sub = raw.get(key)
        if sub is None:
            return None
        if isinstance(sub, int | float):
            # Shorthand: bare number, default mode="block".
            usd = float(sub)
            if usd <= 0:
                return None
            return CeilingConfig(usd=usd, mode="block")
        if not isinstance(sub, dict):
            return None
        try:
            usd = float(sub.get("usd", 0.0))
        except (TypeError, ValueError):
            return None
        if usd <= 0:
            return None
        mode_raw = sub.get("mode", "block")
        mode: CeilingMode = "block" if mode_raw == "block" else "warn"
        return CeilingConfig(usd=usd, mode=mode)

    checkpoints_raw = raw.get("reset_checkpoints", {})
    checkpoints = (
        {k: str(v) for k, v in checkpoints_raw.items() if isinstance(k, str)}
        if isinstance(checkpoints_raw, dict)
        else {}
    )

    return CostCeilingsConfig(
        daily=_one("daily"),
        weekly=_one("weekly"),
        monthly=_one("monthly"),
        reset_checkpoints=checkpoints,
    )


# ---- helpers ----


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime | None:
    """Parse `YYYY-MM-DDTHH:MM:SSZ` (the timestamp format used everywhere
    in telemetry). Returns None on any parse error."""
    if not s or not isinstance(s, str):
        return None
    try:
        # Telemetry uses "Z" suffix. Python <3.11 needs +00:00 substitution.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


# ---- sample loader ----


def load_window_spend(
    telemetry_path: Path,
    *,
    now_utc: datetime,
    window: WindowName,
    reset_checkpoint: str | None = None,
) -> WindowAccounting:
    """Single-pass JSONL read, sums RunCompleted events in [now-Δ, now].

    Defaults to `source="no_history"` if file missing, unreadable, or
    contains zero RunCompleted events. Bad JSON lines are skipped — if
    more than 50% of lines fail to parse, returns `no_history` (safety
    bias toward allow).

    `reset_checkpoint` (ISO8601, optional): events completed at or before
    this timestamp are excluded — supports `sw budget reset` semantics.
    """
    duration = WINDOW_DURATIONS[window]
    window_start = now_utc - duration
    win_start_str = _iso(window_start)
    win_end_str = _iso(now_utc)
    reset_dt = _parse_iso(reset_checkpoint) if reset_checkpoint else None

    if not telemetry_path.exists():
        return WindowAccounting(
            window=window,
            window_start_utc=win_start_str,
            window_end_utc=win_end_str,
            current_spend_usd=0.0,
            contributing_runs=(),
            source="no_history",
        )

    try:
        text = telemetry_path.read_text(encoding="utf-8")
    except OSError:
        return WindowAccounting(
            window=window,
            window_start_utc=win_start_str,
            window_end_utc=win_end_str,
            current_spend_usd=0.0,
            contributing_runs=(),
            source="no_history",
        )

    lines = [ln for ln in text.splitlines() if ln.strip()]
    bad_count = 0
    total_lines = 0
    contributing: list[ContributingRun] = []
    oldest_seen: datetime | None = None

    for line in lines:
        total_lines += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            bad_count += 1
            continue
        if event.get("type") != "run_completed":
            continue
        ts_raw = event.get("timestamp", "")
        ts = _parse_iso(ts_raw)
        if ts is None:
            continue
        if oldest_seen is None or ts < oldest_seen:
            oldest_seen = ts
        if reset_dt is not None and ts <= reset_dt:
            continue
        if ts < window_start or ts > now_utc:
            continue
        try:
            cost = float(event.get("total_cost_usd", 0.0))
        except (TypeError, ValueError):
            continue
        if cost < 0 or cost != cost:  # NaN check
            continue
        contributing.append(
            ContributingRun(
                run_id=str(event.get("run_id", "")),
                total_cost_usd=cost,
                completed_at_utc=_iso(ts),
            )
        )

    # Source classification.
    if total_lines > 0 and bad_count / total_lines > 0.5:
        source: SourceKind = "no_history"
    elif not contributing:
        source = "no_history"
    elif oldest_seen is not None and oldest_seen > window_start:
        # We have history but it doesn't cover the full window.
        source = "partial_history"
    else:
        source = "telemetry"

    # Sort contributing runs by total_cost_usd desc (stable display).
    contributing.sort(key=lambda r: r.total_cost_usd, reverse=True)
    total_spend = sum(r.total_cost_usd for r in contributing)

    return WindowAccounting(
        window=window,
        window_start_utc=win_start_str,
        window_end_utc=win_end_str,
        current_spend_usd=round(total_spend, 4),
        contributing_runs=tuple(contributing),
        source=source,
    )


# ---- evaluator ----


def evaluate_ceilings(
    telemetry_path: Path,
    *,
    ceilings: CostCeilingsConfig,
    projected_run_cost_usd: float,
    now_utc: datetime | None = None,
) -> PreflightResult:
    """Pure evaluator: iterate day/week/month; return decisions.

    Block if ANY window's mode is `block` and
    `current_spend + projected_run_cost >= ceiling`. The first window
    that blocks (in day/week/month order) becomes `blocking_window`.

    When `source="no_history"` the decision is always `allow` regardless
    of mode (verdict revision #6).
    """
    if now_utc is None:
        now_utc = _now_utc()

    evals: list[CeilingEvaluation] = []
    blocked = False
    blocking_window: WindowName | None = None

    for window in WINDOW_ORDER:
        cfg = ceilings.for_window(window)
        checkpoint = ceilings.reset_checkpoints.get(CONFIG_KEY_BY_WINDOW[window])
        accounting = load_window_spend(
            telemetry_path,
            now_utc=now_utc,
            window=window,
            reset_checkpoint=checkpoint,
        )
        if cfg is None:
            # Unconfigured window: surface accounting for visibility but no decision.
            evals.append(
                CeilingEvaluation(
                    window=window,
                    accounting=accounting,
                    ceiling_usd=None,
                    projected_run_cost_usd=round(projected_run_cost_usd, 4),
                    headroom_usd=0.0,
                    mode="warn",
                    decision="allow",
                )
            )
            continue

        proj = max(0.0, projected_run_cost_usd)
        headroom = cfg.usd - (accounting.current_spend_usd + proj)
        if accounting.source == "no_history":
            decision: CeilingDecision = "no_history"
        elif accounting.current_spend_usd + proj >= cfg.usd:
            decision = cfg.mode  # "warn" or "block"
            if cfg.mode == "block" and not blocked:
                blocked = True
                blocking_window = window
        else:
            decision = "allow"

        evals.append(
            CeilingEvaluation(
                window=window,
                accounting=accounting,
                ceiling_usd=cfg.usd,
                projected_run_cost_usd=round(proj, 4),
                headroom_usd=round(headroom, 4),
                mode=cfg.mode,
                decision=decision,
            )
        )

    return PreflightResult(
        evaluations=tuple(evals),
        blocked=blocked,
        blocking_window=blocking_window,
    )


# ---- file lock for preflight evaluations ----


class CeilingLock:
    """Lightweight file-lock for the evaluate→emit window.

    Distinct from the milestone lock — held only for the brief decision
    window, not for the entire run. Reuses the `state.acquire_lock`
    stale-detection pattern (lock files older than `stale_after_s` are
    reclaimed).
    """

    def __init__(self, lock_path: Path, *, stale_after_s: float = 30.0) -> None:
        self._path = lock_path
        self._stale_after_s = stale_after_s
        self._held = False

    def acquire(self, *, timeout_s: float = 2.0) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                # Atomic create-only.
                fd = self._path.open("x")
                fd.write(str(time.time()))
                fd.close()
                self._held = True
                return True
            except FileExistsError:
                # Stale-lock detection.
                try:
                    age = time.time() - self._path.stat().st_mtime
                    if age > self._stale_after_s:
                        self._path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.01)
        return False

    def release(self) -> None:
        if self._held:
            self._path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> CeilingLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# ---- bypass authorization ----


def is_bypass_authorized(
    *,
    ignore_flag: bool,
    env: dict[str, str] | None = None,
    stdin_is_tty: bool = False,
    tty_confirm: bool | None = None,
) -> tuple[bool, str]:
    """Verdict revision #3: enforce defense-in-depth on `--ignore-ceiling`.

    Returns (authorized, reason). Reason is one of:
    - "flag_only_no_env_no_tty" (unauthorized)
    - "env_var_set"
    - "tty_confirmed"
    - "tty_declined" (unauthorized)
    - "no_flag" (not requested)
    """
    if not ignore_flag:
        return False, "no_flag"
    e = env if env is not None else {}
    if e.get("SW_ALLOW_CEILING_BYPASS") == "1":
        return True, "env_var_set"
    if stdin_is_tty:
        if tty_confirm is True:
            return True, "tty_confirmed"
        return False, "tty_declined"
    return False, "flag_only_no_env_no_tty"


# ---- bypass audit + reset audit data builders ----


def build_bypass_audit_payload(
    *,
    window: WindowName,
    current_spend_usd: float,
    ceiling_usd: float,
    projected_run_cost_usd: float,
    auth_reason: str,
) -> dict:
    return {
        "window": window,
        "current_spend_usd": round(current_spend_usd, 4),
        "ceiling_usd": round(ceiling_usd, 4),
        "projected_run_cost_usd": round(projected_run_cost_usd, 4),
        "auth_reason": auth_reason,
    }


def build_reset_audit_payload(
    *,
    window: WindowName,
    prior_spend_usd: float,
    cleared_at_utc: str,
) -> dict:
    return {
        "window": window,
        "prior_spend_usd": round(prior_spend_usd, 4),
        "cleared_at_utc": cleared_at_utc,
    }
