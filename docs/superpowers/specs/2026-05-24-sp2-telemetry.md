# SP2: Telemetry & Analytics — Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Approved for implementation planning
**Roadmap:** SP2 of 7 -> v0.3.0
**Goal:** Structured telemetry that tracks cost, quality, and trends across runs — feeding data to SP3 dashboard and enabling data-driven workflow optimization.

> Depends on SP1 (quality gate pass/fail events feed into telemetry).

---

## 1. Overview

Four capabilities that turn opaque `sw run` sessions into measurable, auditable data:

1. **Structured telemetry writer** -- append-only JSONL to `.claude/telemetry.jsonl`
2. **Quality trend tracking** -- test count, gap count, coverage, cost across runs
3. **Rework rate metric** -- Phase C fixes divided by Phase B lines changed
4. **Analytics CLI** -- `sw analytics` displays trends from telemetry data

**Architecture:** The orchestrator emits events at phase boundaries and quality gate checkpoints. A `TelemetryWriter` appends each event as a single JSON line. A `TelemetryReader` loads historical data and computes aggregate metrics. SP3 consumes the reader API for live and historical display.

---

## 2. Telemetry Format

One JSON object per line. Every event shares a common envelope:

```json
{
  "timestamp": "2026-05-24T14:30:00Z",
  "run_id": "abc123",
  "milestone": "milestone-03-auth",
  "phase": "B",
  "event_type": "PHASE_COMPLETE",
  "data": {}
}
```

### Event Types

| event_type | data fields |
|---|---|
| `PHASE_COMPLETE` | `cost`, `duration_s`, `test_count`, `gap_count`, `tokens_in`, `tokens_out` |
| `QUALITY_GATE` | `gate_name`, `passed`, `details` (truncated to 500 chars) |
| `COVERAGE` | `percent`, `threshold`, `attempt`, `passed` |
| `MILESTONE_COMPLETE` | `total_cost`, `total_duration_s`, `tests_added`, `phases_completed` |
| `REWORK` | `phase_b_lines`, `phase_c_lines`, `rework_rate` |
| `ERROR` | `error_type`, `message`, `phase`, `recoverable` |

---

## 3. Configuration

New optional `telemetry` section in workflow.json:

```json
{
  "telemetry": {
    "enabled": true,
    "path": ".claude/telemetry.jsonl",
    "include_token_counts": true,
    "max_file_size_mb": 50
  }
}
```

All fields optional. Missing section = telemetry enabled with defaults. Telemetry is on by default because it is local-only and append-only.

---

## 4. Components

### TelemetryWriter

- `emit(event_type, milestone, phase, data)` -- append one JSONL line
- `close()` -- flush and close at run end
- Writes use append mode (`"a"`) -- no atomic replace needed
- File rotation: if file exceeds `max_file_size_mb`, rename to `.jsonl.1` and start fresh

### TelemetryReader

- `events(run_id?, event_type?)` -- filter events by run_id and/or type
- `trend(metric, window=10)` -- last N values of a metric across milestones
- `rework_rate(run_id?)` -- Phase C lines / Phase B lines (0.0 = no rework)
- `cost_per_milestone(window=10)` -- cost of last N milestones
- `defect_density(window=10)` -- quality gate failures per milestone

### Rework Rate

After Phase B, capture `git diff --stat` line count. After Phase C, capture the same. Rate = phase_c_lines / phase_b_lines. Emitted as `REWORK` event at milestone end.

---

## 5. Orchestrator Integration

Orchestrator creates `TelemetryWriter` at run start, closes at run end. Emit points:

1. After each phase -- `PHASE_COMPLETE` with cost/duration from runner response
2. After each quality gate -- `QUALITY_GATE` with pass/fail and details
3. After coverage check -- `COVERAGE` with percent and attempt number
4. After milestone push -- `MILESTONE_COMPLETE` with totals
5. On error -- `ERROR` with type and recoverability

---

## 6. CLI: `sw analytics`

```
$ sw analytics
Telemetry: .claude/telemetry.jsonl (47 events, 5 milestones)

Cost per milestone (last 5):  $12.40  $8.90  $11.20  $9.50  $10.10
Coverage trend:                82%     85%    87%     89%    91%
Gap count trend:               8       5      3       2      1
Rework rate:                   0.12    0.08   0.05    0.03   0.02
Defect density:                0.4     0.2    0.2     0.0    0.0

Total cost: $52.10 across 5 milestones
Avg cost/milestone: $10.42
```

Flags: `--json` for machine-readable output, `--window N` for trend window size.

---

## 7. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/telemetry.py` | **Create.** TelemetryWriter, TelemetryReader, event schema, trend computation |
| `src/superpower_workflow/orchestrator.py` | **Modify.** Emit telemetry events after phases, gates, coverage, milestone end |
| `src/superpower_workflow/cli.py` | **Modify.** Add `sw analytics` command with `--json` and `--window` flags |
| `tests/test_telemetry.py` | **Create.** Writer round-trip, reader filtering, trend calculation, rework rate, rotation |
| `tests/test_orchestrator.py` | **Modify.** Verify telemetry events emitted at correct points |

---

## 8. Appendix

### Data API for SP3

SP3 dashboard imports `TelemetryReader` directly. The SSE endpoint tails the JSONL file and pushes new lines as they appear. No separate server process needed -- the reader handles file seeking.

### Privacy

Telemetry is local-only (`.claude/` directory). No data leaves the machine. The file is gitignored by default (`.claude/` is in `.gitignore`).

### Backward Compatibility

Runs without SP1 quality gates still emit `PHASE_COMPLETE` and `MILESTONE_COMPLETE` events. Quality gate events are only emitted when gates are configured.
