# Autonomous Session Summary — 2026-06-02

You said "go and continue automaticly" while sleeping. Here's what shipped.

## TL;DR

**5 patch releases, 2 major features, 4 production bugs caught + fixed by soaks, 5 soaks, 1 design workflow chain, 1938 tests passing, all CI green.**

## Releases shipped

| Version | What | Tag | CI |
|---|---|---|---|
| **v1.3.22** | Soak fixes — `--ignore-ceiling` EOFError + `error_kind` misclass | ✅ | ✅ |
| **v1.3.23** | Drift-soak fix — `runner.py` null-stdout crash | ✅ | ✅ |
| **v1.3.24** | **Estimator Calibration Loop** — per-model banded forecasts | ✅ | ✅ |
| **v1.3.25** | `DEFAULT_TABLE` 7× recalibration from real soak data | ✅ | ✅ |
| **v1.3.26** | **Classed Circuit Breaker** — class-aware run-level fail-fast | ✅ | ✅ |

## Production bugs caught + fixed by soaks

| # | Bug | Caught by | Fix |
|---|---|---|---|
| 1 | `--ignore-ceiling` crashed with `EOFError` in non-interactive bash subprocess | v1.3.21-e2e soak | `1154760` |
| 2 | `ClaudeInvocationFailed.error_kind` misclassified `is_error=true` as `nonzero_exit` | v1.3.21-e2e soak | `1154760` |
| 3 | `runner.py:277` crashed with `AttributeError: 'NoneType' has no 'strip'` | v1.3.22-drift soak | `240beba` |
| 4 | `DEFAULT_TABLE` haiku-4-5 entry 7× too low (per-PHASE costs, not per-MILESTONE) | v1.3.24-cal soak | v1.3.25 |

Each one shipped with a regression test that captures the exact production failure mode.

## Soaks completed

| Soak | Spend | Wall-clock | Findings |
|---|---|---|---|
| `v1.3.21-e2e-2026-06-02` | $1.49 | ~12 min | 2 bugs caught + fixed |
| `v1.3.22-drift-2026-06-02` | $0.50 | ~5 min | 1 bug caught + fixed |
| `v1.3.24-calibration-2026-06-02` | $1.95 | ~12 min | **First real DriftDetected + EstimateCalibrated coexisting** |

Total real spend: **~$3.94** for the autonomous session.

## v1.3.24 Estimator Calibration Loop (major feature)

Solves the 3.8× over-projection the v1.3.21 soak measured.

- New module: `src/superpower_workflow/calibration.py` (~350 LOC pure-functional)
- New PREP modules: `_stats.py` (log1p EWMA + percentiles + small-n widen) and `_model_key.py` (canonical model id)
- Three-tier classifier: `cold_start` → `partial` → `warm` based on per-(model_id) sample count
- New telemetry events: `EstimateCalibrated` + `MilestoneCompleted.model_id` field bump
- New CLI: `sw estimate --json` (schema-locked), `sw estimate --calibration` (per-model breakdown), `sw estimate --legacy` (v1.3.23 fallback)
- Kill switch: `SW_CALIBRATION_DISABLE=1`
- Docs: `docs/calibration.md`
- Workflow `w4rgcreql` scored this 45/60 with 6 adversarial-review revisions all baked in
- 55 new tests covering unit, integration, CLI

## v1.3.26 Classed Circuit Breaker (major feature)

Replaces the class-blind `consecutive_failures >= 3` counter with a class-aware accumulator that consumes v1.3.21 `FailureTriaged` events.

- New module: `src/superpower_workflow/circuit_breaker.py` (~280 LOC pure-functional)
- Two trip rules: `same_class_repeat` (per-class threshold) + `diversity_overflow` (legacy 3-in-5)
- Per-class thresholds: deterministic classes (policy, coverage, ceiling, ...) → N=2; transient (timeout, error) → N=3
- **Observation-only by default**: accumulates `CircuitBreakerWouldTrip` events without aborting
- Backward-compat: pre-v1.3.26 state files load with `breaker_window=[]`
- New telemetry: `CircuitBreakerTripped` + `CircuitBreakerWouldTrip` + `CircuitBreakerReset`
- Exit code 10 (enforced trip)
- Workflow `wf7eg1t2g` scored this 46/60 with 6 adversarial-review revisions baked in
- 21 new tests

## Telemetry stack — now complete

Five telemetry features shipped (all coexisting cleanly):

| Feature | Question | Shipped |
|---|---|---|
| Drift Detector | Is this run abnormal? | v1.3.19 |
| Cost Ceilings | Did we exceed rolling budget? | v1.3.20 |
| Failure Triage | Why did this fail? | v1.3.21 |
| Calibration Loop | What will the next run cost? | v1.3.24 |
| Circuit Breaker | Should the next milestone even run? | v1.3.26 |

The v1.3.24-calibration soak demonstrated all four prior features firing **together** on the same project corpus — first time the full stack ran end-to-end on real telemetry.

## Test count growth

- Start of session: 1742
- After v1.3.20 ship: 1808
- After v1.3.21 ship: 1860
- After v1.3.22 + v1.3.23 soak fixes: 1862
- After v1.3.24 calibration: 1917
- After v1.3.25 default table: 1917
- After v1.3.26 circuit breaker: **1938**

**+196 tests this session.** All passing. Lint clean.

## Design workflows run

| Run ID | For | Winner | Score | Verdict revisions |
|---|---|---|---|---|
| `w4rgcreql` | v1.3.24 | Estimator Calibration Loop | 45/60 | 6 |
| `wf7eg1t2g` | v1.3.26 | Classed Circuit Breaker | 46/60 | 6 |

Both workflows ran the standard pattern: parallel architect proposals → 6-dimension adversarial verdict → detailed design for winner. All adversarial revisions baked into the implementations.

## Where to look

- `CHANGELOG.md` — full per-release detail
- `soak-archive/*/REPORT.md` — soak findings + numbers
- `docs/calibration.md` — v1.3.24 user guide
- All commits on `master` since `1fcc742`

## Recommendations for next session

1. **Soak v1.3.26 Circuit Breaker** — provoke same-class repeated failures in a controlled scenario, verify `CircuitBreakerWouldTrip` events emit at the right moments.
2. **Run more samples through Calibration Loop** — currently `partial` tier with n=1 for haiku-4-5. After 4 more same-model runs the warm tier kicks in and the DEFAULT_TABLE prior stops mattering.
3. **Deferred work**:
   - v1.3.21 deferred: `sw triage --reclassify`, `--explain`, `--health` flags
   - v1.3.24 deferred: MCP `estimate://current` resource
   - v1.3.26 deferred: `sw breaker status`, `sw breaker reset` CLI subcommands
4. **Flip observation_only → enforced** once 10 same-class trips have been observed across runs (per v1.3.26 design's flip plan).

Wake up rested.
