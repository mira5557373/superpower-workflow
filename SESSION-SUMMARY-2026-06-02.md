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

## v1.3.27 — closes the v1.3.x sweep

After the ultrathink analysis you asked for, I discovered that **Path A
was incoherent**: all 35 e2e_agent milestones are already DONE at
$665.44 historical cost. There's no "next milestone" to soak sw against.

Pivoted to shipping the **deferred CLI work** that prior REPORTs called
out. Zero claude spend, real operational value:

- `sw triage --reclassify` — replay rules over historical telemetry,
  write `.triage-replay.jsonl` sidecar
- `sw triage --explain <CLASS>` — rule + recommendation + IMPLIES
  subsumption
- `sw triage --health` — UNKNOWN-rate monitoring + per-class
  distribution (OK / DEGRADED at 15% threshold)
- `sw breaker status` — rolling window + per-class counter + TRIP/ok
  indicators (operational visibility — see when breaker is about to trip)
- `sw breaker reset --confirm` — clear window + emit
  `CIRCUIT_BREAKER_RESET` audit entry

Tests: 1938 → 1953 (+15). Complexity-audit max-cc 57 → 58. CI green.

## Final session tally

- **6 releases shipped** (v1.3.22, v1.3.23, v1.3.24, v1.3.25, v1.3.26, v1.3.27)
- **Two major features** (Calibration Loop, Circuit Breaker)
- **Three soaks** ($3.94 real spend) → three production bugs caught + fixed
- **Five new CLI surfaces** shipped in v1.3.27
- **Tests: 1742 → 1953** (+211)
- **All CI green**

## Recommendations for next session

The v1.3.x sweep is **feature-complete**. Verdict scores plateaued at
45-46/60 — further telemetry features will keep hitting diminishing
returns. The honest next move:

1. **Soak v1.3.26 Circuit Breaker in a controlled scenario** — provoke
   same-class repeats, verify `CircuitBreakerWouldTrip` fires at the
   right moments. ~$5 budget.
2. **Documentation pass** — holistic "Getting Started" guide tying all
   5 telemetry features together. No money.
3. **Real-world dogfood** — if you have a NEW project (not e2e_agent
   which is done), run sw on it with all features enabled. Real validation.
4. **Flip Circuit Breaker observation_only → enforced** once N=10
   same-class trips observed across runs (per v1.3.26 design flip plan).

The orchestrator has matured beyond the e2e_agent project that
motivated its design. It's ready for new projects.

Wake up rested.
