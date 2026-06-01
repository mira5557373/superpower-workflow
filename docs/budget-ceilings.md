# Rolling Cost Ceilings (v1.3.20)

A cross-run cost accountant that enforces optional rolling-window
ceilings on the project's accumulated LLM spend. Catches the
"overnight retry loop drained the budget" failure mode that per-run
budgets and `BudgetAlert` cannot see.

## What problem this solves

Pre-v1.3.20, `sw` had two cost-control mechanisms — both within-run:

| Mechanism | Scope | When it fires |
|---|---|---|
| `max_total_budget_usd` | one run | when state.total_cost_usd exceeds the cap during the run |
| `BudgetAlert` (v1.3.17) | one run | at 50% / 75% / 90% / 100% of `max_total_budget_usd` |

Neither can see *across runs*. A cron-driven `sw run` invocation, or
a chain of best-of-n branches, or a PhaseE retry storm that lands
back inside per-run budget can still drain the team's monthly LLM
budget overnight.

`cost_ceilings` adds three optional rolling windows:

| Window | Duration | Config key | Aggregation |
|---|---|---|---|
| day | 24h ending now-UTC | `cost_ceilings.daily` | sum of `RunCompleted.total_cost_usd` |
| week | 7d ending now-UTC | `cost_ceilings.weekly` | same |
| month | 30d ending now-UTC | `cost_ceilings.monthly` | same |

Each window has an absolute USD ceiling and a mode (`warn` or
`block`). Each is independent — set one, two, or all three.

## Quickstart

```bash
# Set a daily ceiling of $50 that hard-blocks new runs:
sw budget set --daily 50 --mode block

# Inspect spend + headroom:
sw budget show
#   Cost ceilings (project=myrepo, telemetry=sw-telemetry.jsonl)
#   --------------------------------------------------------------------------
#   window mode      spend /    ceiling     headroom  runs
#   day    block  $   12.34 / $    50.00   $    37.66     3

# JSON form for dashboards:
sw budget show --json | jq .

# Reset a window after an incident or deliberate budget shift:
sw budget reset --window day --confirm
```

## Configuration

In `.claude/workflow.json`:

```json
{
  "cost_ceilings": {
    "daily":   { "usd": 50,  "mode": "block" },
    "weekly":  { "usd": 200, "mode": "block" },
    "monthly": { "usd": 600, "mode": "warn"  }
  }
}
```

Shorthand: a bare number defaults to `mode="block"`:

```json
{ "cost_ceilings": { "daily": 50 } }
```

Zero or negative values are silently ignored.

## Preflight gates

The orchestrator evaluates ceilings at three points per run:

| Gate | When | Projection |
|---|---|---|
| `run_start` | once before any milestone begins | full `estimate()` output or `max_total_budget_usd` fallback |
| `milestone_start` | top of each milestone iteration | `(remaining_budget) / (remaining_milestone_count)` |
| `phase_e_retry` | top of each retry attempt > 0 | per-milestone projection |

Each evaluation emits one `CostCeilingEvaluated` event per configured
window with the gate stamped in `preflight_gate`. A `block` decision
(with no authorized bypass) emits `CostCeilingBlocked` and exits 7.

## `CostCeilingEvaluated` vs `BudgetAlert`

These are independent signals and can fire in the same run:

| Field | `BudgetAlert` | `CostCeilingEvaluated` |
|---|---|---|
| Scope | this run only | rolling window across all recent runs |
| Trigger | percent crossing (50/75/90/100) | absolute USD threshold |
| Cardinality | up to 4 per run (one per threshold) | one per configured window × preflight gate |
| Blocks the run? | no | yes (if mode=block and `current+projected >= ceiling`) |

A long-running, well-budgeted milestone can fire
`BudgetAlert(threshold=75)` (we're 75% through our $20 budget) AND
**not** trip any ceiling (because the rolling 24h spend including this
run still fits under $50). Conversely, a brand-new milestone with a
$2 budget could trip the daily ceiling at run-start because the prior
24h of other runs already used $48.

## Decisions and exit codes

| Decision | Meaning |
|---|---|
| `allow` | under ceiling (or no ceiling configured for this window) |
| `warn` | over ceiling but `mode=warn`; run continues, event logged |
| `block` | over ceiling and `mode=block`; run aborts with exit 7 |
| `no_history` | telemetry missing/empty; defaults to allow |
| `bypass` | over+block but user passed authorized `--ignore-ceiling` |

| Exit code | Meaning |
|---|---|
| 0 | success |
| 7 | blocked by cost ceiling |
| 8 | `--ignore-ceiling` used without authorization |

## Escape hatch: `--ignore-ceiling`

Defense-in-depth: the flag alone is not enough.

```bash
# Authorization paths:
SW_ALLOW_CEILING_BYPASS=1 sw run --ignore-ceiling                # cron-safe
sw run --ignore-ceiling                                          # TTY → asks "Proceed? [y/N]"
sw run --ignore-ceiling                                          # non-TTY no-env → exit 8
```

Bypass is recorded in the audit trail as `CEILING_BYPASS` with the
window, prior spend, projected cost, and `auth_reason` (`env_var_set`
or `tty_confirmed`). The `CostCeilingBlocked` telemetry event is
emitted with `override_used=true`.

## Reset semantics

`sw budget reset --window day --confirm` does NOT delete telemetry. It
writes a `reset_checkpoints.day` ISO timestamp into
`cost_ceilings.reset_checkpoints` in `workflow.json`. Events
completed at or before that timestamp are excluded from the window
sum on subsequent evaluations. A `CEILING_RESET` audit event records
the window + prior spend.

Use this after:
- A deliberate decision to "start fresh" mid-window after an incident.
- A model swap that legitimately changed the per-run cost baseline.
- A test/staging cost burst that shouldn't count toward the prod budget.

## Source field

`CostCeilingEvaluated.source` tells dashboards how to interpret the
spend number:

| Value | Meaning |
|---|---|
| `telemetry` | telemetry has at least one event older than the window start; the window's spend is FULL coverage |
| `partial_history` | events exist but the oldest is newer than the window start; the spend may UNDERSTATE actual rolling spend |
| `no_history` | no usable events; decision is always `allow` |

## Rollback levers

Three layers, increasing destructiveness:

1. **Per-invocation override** — `--ignore-ceiling` with
   `SW_ALLOW_CEILING_BYPASS=1`. Audit-logged. Use for incident response.
2. **Per-project mode flip** — `sw budget set --mode warn` keeps
   evaluations and telemetry but never blocks. Or delete
   `cost_ceilings` from `workflow.json` entirely.
3. **Emergency kill switch** — `SW_DISABLE_COST_CEILINGS=1` short-
   circuits the preflight check at the top of
   `Orchestrator._check_cost_ceilings`. No telemetry emitted, no audit.
   Documented escape valve for incident-response when the ceiling
   logic itself is suspect.

## Performance

The accountant is pure-functional with a single-pass JSONL read per
preflight invocation. A 100k-event telemetry log with 1k events in
the day window evaluates in well under 500ms on Windows CI (see
`tests/test_budget_ceiling.py::TestPerformance`).

A separate file lock `.claude/.ceiling.lock` serializes concurrent
preflight evaluations across racing `sw run` invocations — without
blocking the long-running phases inside each run. Stale locks (older
than 30s) are auto-reclaimed.
