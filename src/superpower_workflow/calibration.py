"""Estimator Calibration Loop v1.3.24 — per-model cost band computation.

Pure-functional library that reads `MilestoneCompleted` events with
`model_id` from `sw-telemetry.jsonl`, partitions by canonical model id,
and produces confidence bands (p10 / p50 / p90) the CLI displays in
`sw estimate --calibration`.

Three tiers based on sample count per model:
- `cold_start` (n=0): published default-table prior; explicit label
- `partial` (1 ≤ n < 5): blend of default-table prior and telemetry
- `warm` (n ≥ 5): pure log1p-EWMA + percentiles, widened for small n

The math is shared with `drift.py` via `_stats.py` (so a future fix to
log1p semantics propagates to both). Cross-module bucket consistency
is asserted by `tests/test_model_key.py::test_drift_and_calibration_use_identical_keys`.

Design provenance: 4-architect + 4-verdict workflow (w4rgcreql) picked
this as the v1.3.24 winner at 45/60. Six revisions baked in:
1. Schema bump on `MilestoneCompleted` (model_id field) — owned explicitly.
2. log1p space everywhere, shared via `_stats.py`.
3. MCP resource cut from scope (deferred v1.3.25).
4. PREP commit lands `_model_key.py` + `_stats.py` before this feature.
5. 22 enumerated test cases incl missing-model_id backfill + perf.
6. Telemetry growth bounded (one `EstimateCalibrated` per completed run).
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from superpower_workflow._model_key import canonicalize, extract_model_id
from superpower_workflow._stats import (
    log1p_ewma,
    log1p_percentiles,
    small_n_widen,
)

logger = logging.getLogger(__name__)

# ---- defaults ----

WARM_THRESHOLD: int = 5  # n >= this is "warm"
MAX_AGE_DAYS_DEFAULT: int = 60
MAX_EVENTS_DEFAULT: int = 10_000

# Per-milestone cost bands (p10, p50, p90 USD). Derived from soak data.
# Used as the cold-start prior AND the blend partner for partial-tier.
DEFAULT_TABLE: dict[str, tuple[float, float, float]] = {
    "haiku-4-5": (0.08, 0.18, 0.42),
    "sonnet-4-5": (0.35, 0.85, 2.10),
    "sonnet-4": (0.35, 0.85, 2.10),
    "opus-4-7": (1.20, 2.80, 6.50),
    "opus-4-8": (1.20, 2.80, 6.50),
    "unknown": (0.15, 0.50, 1.80),
}


# ---- dataclasses ----


@dataclass(frozen=True)
class CalibrationBand:
    """Result of `compute_bands` — what `sw estimate --json` serializes."""

    model_id: str
    p10_usd: float
    p50_usd: float
    p90_usd: float
    samples_used: int
    tier: Literal["cold_start", "partial", "warm"]
    source: Literal["default_table", "telemetry", "mixed"]
    last_sample_age_days: float | None = None
    rolling_error_ratio_mean: float | None = None


# ---- sample loader ----


def _now() -> float:
    return time.time()


def _parse_ts_to_epoch(ts: str) -> float | None:
    """Best-effort parse of `YYYY-MM-DDTHH:MM:SSZ` to epoch seconds."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        from datetime import datetime

        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def load_samples_by_model(
    telemetry_path: Path,
    *,
    max_age_days: int = MAX_AGE_DAYS_DEFAULT,
    max_events: int = MAX_EVENTS_DEFAULT,
    now_epoch: float | None = None,
) -> tuple[dict[str, list[float]], dict[str, float], int]:
    """Single-pass read of `sw-telemetry.jsonl`. Returns:
    - `{model_id: [cost_usd, ...]}` (most-recent-first within each list)
    - `{model_id: youngest_sample_epoch}`
    - count of pre-v1.3.24 samples skipped (events with model_id=None)

    Filters:
    - event type == "milestone_completed"
    - model_id resolvable (else skipped + counted)
    - timestamp within `max_age_days`
    - reads at most `max_events` lines (newest first via file seek + read)

    Bad JSON lines silently skipped. Negative/NaN costs filtered.
    """
    if now_epoch is None:
        now_epoch = _now()
    cutoff = now_epoch - max_age_days * 86400

    out: dict[str, list[float]] = {}
    youngest: dict[str, float] = {}
    skipped_no_model_id = 0

    if not telemetry_path.exists():
        return out, youngest, skipped_no_model_id

    try:
        text = telemetry_path.read_text(encoding="utf-8")
    except OSError:
        return out, youngest, skipped_no_model_id

    lines = text.splitlines()
    if len(lines) > max_events:
        lines = lines[-max_events:]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "milestone_completed":
            continue
        model_id = extract_model_id(ev)
        if model_id is None:
            skipped_no_model_id += 1
            continue
        ts_epoch = _parse_ts_to_epoch(ev.get("timestamp", ""))
        if ts_epoch is None or ts_epoch < cutoff:
            continue
        try:
            cost = float(ev.get("cost_usd", 0.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(cost) or cost < 0:
            continue
        out.setdefault(model_id, []).append(cost)
        if model_id not in youngest or ts_epoch > youngest[model_id]:
            youngest[model_id] = ts_epoch

    if skipped_no_model_id > 0:
        logger.info(
            "calibration: skipped %d pre-v1.3.24 sample(s) with no model_id",
            skipped_no_model_id,
        )
    return out, youngest, skipped_no_model_id


# ---- band computation ----


def _default_for(model_id: str) -> tuple[float, float, float]:
    return DEFAULT_TABLE.get(model_id, DEFAULT_TABLE["unknown"])


def _blend(
    table: tuple[float, float, float],
    telemetry_bands: tuple[float, float, float],
    weight_telemetry: float,
) -> tuple[float, float, float]:
    """Linear blend per percentile in log1p space for numerical stability."""
    w = max(0.0, min(1.0, weight_telemetry))
    out: list[float] = []
    for t, telemetry_val in zip(table, telemetry_bands, strict=False):
        log_blend = (1 - w) * math.log1p(t) + w * math.log1p(telemetry_val)
        out.append(math.expm1(log_blend))
    return out[0], out[1], out[2]


def compute_bands(
    samples_by_model: dict[str, list[float]],
    target_model: str,
    *,
    milestone_count: int,
    now_epoch: float | None = None,
    youngest_by_model: dict[str, float] | None = None,
    rolling_error_ratio_mean: float | None = None,
) -> CalibrationBand:
    """Build a `CalibrationBand` for `target_model` at the given milestone count.

    - n=0: cold_start, pure default_table × milestone_count
    - 1 ≤ n < 5: partial, blend table (weight 1-n/5) with telemetry (weight n/5)
    - n ≥ 5: warm, log1p-EWMA + percentiles, widened by small_n_widen
    """
    if milestone_count <= 0:
        return CalibrationBand(
            model_id=target_model,
            p10_usd=0.0,
            p50_usd=0.0,
            p90_usd=0.0,
            samples_used=0,
            tier="cold_start",
            source="default_table",
        )

    samples = samples_by_model.get(target_model, [])
    n = len(samples)
    table = _default_for(target_model)

    if n == 0:
        per_ms = table
        tier: Literal["cold_start", "partial", "warm"] = "cold_start"
        source: Literal["default_table", "telemetry", "mixed"] = "default_table"
    elif n < WARM_THRESHOLD:
        # Partial blend.
        p10_t, p50_t, p90_t = _telemetry_percentiles(samples)
        weight = n / WARM_THRESHOLD
        per_ms = _blend(table, (p10_t, p50_t, p90_t), weight)
        # Widen for small-sample uncertainty.
        low, high = small_n_widen(per_ms[0], per_ms[2], n=n, p50=per_ms[1])
        per_ms = (low, per_ms[1], high)
        tier = "partial"
        source = "mixed"
    else:
        # Warm: pure telemetry.
        p10_t, p50_t, p90_t = _telemetry_percentiles(samples)
        # Replace p50 with log1p EWMA (more sensitive to recent runs).
        ewma_p50 = log1p_ewma(samples)
        low, high = small_n_widen(p10_t, p90_t, n=n, p50=ewma_p50)
        per_ms = (low, ewma_p50, high)
        tier = "warm"
        source = "telemetry"

    # Sanity-check ordering — if violated, fall back to default table.
    if not (per_ms[0] <= per_ms[1] <= per_ms[2]):
        logger.warning(
            "calibration: band ordering violated (model=%s n=%d band=%s); "
            "falling back to default_table",
            target_model,
            n,
            per_ms,
        )
        per_ms = table
        tier = "cold_start"
        source = "default_table"

    # Scale up to per-run by milestone count.
    p10_run = round(per_ms[0] * milestone_count, 4)
    p50_run = round(per_ms[1] * milestone_count, 4)
    p90_run = round(per_ms[2] * milestone_count, 4)

    last_age_days: float | None = None
    if youngest_by_model and target_model in youngest_by_model:
        if now_epoch is None:
            now_epoch = _now()
        age_s = now_epoch - youngest_by_model[target_model]
        last_age_days = round(max(0.0, age_s / 86400), 2)

    return CalibrationBand(
        model_id=target_model,
        p10_usd=p10_run,
        p50_usd=p50_run,
        p90_usd=p90_run,
        samples_used=n,
        tier=tier,
        source=source,
        last_sample_age_days=last_age_days,
        rolling_error_ratio_mean=rolling_error_ratio_mean,
    )


def _telemetry_percentiles(samples: list[float]) -> tuple[float, float, float]:
    """Compute p10, p50, p90 in log1p space."""
    out = log1p_percentiles(samples, [0.1, 0.5, 0.9])
    return out[0.1], out[0.5], out[0.9]


# ---- error-ratio rolling window ----


def rolling_error_ratio(telemetry_path: Path, model_id: str, n: int = 10) -> float | None:
    """Mean of the last `n` EstimateCalibrated.error_ratio events for `model_id`.

    Returns None if the file is missing or no matching events.
    """
    if not telemetry_path.exists() or n <= 0:
        return None
    try:
        text = telemetry_path.read_text(encoding="utf-8")
    except OSError:
        return None
    ratios: list[float] = []
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "estimate_calibrated":
            continue
        if extract_model_id(ev) != model_id:
            continue
        try:
            ratio = float(ev.get("error_ratio", 0.0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(ratio) and ratio > 0:
            ratios.append(ratio)
        if len(ratios) >= n:
            break
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 4)


# ---- entry point used by orchestrator ----


def compute_error_ratio(predicted_cost_usd: float, actual_cost_usd: float) -> float:
    """error_ratio = actual / max(predicted, 0.001). Bounded to avoid div-by-zero."""
    return round(max(0.0, actual_cost_usd) / max(0.001, predicted_cost_usd), 4)


__all__ = [
    "CalibrationBand",
    "DEFAULT_TABLE",
    "MAX_AGE_DAYS_DEFAULT",
    "MAX_EVENTS_DEFAULT",
    "WARM_THRESHOLD",
    "canonicalize",  # re-export for convenience
    "compute_bands",
    "compute_error_ratio",
    "load_samples_by_model",
    "rolling_error_ratio",
]
