# Migration Guide (v1.x → v1.4.0)

Schema bumps, exit-code additions, and forward/backward-compat guarantees
across the v1.3.x line. All changes through v1.4.0 are **additive** — no
event types removed, no fields removed, no exit codes repurposed.

## Schema bumps

### `MilestoneCompleted.model_id` (v1.3.24)

`MilestoneCompleted` gained a `model_id: str | None = None` field so the
Estimator Calibration Loop can partition samples per canonical model.

| Concern | Resolution |
|---|---|
| Old events | `model_id=None` on every pre-v1.3.24 `MilestoneCompleted` event |
| Calibration behavior | Pre-v1.3.24 events are **SKIPPED** by calibration (not pooled into a phantom `unknown` bucket) and counted in an INFO log line: `calibration: skipped N pre-v1.3.24 sample(s) with no model_id` |
| Read path | `_model_key.extract_model_id` returns `None` silently on missing field — no exception |
| Telemetry consumers | Unknown field on a `MilestoneCompleted` dict is ignored by readers (additive forward-compat) |

**Implication:** if you have a project with significant pre-v1.3.24 history,
calibration will start in `cold_start` tier and reach `partial` / `warm`
only after you accumulate 1+ / 5+ NEW v1.3.24+ samples per model. The
historical events are not retroactively re-stamped.

### `WorkflowState.breaker_window` (v1.3.26)

`WorkflowState` gained `breaker_window: list[dict] = field(default_factory=list)`
to persist the Classed Circuit Breaker's rolling failure window.

| Concern | Resolution |
|---|---|
| Old state files | Missing field defaults to `[]` on load |
| Regression test | `test_pre_v1326_state_loads_with_empty_breaker_window` loads a hand-crafted pre-v1.3.26 state fixture and asserts no raise + empty window |
| Round-trip | `test_v1326_state_roundtrip_preserves_window` confirms save/load preserves entries |
| Missing file | `load_state` returns a fresh `WorkflowState()` with empty window |

**Implication:** projects upgrading from <v1.3.26 will see the breaker
start with an empty window. This is correct — historical failures from
prior runs are NOT replayed into the new window. Use
`sw triage --reclassify` if you want to see what the historical failures
would have classified as under current rules.

### `PhaseCompleted` token fields (pre-v1.3.x)

Token-related fields on `PhaseCompleted` (`input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `cache_hit_rate`)
were added in earlier v1.3.x releases. All consumers tolerate missing
fields with zero defaults.

## Telemetry event additions

No event types have been removed. Per release:

| Release | New event types |
|---|---|
| v1.3.17 | `RunCostProjection`, `BudgetAlert` |
| v1.3.19 | `DriftDetected` |
| v1.3.20 | `CostCeilingEvaluated`, `CostCeilingBlocked` |
| v1.3.21 | `ClaudeInvocationFailed` (emitted by orchestrator on `_PhaseError`), `FailureTriaged` |
| v1.3.24 | `EstimateCalibrated` |
| v1.3.26 | `CircuitBreakerTripped`, `CircuitBreakerWouldTrip`, `CircuitBreakerReset` |

`TelemetryReader` and `TelemetryDbWriter` treat unknown event `type` values
as opaque — they record them but don't try to interpret. Dashboard
consumers do the same. **No forward-incompat reads.**

## Audit-trail event additions

No audit entries have been removed. New `event` values emitted by
`AuditTrail.append`:

| Release | New audit `event` values |
|---|---|
| v1.3.20 | `CEILING_BLOCK`, `CEILING_BYPASS`, `CEILING_RESET` |
| v1.3.26 | `CIRCUIT_BREAKER_RESET` (emitted by `sw breaker reset --confirm` in v1.3.27+) |

The hash chain validates regardless of which events appear. `sw audit
verify` walks the chain by `prev_hash` reference, not by event type.

## Exit code additions

All additive; pre-existing codes (`0`, `1`, `2`, `3`) unchanged.

| Code | Meaning | Added |
|---|---|---|
| 7 | Cost ceiling blocked the run (block mode) | v1.3.20 |
| 8 | `--ignore-ceiling` used without authorization | v1.3.20 |
| 10 | Circuit breaker tripped in enforced mode | v1.3.26 |

`sw run --ignore-ceiling` requires `SW_ALLOW_CEILING_BYPASS=1` env var OR
interactive TTY confirmation. Bare flag in non-TTY no-env shell → exit 8.
Code 10 is only reachable when `circuit_breaker.observation_only=false` (the
default is `true`, so 10 is unreachable until you flip the config).

## Model canonicalization (v1.3.24)

`_model_key.canonicalize` strips the `claude-` prefix and lowercases.
Aliases are accepted in config and canonicalized at read; telemetry always
records the canonical form.

| Config string | Canonical |
|---|---|
| `claude-haiku-4-5` | `haiku-4-5` |
| `claude-sonnet-4-5` | `sonnet-4-5` |
| `claude-opus-4-7` | `opus-4-7` |
| `haiku` (legacy alias) | `haiku-4-5` |
| `sonnet` | `sonnet-4-5` |
| `opus` | `opus-4-7` |
| unknown / new model | lowercased as-is |

Drift Detector and Calibration Loop both bucket by canonical id. Mixed-case
or claude-prefixed strings in old logs are normalized on read.

## `DEFAULT_TABLE` recalibration (v1.3.25)

The `calibration.DEFAULT_TABLE` per-model prior used at cold-start was
recalibrated from soak data:

| Model | v1.3.24 prior (p10, p50, p90) | v1.3.25 prior |
|---|---|---|
| `haiku-4-5` | (0.08, 0.18, 0.42) | **(0.50, 1.49, 1.95)** |
| `sonnet-4-5` | (0.35, 0.85, 2.10) | (1.80, 4.50, 12.00) — seed |
| `opus-4-7` | (1.20, 2.80, 6.50) | (6.00, 15.00, 35.00) — seed |
| `unknown` | (0.15, 0.50, 1.80) | (0.50, 1.50, 5.00) |

**Impact:** new cold-start projects on haiku-4-5 see a more realistic prior
(prior bands ~7× higher than v1.3.24's accidentally-per-phase numbers).
Projects with telemetry hit `partial` or `warm` tier quickly and the prior
matters less.

## Configuration forward-compat

`workflow.json` is loaded as a plain dict. Unknown keys are ignored. Adding
new optional blocks (`drift_detection`, `cost_ceilings`, `triage`,
`circuit_breaker`) does not break readers that don't expect them. The only
**required** top-level fields remain:

- `spec`
- `model`
- `budgets.{plan, implement, review, push}`
- `milestones` (after `sw decompose`)

## Kill switches summary

Each telemetry feature has a per-feature env-var kill switch. The circuit
breaker is config-only — flip `circuit_breaker.enabled=false` in
`workflow.json` instead of an env var.

| Variable | Effect | Added |
|---|---|---|
| `SW_DRIFT_DISABLE=1` | skip drift assessment | v1.3.19 |
| `SW_DISABLE_COST_CEILINGS=1` | short-circuit ceiling preflight | v1.3.20 |
| `SW_TRIAGE_OFF=1` | skip triage hook + CLI | v1.3.21 |
| `SW_CALIBRATION_DISABLE=1` | skip calibration emit + render | v1.3.24 |
| `SW_ALLOW_CEILING_BYPASS=1` | authorize `--ignore-ceiling` flag | v1.3.20 |
| `SW_AUDIT_KEY` | HMAC key for audit chain (required if `security.audit_trail=true`) | pre-v1.3.x |
| `SW_DATABASE_URL` | optional Postgres for server-mode telemetry | pre-v1.3.x |

## General forward/backward-compat principles

1. **Telemetry events are additive only.** No removed types, no removed
   fields, no renames. Consumers tolerate unknown event types as opaque.
2. **State schema bumps include default values for backward-compat reads.**
   New fields land with `field(default_factory=...)` so loading older state
   files never raises.
3. **`workflow.json` is forward-compat.** Unknown config blocks are ignored.
4. **Exit codes are additive.** Pre-existing codes are never repurposed.
5. **Audit events extend the catalog.** Old audit consumers see new entries
   and pass them through; hash chain validation does not depend on event
   type.
6. **`sw clean` does NOT delete `audit-trail.jsonl`.** Audit history
   survives state resets by design.

## Upgrading

For an upgrade from any v1.3.x to v1.4.0:

```bash
cd path/to/superpower-workflow
git pull origin master
git checkout v1.4.0
pip install -e .
# In your project:
sw doctor          # verifies install + locates claude
sw status          # confirms state loads cleanly
```

No state migration step is required. The first `sw run` under v1.4.0 will
start emitting the new event types and reading old logs forward-compat.

If you have project-specific `workflow.json` customizations (custom
`circuit_breaker.same_class_thresholds`, custom `verify_commands`), those
are preserved — only the framework code updates.

For pre-v1.3.x to v1.4.0, the changes are extensive but still additive. You
will see:
- Calibration starting from `cold_start` tier (pre-v1.3.24 events have no `model_id`)
- Breaker window empty on first load (defaulted)
- New telemetry events appearing alongside existing ones

Nothing in the upgrade path requires hand-editing existing files.
