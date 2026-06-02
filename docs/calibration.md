# Estimator Calibration Loop (v1.3.24)

`sw estimate` now produces **per-model confidence-banded** cost forecasts
that calibrate themselves from project telemetry. Closes the
**3.8× over-projection** the v1.3.21-e2e soak measured on haiku-4-5.

## What problem this solves

Pre-v1.3.24 `sw estimate` used hard-coded `COST_PER_MS_*` constants
that ignored which model the project was using. Real-world numbers:

| Model | Estimator said | Actual (soak) | Error |
|---|---|---|---|
| haiku-4-5 | $5.60-$8.00 / milestone | $1.49 / milestone | **3.8× over** |

Cost ceilings, budget alerts, and capacity planning all suffer when
the estimator is this wrong. v1.3.24 fixes it by **learning from
telemetry** — each completed milestone trains the per-model band that
subsequent estimates use.

## Three tiers, automatic transition

| Tier | Trigger | Source |
|---|---|---|
| `cold_start` | 0 same-model samples in history | `DEFAULT_TABLE` prior |
| `partial` | 1 ≤ n < 5 same-model samples | blend of table + telemetry |
| `warm` | n ≥ 5 same-model samples | pure-telemetry log1p EWMA + percentiles |

Transitions happen automatically as samples accumulate. No
configuration knobs needed for normal use.

## CLI

```bash
sw estimate                   # banded, per-model
sw estimate --json            # machine-readable schema
sw estimate --calibration     # per-model breakdown table
sw estimate --legacy          # force v1.3.23 single-pair output
```

### Banded output

```
Spec: spec.md (3 milestones)
Estimate: $0.54  [p10 $0.24 - p90 $1.26]
  model=haiku-4-5  samples=2  tier=partial  age=0.05d
Duration: 50-72 min
```

### `--calibration` subview

```
  Model          n    p10     p50     p90    err   age
  haiku-4-5      8   $0.10   $0.18   $0.42   1.02   0.1d  [warm]
  sonnet-4-5     0   $0.35   $0.85   $2.10    -      -    [cold_start]
  unknown        —   $0.15   $0.50   $1.80    -      -    [cold_start]
```

`err` is the rolling mean of the last 10 `EstimateCalibrated.error_ratio`
events for that model — close to 1.0 means the estimator is accurate.

### `--json` schema (v1)

```json
{
  "schema_version": 1,
  "spec_path": "spec.md",
  "model_id": "haiku-4-5",
  "milestone_count": 3,
  "band": {"p10_usd": 0.24, "p50_usd": 0.54, "p90_usd": 1.26},
  "tier": "partial",
  "samples_used": 2,
  "calibration_source": "mixed",
  "rolling_error_ratio_mean": 1.02,
  "last_sample_age_days": 0.05,
  "duration_min": [50, 72]
}
```

Schema locked by `tests/test_cli_estimate_banded.py::test_json_schema_snapshot`.

## Telemetry footprint

Two events:

1. **`MilestoneCompleted`** gained a `model_id` field (canonical, e.g.
   `haiku-4-5`). Pre-v1.3.24 events with `model_id=None` are explicitly
   **skipped** by calibration (not pooled into a phantom `unknown`
   bucket) and counted in a log line.

2. **`EstimateCalibrated`** — emitted once per **completed** run:

```python
@dataclass
class EstimateCalibrated(TelemetryEvent):
    model_id: str
    predicted_cost_usd: float
    actual_cost_usd: float
    error_ratio: float            # actual / max(predicted, 0.001)
    samples_used: int
    calibration_source: str       # cold_start | partial | warm
```

`error_ratio` close to 1.0 means the estimator was on-target.
Failed/cancelled runs do NOT emit (`status="complete"` gate).

## Math

Both `drift.py` and `calibration.py` compute baselines in **log1p
space** (`expm1(ewma(log1p(samples)))`) for heavy-tailed cost
distributions. The shared `_stats.py` module owns the math so a future
fix to the log-space semantics propagates to both. Cross-module
consistency is asserted by
`tests/test_model_key.py::test_drift_and_calibration_use_identical_keys`.

For 1 ≤ n < 20 the bands are widened by `small_n_widen` (asymptotes
to identity at n=20) to reflect the higher uncertainty at low sample
counts.

## Kill switches

| Lever | Effect |
|---|---|
| `SW_CALIBRATION_DISABLE=1` env var | skips banded path AND `EstimateCalibrated` emission |
| `sw estimate --legacy` flag | per-invocation fallback to v1.3.23 |
| `SW_CALIBRATION_MAX_EVENTS=N` env var | caps streaming read (default 10000) |

## DEFAULT_TABLE

Per-milestone p10/p50/p90 used at cold-start and as blend partner
under partial-tier:

```python
DEFAULT_TABLE = {
    "haiku-4-5":  (0.08, 0.18, 0.42),   # derived from v1.3.21-e2e soak
    "sonnet-4-5": (0.35, 0.85, 2.10),   # placeholder until soaked
    "opus-4-7":   (1.20, 2.80, 6.50),   # placeholder until soaked
    "unknown":    (0.15, 0.50, 1.80),
}
```

The haiku-4-5 entry is the one calibrated from real soak data. The
others are seed values; they'll be replaced organically as projects
accumulate telemetry under those models.

## Adding a new model

1. Add a row to `DEFAULT_TABLE` in `calibration.py`. Best practice:
   p50 = an honest guess; p10 = p50 / 2; p90 = p50 × 2.5.
2. Add the alias to `_CANONICAL` in `_model_key.py` if needed.
3. After 5 same-model runs on a real project, the warm tier kicks in
   and the table values stop mattering.

## Distinct from neighboring features

| Feature | Asks |
|---|---|
| Drift Detector (v1.3.19) | Is this run abnormal vs baseline? |
| Cost Ceilings (v1.3.20) | Did we exceed a rolling-window budget envelope? |
| Failure Triage (v1.3.21) | Why did this milestone fail? |
| **Calibration Loop (v1.3.24)** | **What will the NEXT run cost on this model?** |

All four read the same `sw-telemetry.jsonl`. None mutate each other.
