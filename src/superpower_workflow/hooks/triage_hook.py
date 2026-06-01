"""v1.3.21 — orchestrator-side hook for the Failure Triage Classifier.

Best-effort: every call site MUST be wrapped in try/except so a triage
failure never propagates into the milestone loop. The hook reads existing
telemetry/audit/state (no new instrumentation), classifies the anchor
failure, and emits a FailureTriaged event.

The hook is callable from the orchestrator at three anchor points (the
orchestrator wires `on_milestone_failed` for the common MilestoneFailed
case; the others extend naturally as future call sites).

Reader-cache contract (verdict revision #6): the orchestrator owns a
shared TelemetryReader-style object cached for the run's lifetime;
this hook calls into it via the `read_events`/`read_audit` callbacks
rather than hitting disk every failure. For v1 we pass plain Path
arguments and read once per failure — the cache layer is a follow-up
optimization, but the API supports it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from superpower_workflow.failure_triage import (
    ANCHOR_TYPES,
    BundleWindow,
    classify_failure,
    to_event_dict,
)


def on_milestone_failed(
    *,
    anchor: dict[str, Any],
    telemetry_path: Path,
    audit_path: Path | None,
    state_snapshot: dict | None,
    emit: Callable[[dict], None],
    read_events: Callable[[], list[dict]] | None = None,
    read_audit: Callable[[], list[dict]] | None = None,
) -> dict | None:
    """Classify a terminal failure anchor and emit a FailureTriaged event.

    Args:
        anchor: the source telemetry event dict (MilestoneFailed,
            CostCeilingBlocked, etc.). Must have `type`, `run_id`,
            `milestone`, optionally `seq`/`phase`/`reason`.
        telemetry_path: path to sw-telemetry.jsonl for bundle reconstruction.
        audit_path: optional path to audit-trail.jsonl.
        state_snapshot: optional dict of current WorkflowState (for
            rule_13 `current_step` check).
        emit: callable that writes a FailureTriaged event dict (typically
            the orchestrator's TelemetryEmitter.emit closure).
        read_events / read_audit: optional callables that return cached
            event lists; if provided, the hook will use them instead of
            re-reading the JSONL files (verdict revision #6).

    Returns:
        The emitted FailureTriaged dict on success, or None if classification
        was skipped (anchor not an anchor type, etc.). Never raises into the
        caller — the orchestrator's hook call site is `try/except` wrapped.
    """
    if anchor.get("type") not in ANCHOR_TYPES:
        return None

    events = read_events() if read_events is not None else _read_jsonl(telemetry_path)
    if read_audit is not None:
        audit = read_audit()
    else:
        audit = _read_jsonl(audit_path) if audit_path else []

    # Assign synthetic seq if needed.
    for i, ev in enumerate(events):
        ev.setdefault("seq", i)
    for i, a in enumerate(audit):
        a.setdefault("seq", i)
    anchor.setdefault("seq", len(events) - 1)

    run_id = anchor.get("run_id", "")
    milestone = anchor.get("milestone", "")
    anchor_seq = int(anchor.get("seq", 0))

    in_events: list[dict] = []
    for ev in events:
        if int(ev.get("seq", 0)) > anchor_seq:
            continue
        if ev.get("run_id", "") != run_id:
            continue
        ms = ev.get("milestone", "")
        if ms and milestone and ms != milestone:
            blocked = ev.get("blocked_milestone", "")
            if blocked != milestone:
                continue
        in_events.append(ev)

    in_audit: list[dict] = []
    for a in audit:
        if int(a.get("seq", 0)) > anchor_seq:
            continue
        if a.get("run_id", "") != run_id:
            continue
        ms = a.get("milestone", "")
        if ms and milestone and ms != milestone:
            continue
        in_audit.append(a)

    bundle = BundleWindow(
        anchor=anchor,
        events=in_events,
        audit_entries=in_audit,
        state_snapshot=state_snapshot,
    )
    result = classify_failure(anchor, bundle)
    out = to_event_dict(result, run_id=run_id)
    emit(out)
    return out


def _read_jsonl(path: Path | None) -> list[dict]:
    """Tiny duplicated reader so the hook stays decoupled from failure_triage
    internals. Skips bad JSON lines and missing files."""
    import json

    if path is None or not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
