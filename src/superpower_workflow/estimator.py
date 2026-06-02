"""Cost and duration estimates from workflow config and historical telemetry."""

from __future__ import annotations

import json
from pathlib import Path

# Calibrated from a real soak (2026-05-29): 1 small milestone, opus, $7.00 total
# including trust-but-verify ($0.83 / 12% overhead).
# Historical avg from prior runs (35 milestones, $665): ~$19/milestone on opus.
COST_PER_MS_SMALL = 8.0  # ≤5 milestones (each milestone tends to be wider)
COST_PER_MS_LARGE = 18.0  # >5 milestones (each tends to be narrower but more of them)

# Optimistic = pessimistic × OPTIMISTIC_FACTOR. Previously 0.5 (way too aggressive —
# real soak landed at the pessimistic end).
OPTIMISTIC_FACTOR = 0.7

# Overhead added when trust-but-verify (spec_compliance or feature_verification)
# is enabled. Measured: $0.83 / $6.17 = 13.5% on the 2026-05-29 soak.
TRUST_BUT_VERIFY_OVERHEAD = 0.15

MINUTES_PER_PHASE = {"plan": 30, "implement": 120, "review": 45, "push": 2}


def _load_historical_costs(project_root: Path | None) -> list[float]:
    if project_root is None:
        return []
    telemetry_path = project_root / ".claude" / "telemetry.jsonl"
    if not telemetry_path.exists():
        return []
    costs: list[float] = []
    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "milestone_completed":
                    cost = event.get("cost_usd", 0.0)
                    if cost > 0:
                        costs.append(cost)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return costs


def _trust_but_verify_enabled(config: dict) -> bool:
    validation = config.get("validation", {})
    return bool(
        validation.get("spec_compliance", False) or validation.get("feature_verification", False)
    )


def estimate(config: dict, project_root: Path | None = None) -> dict:
    milestones = config.get("milestones", [])
    n = len(milestones)
    total_minutes = sum(MINUTES_PER_PHASE.values())

    historical = _load_historical_costs(project_root)
    if historical:
        avg_cost = sum(historical) / len(historical)
        cost_pessimistic = round(n * avg_cost * 1.3, 2)
        cost_optimistic = round(n * avg_cost * 0.8, 2)
    else:
        per_ms = COST_PER_MS_SMALL if n <= 5 else COST_PER_MS_LARGE
        if _trust_but_verify_enabled(config):
            per_ms *= 1.0 + TRUST_BUT_VERIFY_OVERHEAD
        cost_pessimistic = round(n * per_ms, 2)
        cost_optimistic = round(cost_pessimistic * OPTIMISTIC_FACTOR, 2)

    return {
        "milestone_count": n,
        "cost_optimistic": cost_optimistic,
        "cost_pessimistic": cost_pessimistic,
        "duration_optimistic_min": round(n * total_minutes * OPTIMISTIC_FACTOR),
        "duration_pessimistic_min": n * total_minutes,
    }


def estimate_banded(
    config: dict,
    project_root: Path | None = None,
) -> dict:
    """v1.3.24 — calibration-aware banded estimator.

    Reads `MilestoneCompleted` events with `model_id` from telemetry,
    partitions by canonical model, returns confidence bands plus the
    same `cost_optimistic` / `cost_pessimistic` fields the legacy
    estimator emits (for backward-compat callers).

    Cold-start path: zero telemetry samples → uses `DEFAULT_TABLE`
    prior from `calibration.py`, explicitly labeled `tier=cold_start`.

    Set `SW_CALIBRATION_DISABLE=1` to skip and fall back to legacy.
    """
    import os

    from superpower_workflow._model_key import canonicalize
    from superpower_workflow.calibration import (
        compute_bands,
        load_samples_by_model,
        rolling_error_ratio,
    )

    legacy = estimate(config, project_root)
    if os.environ.get("SW_CALIBRATION_DISABLE") == "1":
        legacy["tier"] = "legacy"
        legacy["source"] = "legacy"
        legacy["model_id"] = canonicalize(config.get("model", "")) or "unknown"
        return legacy

    milestone_count = legacy["milestone_count"]
    model_id = canonicalize(config.get("model", "")) or "unknown"

    telemetry_path = None
    if project_root is not None:
        telemetry_path = project_root / ".claude" / "sw-telemetry.jsonl"
    if telemetry_path is None or not telemetry_path.exists():
        samples_by_model: dict = {}
        youngest: dict = {}
    else:
        samples_by_model, youngest, _ = load_samples_by_model(telemetry_path)
    err_ratio = (
        rolling_error_ratio(telemetry_path, model_id)
        if telemetry_path is not None and telemetry_path.exists()
        else None
    )
    band = compute_bands(
        samples_by_model,
        target_model=model_id,
        milestone_count=milestone_count,
        youngest_by_model=youngest,
        rolling_error_ratio_mean=err_ratio,
    )
    legacy.update(
        {
            "model_id": band.model_id,
            "tier": band.tier,
            "source": band.source,
            "samples_used": band.samples_used,
            "p10_usd": band.p10_usd,
            "p50_usd": band.p50_usd,
            "p90_usd": band.p90_usd,
            "rolling_error_ratio_mean": band.rolling_error_ratio_mean,
            "last_sample_age_days": band.last_sample_age_days,
        }
    )
    return legacy
