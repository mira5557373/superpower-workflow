"""Unit tests for _model_key.py — shared model-id canonicalization (v1.3.24)."""

from __future__ import annotations

from superpower_workflow._model_key import canonicalize, extract_model_id


class TestCanonicalize:
    def test_none_returns_none(self) -> None:
        assert canonicalize(None) is None

    def test_empty_returns_none(self) -> None:
        assert canonicalize("") is None
        assert canonicalize("   ") is None

    def test_strips_claude_prefix(self) -> None:
        assert canonicalize("claude-haiku-4-5") == "haiku-4-5"
        assert canonicalize("claude-sonnet-4-5") == "sonnet-4-5"
        assert canonicalize("claude-opus-4-7") == "opus-4-7"

    def test_already_canonical_pass_through(self) -> None:
        assert canonicalize("haiku-4-5") == "haiku-4-5"
        assert canonicalize("sonnet-4-5") == "sonnet-4-5"

    def test_legacy_short_alias(self) -> None:
        assert canonicalize("haiku") == "haiku-4-5"
        assert canonicalize("sonnet") == "sonnet-4-5"
        assert canonicalize("opus") == "opus-4-7"

    def test_case_insensitive(self) -> None:
        assert canonicalize("Claude-Haiku-4-5") == "haiku-4-5"
        assert canonicalize("HAIKU") == "haiku-4-5"

    def test_unknown_returns_lowercased(self) -> None:
        """Unknown model id is preserved (after lowercase + strip claude-).
        Lets new models work without code changes."""
        assert canonicalize("claude-future-9") == "future-9"
        assert canonicalize("custom-model") == "custom-model"

    def test_idempotent(self) -> None:
        first = canonicalize("claude-haiku-4-5")
        second = canonicalize(first)
        assert first == second == "haiku-4-5"


class TestExtractModelId:
    def test_non_dict_returns_none(self) -> None:
        assert extract_model_id("not a dict") is None  # type: ignore[arg-type]
        assert extract_model_id(None) is None  # type: ignore[arg-type]

    def test_missing_model_keys_returns_none(self) -> None:
        assert extract_model_id({"type": "milestone_started"}) is None

    def test_prefers_model_id(self) -> None:
        """model_id field (v1.3.24+) takes priority over legacy `model`."""
        ev = {"model_id": "haiku-4-5", "model": "opus"}
        assert extract_model_id(ev) == "haiku-4-5"

    def test_falls_back_to_model(self) -> None:
        ev = {"model": "claude-sonnet-4-5"}
        assert extract_model_id(ev) == "sonnet-4-5"

    def test_winner_model_field(self) -> None:
        """BestOfNCompleted-style event with winner_model."""
        ev = {"winner_model": "claude-opus-4-7"}
        assert extract_model_id(ev) == "opus-4-7"

    def test_drift_and_calibration_use_identical_keys(self) -> None:
        """Cross-module consistency anchor: feed both modules the same
        event, assert they produce the same key (verdict revision #4)."""
        from superpower_workflow.drift import bucket_key_for_phase

        ev = {"phase": "implement", "model": "claude-haiku-4-5"}
        mk = extract_model_id(ev)
        assert mk == "haiku-4-5"
        # Drift's existing bucket key includes model_id verbatim, so
        # feeding it the canonicalized id yields the same bucket prefix.
        assert bucket_key_for_phase("implement", mk) == "implement|haiku-4-5"
