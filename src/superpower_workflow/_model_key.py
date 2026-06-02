"""Shared model_id extraction + canonicalization (v1.3.24).

Both `drift.py` and `calibration.py` need to identify a sample's model.
Centralizing here:
- ensures both modules treat `claude-haiku-4-5` and `haiku-4-5` as the same
  bucket
- gives one place to add new model aliases as they ship
- prevents drift/calibration from silently diverging on bucket keys
"""

from __future__ import annotations

_CANONICAL: dict[str, str] = {
    # Map raw → canonical. Both forward (claude-foo → foo) and direct
    # canonical → canonical entries so we can call canonicalize() twice
    # without harm.
    "claude-haiku-4-5": "haiku-4-5",
    "claude-sonnet-4-5": "sonnet-4-5",
    "claude-sonnet-4": "sonnet-4",
    "claude-opus-4-7": "opus-4-7",
    "claude-opus-4-8": "opus-4-8",
    "haiku-4-5": "haiku-4-5",
    "sonnet-4-5": "sonnet-4-5",
    "sonnet-4": "sonnet-4",
    "opus-4-7": "opus-4-7",
    "opus-4-8": "opus-4-8",
    # Legacy short aliases (pre-2026).
    "haiku": "haiku-4-5",
    "sonnet": "sonnet-4-5",
    "opus": "opus-4-7",
}


def canonicalize(raw: str | None) -> str | None:
    """Strip `claude-` prefix and lowercase. Unknown ids returned as-is
    (after lowercasing) so new models don't crash; just create their own
    bucket and may pick up a DEFAULT_TABLE fallback downstream.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _CANONICAL:
        return _CANONICAL[s]
    if s.startswith("claude-"):
        stripped = s[len("claude-") :]
        if stripped in _CANONICAL:
            return _CANONICAL[stripped]
        return stripped
    return s


def extract_model_id(event: dict) -> str | None:
    """Pull a canonical model_id from a telemetry event dict, or None.

    Inspects (in priority order):
    1. event["model_id"] (preferred — set on MilestoneCompleted v1.3.24+)
    2. event["model"] (RunStarted, ModelRouted, BestOfNCompleted.winner_model)

    Never raises. None → unbucketed (caller decides what to do).
    """
    if not isinstance(event, dict):
        return None
    for key in ("model_id", "model"):
        v = event.get(key)
        if v:
            return canonicalize(v)
    # BestOfNCompleted-style nested field.
    winner = event.get("winner_model")
    if winner:
        return canonicalize(winner)
    return None
