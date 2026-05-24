# SP3: Dashboard — Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Approved for implementation planning
**Roadmap:** SP3 of 7 -> v0.4.0
**Goal:** Real-time visibility into workflow execution through a web dashboard and terminal TUI -- observe cost, progress, and quality without reading logs.

> Depends on SP2 (reads telemetry JSONL and trend APIs).

---

## 1. Overview

Three presentation layers for workflow observability:

1. **Web dashboard** (`sw dashboard`) -- HTML + JS at localhost:3000, live updates via SSE
2. **Terminal TUI** (`sw watch`) -- rich-based live display with progress bars and cost ticker
3. **Prometheus endpoint** (optional) -- `/metrics` for Grafana integration

**Architecture:** No React, no bundler. A single-file Python HTTP server serves static HTML/JS and an SSE endpoint. SSE tails `.claude/telemetry.jsonl` and pushes events as written. The TUI reads the same file plus `workflow-state.json` for phase status.

---

## 2. Configuration

New optional `dashboard` section in workflow.json:

```json
{
  "dashboard": {
    "port": 3000,
    "host": "127.0.0.1",
    "prometheus": false,
    "refresh_interval_ms": 1000
  }
}
```

All fields optional. Defaults shown above.

---

## 3. Web Dashboard

### Server Routes (`dashboard/server.py`)

| Route | Purpose |
|---|---|
| `GET /` | Serve `index.html` (static dashboard page) |
| `GET /events` | SSE stream -- tails telemetry JSONL, pushes new lines |
| `GET /state` | JSON snapshot of current `workflow-state.json` |
| `GET /metrics` | Prometheus text format (only if `--prometheus` flag) |

SSE opens the telemetry file, seeks to end, polls for new lines every 500ms. Each new JSONL line is sent as an SSE `data:` frame.

### Dashboard UI (`dashboard/templates/index.html`)

Single HTML file with embedded JS (no build step). Five sections: milestone Kanban (pending/running/done), phase progress bar (A/B/QB/C/QC/D), cumulative cost chart (`<canvas>`, no library), test count bars, and live log (last 20 events, auto-scroll). JS connects via `EventSource`; page load fetches `/state` for initial render.

---

## 4. Terminal TUI (`sw watch`)

Uses `rich` library. Layout:

```
+------------------------------------------+
| superpower-workflow  [milestone 3/7]     |
+------------------------------------------+
| Phase:  A [====] B [====] QB [==] C [...] |
| Cost:   $12.40 / $100.00 budget          |
| Tests:  47 (+12 this milestone)          |
+------------------------------------------+
| Recent Events:                           |
| 14:30:01  PHASE_COMPLETE  B  $4.20       |
| 14:30:05  QUALITY_GATE    lint  PASSED   |
+------------------------------------------+
```

```python
class WorkflowTUI:
    def __init__(self, state_path: Path, telemetry_path: Path): ...
    def run(self) -> None:
        """Block and render live display until Ctrl-C."""
```

Polls `workflow-state.json` every second. Tails telemetry for events. Uses `rich.live.Live` for flicker-free updates.

---

## 5. Prometheus Endpoint

When `--prometheus` flag is set, `/metrics` returns text format with gauges: `sw_milestones_total`, `sw_cost_dollars_total`, `sw_test_count`, `sw_coverage_percent`, `sw_rework_rate`. Metrics computed from `TelemetryReader` on each scrape (no in-memory accumulator).

---

## 6. CLI Commands

### `sw dashboard`

```
$ sw dashboard [--port 3000] [--prometheus] [--open]
Dashboard running at http://127.0.0.1:3000
```

Starts HTTP server in foreground. `--open` opens browser.

### `sw watch`

```
$ sw watch
```

Starts terminal TUI. Exits on Ctrl-C.

---

## 7. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/dashboard/__init__.py` | **Create.** Package init |
| `src/superpower_workflow/dashboard/server.py` | **Create.** HTTP server, SSE, state, Prometheus endpoints |
| `src/superpower_workflow/dashboard/templates/index.html` | **Create.** Single-file dashboard with embedded JS |
| `src/superpower_workflow/tui.py` | **Create.** WorkflowTUI class using rich library |
| `src/superpower_workflow/cli.py` | **Modify.** Add `sw dashboard` and `sw watch` commands |
| `pyproject.toml` | **Modify.** Add optional dependency: `rich` |
| `tests/test_dashboard.py` | **Create.** Server route tests, SSE format, state endpoint |
| `tests/test_tui.py` | **Create.** TUI rendering tests (mock rich output) |

---

## 8. Appendix

### Why No React

Developer tool for local use. Single HTML file is easier to maintain, zero build dependencies, ships inside the Python package.

### SSE vs WebSocket

SSE is simpler (unidirectional, auto-reconnect via EventSource API) and sufficient since the dashboard only needs server-to-client push.

### Dependency: rich

Optional dependency (`pip install superpower-workflow[tui]`). `sw watch` checks for rich at import time and prints install instructions if missing.
