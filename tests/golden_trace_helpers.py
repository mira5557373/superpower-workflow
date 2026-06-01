"""Golden-trace parity oracle for the v1.2.0-real Phase A/B/C/D/E refactor.

The refactor extracts ~657 lines from Orchestrator._run_milestone into
PhaseA/PhaseB/PhaseTbV/PhaseC/PhaseD/PhaseE classes. The plan
(docs/superpowers/plans/2026-06-01-v120-real-phase-refactor.md) demands a
parity oracle that catches:

- event ordering regressions (e.g., PhaseCompleted emitted before GapReport)
- token-extraction regressions (cache_* fields lost, cache_hit_rate denom drift)
- cost-accumulation granularity regressions (v1.3.12 in-flight gate weakens
  if _accumulate_cost moves from ~15 in-milestone sites down to 5 per-phase)
- state-transition order regressions (v1.3.4 #15 retry safety)
- v1.3.14 cache_* DB persistence regressions (SwPhase row roundtrip)

Adversarial review of the initial design flagged 10 blind spots; this
module is structured around the resolutions:

1. **Universal telemetry sink** — subscribes to ALL events, not a manual
   append list. Captures typed QualityGateResult etc.
2. **_accumulate_cost recorder** — wraps Orchestrator._accumulate_cost so
   the trace records (delta, resulting_total) per call. Granularity
   regressions are visible directly.
3. **save_state recorder** — wraps state.save_state so the trace records
   (path_basename, current_step, total_cost_usd) per call. State
   transition order is locked.
4. **Subprocess dispatcher** — monkeypatches subprocess.run with a
   cmd-prefix dispatcher: git rev-parse → deterministic SHA, git tag →
   rc=0, gate commands → rc=0 on happy fixture, rc=1 on fix-loop fixture.
5. **run_claude stub with per-call token variation** — different envelope
   per call_index so multi-call token-mis-aggregation regressions surface.

The recorder is a reusable test helper. Callers wire it up via
install_recorders(orch, recorder), then call whatever orchestrator entry
point they want to exercise; the recorder collects records in arrival order.

Update mode: if a deliberate behavior change SHOULD overwrite the
fixture, set GOLDEN_TRACE_UPDATE=1 AND GOLDEN_TRACE_RATIONALE="<reason>".
Both env vars are required — protects against accidental fixture-blessing
when a developer's local refactor has introduced a regression.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Token shape variations indexed by claude-call sequence. Designed so that
# any regression that caches the first envelope's tokens across all calls
# (or mis-aggregates them) produces a different cache_hit_rate per phase.
TOKEN_SHAPES: tuple[dict[str, int], ...] = (
    # Call 0 (Phase A primary)
    {
        "input_tokens": 50,
        "output_tokens": 200,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 400,
    },
    # Call 1 (Phase A curator)
    {
        "input_tokens": 30,
        "output_tokens": 80,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 200,
    },
    # Call 2 (Phase B primary)
    {
        "input_tokens": 80,
        "output_tokens": 400,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 800,
    },
    # Call 3 (Phase B QG fix-loop)
    {
        "input_tokens": 20,
        "output_tokens": 60,
        "cache_creation_input_tokens": 40,
        "cache_read_input_tokens": 160,
    },
    # Call 4 (Phase TbV spec_compliance)
    {
        "input_tokens": 40,
        "output_tokens": 150,
        "cache_creation_input_tokens": 80,
        "cache_read_input_tokens": 300,
    },
    # Call 5 (Phase TbV feature_verification)
    {
        "input_tokens": 45,
        "output_tokens": 160,
        "cache_creation_input_tokens": 85,
        "cache_read_input_tokens": 320,
    },
    # Call 6 (Phase TbV curator)
    {
        "input_tokens": 25,
        "output_tokens": 70,
        "cache_creation_input_tokens": 45,
        "cache_read_input_tokens": 180,
    },
    # Call 7 (Phase C primary)
    {
        "input_tokens": 60,
        "output_tokens": 250,
        "cache_creation_input_tokens": 120,
        "cache_read_input_tokens": 480,
    },
    # Call 8 (Phase C strict iteration)
    {
        "input_tokens": 35,
        "output_tokens": 120,
        "cache_creation_input_tokens": 70,
        "cache_read_input_tokens": 280,
    },
    # Call 9 (Phase D push)
    {
        "input_tokens": 15,
        "output_tokens": 40,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 120,
    },
    # Call 10+ (Phase E ci_fix retries — repeats from index 10 onward)
    {
        "input_tokens": 25,
        "output_tokens": 90,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 200,
    },
)

# Per-call cost in USD. Mirrors realistic phase budgeting in cents.
CALL_COSTS: tuple[float, ...] = (
    1.00,  # 0: Phase A primary
    0.20,  # 1: Phase A curator
    2.50,  # 2: Phase B primary
    0.50,  # 3: Phase B fix-loop
    0.75,  # 4: TbV spec_compliance
    0.75,  # 5: TbV feature_verification
    0.30,  # 6: TbV curator
    1.50,  # 7: Phase C primary
    0.40,  # 8: Phase C strict iteration
    0.10,  # 9: Phase D push
    0.05,  # 10+: Phase E ci_fix retry
)

DETERMINISTIC_SHA = "0123456789abcdef0123456789abcdef01234567"


@dataclass
class TraceRecord:
    """One arrival-ordered observation captured during a recorded run."""

    call_index: int
    kind: str  # 'event' | 'accumulate_cost' | 'save_state' | 'subprocess' | 'run_claude'
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRecorder:
    """Collects TraceRecords in arrival order.

    Threadsafe — uses a Lock so multiple threads (e.g., parallel mode
    workers in a future Task 1 expansion) record without interleaving
    payloads.
    """

    records: list[TraceRecord] = field(default_factory=list)
    _counter: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _next_index(self) -> int:
        with self._lock:
            i = self._counter
            self._counter += 1
            return i

    def record(self, kind: str, **payload: Any) -> None:
        idx = self._next_index()
        with self._lock:
            self.records.append(TraceRecord(call_index=idx, kind=kind, payload=payload))

    # ---- arrival-ordered views ----

    @property
    def events(self) -> list[TraceRecord]:
        return [r for r in self.records if r.kind == "event"]

    @property
    def event_types(self) -> list[str]:
        return [r.payload.get("event_type", "") for r in self.events]

    @property
    def accumulate_cost_calls(self) -> list[TraceRecord]:
        return [r for r in self.records if r.kind == "accumulate_cost"]

    @property
    def save_state_calls(self) -> list[TraceRecord]:
        return [r for r in self.records if r.kind == "save_state"]

    @property
    def subprocess_calls(self) -> list[TraceRecord]:
        return [r for r in self.records if r.kind == "subprocess"]

    @property
    def run_claude_calls(self) -> list[TraceRecord]:
        return [r for r in self.records if r.kind == "run_claude"]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the trace to a JSON-safe dict suitable for a fixture."""
        return {
            "records": [
                {"call_index": r.call_index, "kind": r.kind, "payload": _json_safe(r.payload)}
                for r in self.records
            ],
        }


def _json_safe(obj: Any) -> Any:
    """Coerce common non-JSON types (Path, set) so json.dumps doesn't choke."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, set):
        return sorted(_json_safe(v) for v in obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


# Stable per-event-type key field extraction. Ensures the trace records
# the semantically-load-bearing fields and ignores irrelevant ones
# (timestamps, monotonic seqs, etc).
_EVENT_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "phase_started": ("milestone", "phase"),
    "phase_completed": (
        "milestone",
        "phase",
        "cost_usd",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cache_hit_rate",
    ),
    "milestone_started": ("milestone", "index"),
    "milestone_completed": ("milestone", "status", "cost_usd"),
    "quality_gate_result": ("checkpoint", "gate_name", "passed"),
    "gap_report": ("milestone", "phase"),
    "gap_validation_event": ("milestone",),
    "spec_compliance_completed": ("milestone",),
    "feature_verification_completed": ("milestone",),
    "strict_mode_iteration": ("milestone", "iteration", "residual_count"),
    "run_started": ("model", "milestone_count"),
    "run_completed": ("status", "total_cost_usd"),
}


def _key_fields_for(event_type: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    keys = _EVENT_KEY_FIELDS.get(event_type, ())
    return {k: event_dict.get(k) for k in keys}


def make_telemetry_subscriber(recorder: TraceRecorder) -> Callable[..., None]:
    """Return a function suitable for monkeypatching TelemetryEmitter.emit.

    The wrapper records the event's TYPE + key fields. It also still
    delegates to the original emit so downstream consumers (JSONL writer,
    db writer) still see the event — important for the SwPhase DB
    roundtrip assertion the fixture will make.
    """

    def subscriber(emit_orig: Callable, event: Any) -> None:
        event_dict = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        event_type = event_dict.get("type", "")
        recorder.record(
            "event",
            event_type=event_type,
            fields=_key_fields_for(event_type, event_dict),
        )
        emit_orig(event)

    return subscriber


def make_accumulate_cost_wrapper(
    recorder: TraceRecorder,
    original: Callable[..., float],
) -> Callable[..., float]:
    """Wrap Orchestrator._accumulate_cost to record (delta, resulting_total).

    The resulting total is read from the orchestrator instance AFTER the
    original call returns, so the trace reflects the post-call state.
    """

    def wrapped(self_orch, local_cost: float, delta: float) -> float:
        new_local = original(self_orch, local_cost, delta)
        # NOTE: `new_local` (the return value) is NOT recorded.
        # The original `_run_milestone` threaded a `cost` variable through
        # every `_accumulate_cost` call so the return was the milestone
        # running total. The v1.2.0-real refactor has each phase class
        # call `_accumulate_cost(0.0, delta)` since the return is unused
        # (driver tracks running total in ctx.accumulated_cost via
        # pure-local arithmetic). The state side effect (`delta` charged,
        # `new_state_total` updated) is identical; only the local
        # accumulator return value differs. Locking `new_local` in the
        # fixture would create a false-positive failure on a refactor
        # that legitimately changed the local-accumulator threading
        # pattern. The load-bearing invariants — what was charged and
        # what state shows after — remain pinned.
        recorder.record(
            "accumulate_cost",
            delta=round(delta, 6),
            new_state_total=round(self_orch.state.total_cost_usd, 6),
        )
        return new_local

    return wrapped


def make_save_state_recorder(
    recorder: TraceRecorder,
    original: Callable[..., None],
) -> Callable[..., None]:
    """Wrap state.save_state to record (path_basename, current_step, total_cost)."""

    def wrapped(claude_dir: Any, state: Any) -> None:
        try:
            path_basename = Path(claude_dir).name
        except (TypeError, ValueError):
            path_basename = str(claude_dir)
        recorder.record(
            "save_state",
            claude_dir=path_basename,
            current_step=getattr(state, "current_step", None),
            total_cost_usd=round(getattr(state, "total_cost_usd", 0.0), 6),
        )
        return original(claude_dir, state)

    return wrapped


def make_subprocess_dispatcher(
    recorder: TraceRecorder,
    *,
    gate_returncode: int | Callable[[int, str], int] = 0,
) -> Callable[..., Any]:
    """Return a subprocess.run replacement that dispatches by cmd[0].

    Deterministic outputs:
    - `git rev-parse HEAD` → DETERMINISTIC_SHA on stdout
    - `git tag <...>`  → rc=0
    - `git push <...>` → rc=0
    - `git diff --name-only ...` → empty stdout
    - any other `git ...` → rc=0 with empty stdout
    - any non-git command (assumed: quality-gate shell command) →
      rc=gate_returncode(call_index, cmd) if callable else gate_returncode

    The callable form takes (per-dispatcher gate-call-index, cmd_repr) so
    callers can encode "fail once then pass" stateful patterns. The index
    counts only non-git calls (gate calls), starting at 0.
    """

    class _Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    # Per-dispatcher mutable state: count of gate calls so the callable
    # form can implement "first N fail" patterns.
    gate_call_count = {"n": 0}

    def _resolve_gate_rc(cmd_repr: str) -> int:
        idx = gate_call_count["n"]
        gate_call_count["n"] += 1
        if callable(gate_returncode):
            return gate_returncode(idx, cmd_repr)
        return gate_returncode

    def dispatcher(*args, **kwargs) -> _Result:
        # First positional arg is the command (list or str depending on shell=True).
        cmd = args[0] if args else kwargs.get("args", [])
        is_shell = kwargs.get("shell", False)
        if isinstance(cmd, str):
            head = cmd.split()[0] if cmd.split() else ""
            cmd_repr = cmd
        elif isinstance(cmd, (list, tuple)) and cmd:
            head = str(cmd[0])
            cmd_repr = " ".join(str(c) for c in cmd)
        else:
            head = ""
            cmd_repr = ""

        recorder.record("subprocess", head=head, cmd=cmd_repr, shell=is_shell)

        if head == "git" or cmd_repr.startswith("git "):
            tokens = cmd_repr.split()
            if "rev-parse" in tokens:
                return _Result(returncode=0, stdout=DETERMINISTIC_SHA + "\n")
            return _Result(returncode=0, stdout="")
        # Anything else is treated as a quality-gate shell command.
        rc = _resolve_gate_rc(cmd_repr)
        return _Result(returncode=rc, stdout="", stderr="")

    return dispatcher


def make_run_claude_stub(recorder: TraceRecorder) -> Callable[..., Any]:
    """Return a run_claude replacement with per-call token variation.

    Each successive call gets the next entry in TOKEN_SHAPES and CALL_COSTS.
    Calls beyond the table reuse the last entry (Phase E retries).
    """
    from superpower_workflow.runner import ClaudeResult

    call_counter = {"n": 0}

    def stub(*args, **kwargs):
        i = call_counter["n"]
        call_counter["n"] += 1

        shape_idx = min(i, len(TOKEN_SHAPES) - 1)
        cost_idx = min(i, len(CALL_COSTS) - 1)
        usage = TOKEN_SHAPES[shape_idx]
        cost = CALL_COSTS[cost_idx]

        raw = {
            "type": "result",
            "is_error": False,
            "total_cost_usd": cost,
            "duration_ms": 1000 + i * 10,
            "session_id": f"sess-{i:02d}",
            "result": "ok",
            "usage": dict(usage),
        }

        recorder.record(
            "run_claude",
            call_index_local=i,
            cost=cost,
            session_id=raw["session_id"],
            usage=dict(usage),
        )

        return ClaudeResult(
            is_error=False,
            cost_usd=cost,
            duration_ms=raw["duration_ms"],
            session_id=raw["session_id"],
            text="ok",
            raw=raw,
        )

    return stub


def install_recorders(monkeypatch, orch, recorder: TraceRecorder, **opts) -> None:
    """Wire all recorders + stubs into the given Orchestrator instance.

    Args:
        monkeypatch: pytest's monkeypatch fixture.
        orch: a fully-constructed Orchestrator instance.
        recorder: a fresh TraceRecorder.
        gate_returncode: passed to the subprocess dispatcher (default 0).

    After this call returns:
    - orch._telemetry.emit subscribes the recorder before delegating.
    - orch._accumulate_cost records each (delta, new_total) call.
    - state.save_state (module-level) records each persist.
    - subprocess.run uses the cmd-prefix dispatcher.
    - orch._run_claude returns deterministic ClaudeResults with per-call
      token variation.

    The fixture file (when written) is deep-equal vs recorder.to_dict().
    """
    from superpower_workflow import orchestrator as orch_mod
    from superpower_workflow import state as state_mod

    # 1. Telemetry subscriber — wraps the existing emit.
    original_emit = orch._telemetry.emit
    subscriber = make_telemetry_subscriber(recorder)
    monkeypatch.setattr(
        orch._telemetry,
        "emit",
        lambda event: subscriber(original_emit, event),
    )

    # 2. _accumulate_cost — wrap the bound method via the class.
    original_accumulate = orch_mod.Orchestrator._accumulate_cost
    monkeypatch.setattr(
        orch_mod.Orchestrator,
        "_accumulate_cost",
        make_accumulate_cost_wrapper(recorder, original_accumulate),
    )

    # 3. save_state — wrap the module-level function. Patch the state
    # module's definition AND every module that already imported the
    # symbol (each `from superpower_workflow.state import save_state`
    # creates a local rebinding that bypasses the state-module patch).
    # The v1.2.0-real refactor moved several save_state callsites from
    # orchestrator.py into phase modules; each phase module's local
    # save_state binding needs its own patch so the recorder captures
    # every state-transition save.
    original_save_state = state_mod.save_state
    wrapped_save_state = make_save_state_recorder(recorder, original_save_state)
    monkeypatch.setattr(state_mod, "save_state", wrapped_save_state)

    _save_state_holders = [orch_mod]
    # Phase modules that import save_state at module load.
    for mod_name in (
        "superpower_workflow.phases.plan",
        "superpower_workflow.phases.implement",
        "superpower_workflow.phases.review",
        "superpower_workflow.phases.push",
        "superpower_workflow.phases.ci_fix",
    ):
        try:
            phase_mod = __import__(mod_name, fromlist=["save_state"])
            _save_state_holders.append(phase_mod)
        except ImportError:
            # Phase module not yet present (e.g., Task 1.x tests run
            # before Task 4+). Skip silently.
            pass

    for holder in _save_state_holders:
        if hasattr(holder, "save_state"):
            monkeypatch.setattr(holder, "save_state", wrapped_save_state)

    # 4. Subprocess dispatcher.
    dispatcher = make_subprocess_dispatcher(
        recorder,
        gate_returncode=opts.get("gate_returncode", 0),
    )
    monkeypatch.setattr("subprocess.run", dispatcher)

    # 5. run_claude stub — patch the orchestrator's imported symbol AND
    # the runner module's source, since various paths import via either.
    stub = make_run_claude_stub(recorder)
    if hasattr(orch_mod, "run_claude"):
        monkeypatch.setattr(orch_mod, "run_claude", stub)
    from superpower_workflow import runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_claude", stub)


# ---- fixture-blessing safeguards ----


def assert_trace_matches_fixture(
    recorder: TraceRecorder,
    fixture_path: Path,
) -> None:
    """Compare recorder output against a JSON fixture.

    If GOLDEN_TRACE_UPDATE=1 is set AND GOLDEN_TRACE_RATIONALE is also set
    to a non-empty string, the fixture is overwritten and the test passes.
    Both env vars are required — protects against accidental
    fixture-blessing when a developer's local refactor has introduced a
    regression. The rationale is written to a sidecar file
    `<fixture>.rationale.txt` for audit.

    Otherwise the recorder's trace is deep-equal compared against the
    fixture; on mismatch a detailed diff is printed and the test fails.
    """
    actual = recorder.to_dict()
    update_mode = os.environ.get("GOLDEN_TRACE_UPDATE") == "1"
    rationale = os.environ.get("GOLDEN_TRACE_RATIONALE", "").strip()

    if update_mode:
        if not rationale:
            raise RuntimeError(
                "GOLDEN_TRACE_UPDATE=1 requires GOLDEN_TRACE_RATIONALE "
                "to be set to a non-empty string explaining why the "
                "fixture is being changed. Aborting fixture update."
            )
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(json.dumps(actual, indent=2, sort_keys=False))
        rationale_path = fixture_path.with_suffix(fixture_path.suffix + ".rationale.txt")
        rationale_path.write_text(rationale + "\n")
        return

    if not fixture_path.exists():
        raise AssertionError(
            f"Golden trace fixture not found: {fixture_path}. "
            f"Re-run with GOLDEN_TRACE_UPDATE=1 and "
            f"GOLDEN_TRACE_RATIONALE='<reason>' to create it."
        )

    expected = json.loads(fixture_path.read_text())
    if actual != expected:
        # Surface the first divergence point for fast triage.
        a_recs = actual.get("records", [])
        e_recs = expected.get("records", [])
        for i, (a, e) in enumerate(zip(a_recs, e_recs, strict=False)):
            if a != e:
                raise AssertionError(
                    f"Trace divergence at index {i}:\n"
                    f"  expected: {json.dumps(e, sort_keys=True)}\n"
                    f"  actual:   {json.dumps(a, sort_keys=True)}"
                )
        # Same prefix; differ only in length.
        raise AssertionError(
            f"Trace length differs: actual={len(a_recs)} expected={len(e_recs)}.\n"
            f"First extra/missing record: "
            f"{json.dumps(a_recs[len(e_recs)] if len(a_recs) > len(e_recs) else e_recs[len(a_recs)], sort_keys=True)}"
        )
