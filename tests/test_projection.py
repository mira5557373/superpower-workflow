"""Tests for src/superpower_workflow/projection.py.

Per-phase cost projection algorithm. Pinned by the workflow-designed
DESIGN_SCHEMA + Verdict 1's 5 algorithm fixes:

1. Cold-start ratios calibrated from soak data (plan=0.23, implement=0.54,
   review=0.20, push=0.03) — NOT the original 0.30/0.40/0.20/0.05 which
   under-weighted Phase B.
2. Failed/skipped milestone cost counted via state.total_cost_usd /
   (completed+failed+skipped), not just cost_by_milestone.
3. Custom phase residual ratios renormalize to 1.0 (no negative weights).
4. Single-milestone runs escape cold-start once first PhaseCompleted fires.
5. All-zero costs return projected=0, confidence=0 (degenerate).
"""

from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.projection import (
    COLD_START_RATIOS,
    _renormalize_ratios,
    compute_projection,
    load_phase_history,
)


def _write_telemetry(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events))


# ---- cold-start ratio calibration (Verdict 1 fix #1) ----


class TestColdStartRatios:
    def test_ratios_match_soak_data(self):
        """Soak data showed plan~0.23, implement~0.54, review~0.20,
        push~0.03 across 8 real milestones. The prior design's
        0.30/0.40/0.20/0.05 under-weighted Phase B by ~35%."""
        assert COLD_START_RATIOS["plan"] == 0.23
        assert COLD_START_RATIOS["implement"] == 0.54
        assert COLD_START_RATIOS["review"] == 0.20
        assert COLD_START_RATIOS["push"] == 0.03

    def test_ratios_sum_to_one(self):
        # Should sum to ≈1.0 (we use 1e-6 tolerance for float arithmetic).
        total = sum(COLD_START_RATIOS.values())
        assert abs(total - 1.0) < 1e-6


# ---- custom-phase renormalization (Verdict 1 fix #3) ----


class TestRenormalizeRatios:
    def test_known_phases_only_passthrough(self):
        ratios = _renormalize_ratios(["plan", "implement", "review", "push"])
        assert abs(sum(ratios.values()) - 1.0) < 1e-6
        # Each known phase retains its soak-validated ratio.
        assert ratios["implement"] == 0.54

    def test_unknown_phase_gets_positive_ratio(self):
        """Verdict 1 fix #3 — original residual formula went negative
        when defaults already summed to 1.0. After fix: unknown phases
        share via renormalization, never negative."""
        ratios = _renormalize_ratios(["plan", "implement", "review", "push", "custom_phase"])
        assert ratios["custom_phase"] > 0
        # All ratios sum to 1.0.
        assert abs(sum(ratios.values()) - 1.0) < 1e-6

    def test_only_unknown_phases_uniform(self):
        ratios = _renormalize_ratios(["wat", "huh"])
        assert ratios["wat"] == 0.5
        assert ratios["huh"] == 0.5


# ---- load_phase_history ----


class TestLoadPhaseHistory:
    def test_missing_telemetry_returns_empty(self, tmp_path):
        h = load_phase_history(tmp_path / "nonexistent.jsonl", "implement")
        assert h.n == 0
        assert h.mean == 0.0

    def test_loads_phase_completed_events(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [
                {"type": "phase_completed", "phase": "implement", "cost_usd": 5.0},
                {"type": "phase_completed", "phase": "implement", "cost_usd": 6.0},
                {"type": "phase_completed", "phase": "implement", "cost_usd": 7.0},
                {"type": "phase_completed", "phase": "plan", "cost_usd": 2.0},  # ignored
                {"type": "phase_started", "phase": "implement"},  # ignored
            ],
        )
        h = load_phase_history(tel, "implement")
        assert h.n == 3
        assert h.samples == [5.0, 6.0, 7.0]
        assert h.mean == 6.0

    def test_filters_zero_and_negative_costs(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [
                {"type": "phase_completed", "phase": "implement", "cost_usd": 0.0},
                {"type": "phase_completed", "phase": "implement", "cost_usd": -1.0},
                {"type": "phase_completed", "phase": "implement", "cost_usd": 5.0},
            ],
        )
        h = load_phase_history(tel, "implement")
        assert h.samples == [5.0]

    def test_limit_respected(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [
                {"type": "phase_completed", "phase": "implement", "cost_usd": float(i)}
                for i in range(1, 21)
            ],
        )
        h = load_phase_history(tel, "implement", limit=5)
        # Most-recent 5 (jsonl is chronological — last 5 = 16..20).
        assert h.samples == [16.0, 17.0, 18.0, 19.0, 20.0]

    def test_single_sample_uses_fallback_stdev(self, tmp_path):
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [{"type": "phase_completed", "phase": "plan", "cost_usd": 10.0}],
        )
        h = load_phase_history(tel, "plan")
        # Single sample → stdev = 30% of mean (fallback).
        assert h.stdev == 3.0


# ---- compute_projection: degenerate / terminal ----


class TestComputeProjectionDegenerate:
    def test_zero_milestones(self, tmp_path):
        r = compute_projection(
            state_total_cost=0.0,
            milestones_total=0,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=[],
            completed_phases_this_milestone=[],
            telemetry_path=tmp_path / "tel.jsonl",
        )
        assert r.projected_total == 0.0
        assert r.confidence == 1.0
        assert r.source == "cold_start"

    def test_all_done(self, tmp_path):
        r = compute_projection(
            state_total_cost=42.5,
            milestones_total=3,
            milestones_completed=3,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=[],
            completed_phases_this_milestone=[],
            telemetry_path=tmp_path / "tel.jsonl",
        )
        # Nothing left → projected equals spent.
        assert r.projected_total == 42.5
        assert r.low_p10 == 42.5
        assert r.high_p90 == 42.5
        assert r.confidence == 1.0


# ---- compute_projection: cold-start ----


class TestComputeProjectionColdStart:
    def test_no_history_uses_cold_start_default(self, tmp_path):
        r = compute_projection(
            state_total_cost=0.0,
            milestones_total=3,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["plan", "implement", "review", "push"],
            completed_phases_this_milestone=[],
            telemetry_path=tmp_path / "tel.jsonl",
            config_cost_per_ms_default=10.0,
        )
        assert r.source == "cold_start"
        # 3 milestones × $10 default = $30 baseline.
        assert r.projected_total == 30.0
        assert r.confidence == 0.0
        # ±30% band on cold-start.
        assert abs(r.low_p10 - 30.0 * 0.7) < 0.01
        assert abs(r.high_p90 - 30.0 * 1.3) < 0.01

    def test_cold_start_blends_observed_avg_with_default(self, tmp_path):
        """Verdict 1 fix #2 — observed_milestone_avg captures state cost
        from completed+failed+skipped."""
        r = compute_projection(
            state_total_cost=20.0,
            milestones_total=3,
            milestones_completed=1,
            milestones_failed=1,  # Verdict 1 fix #2: failed cost counted
            milestones_skipped=0,
            remaining_phases=["plan", "implement"],
            completed_phases_this_milestone=[],
            telemetry_path=tmp_path / "tel.jsonl",
            config_cost_per_ms_default=15.0,
        )
        # observed_avg = 20 / (1+1) = 10
        # blended with default 15 → (10+15)/2 = 12.5
        # remaining = 1 (3 total - 2 done) → projected = 20 + 12.5 = 32.5
        assert r.projected_total == 32.5


# ---- compute_projection: partial / full history ----


class TestComputeProjectionWithHistory:
    def _seed_history(self, tmp_path, phase_samples: dict[str, list[float]]):
        tel = tmp_path / "tel.jsonl"
        events = []
        for phase, samples in phase_samples.items():
            for s in samples:
                events.append({"type": "phase_completed", "phase": phase, "cost_usd": s})
        _write_telemetry(tel, events)
        return tel

    def test_full_history_uses_historical_mean(self, tmp_path):
        """With 10+ samples per phase, uses historical mean for the
        projection."""
        tel = self._seed_history(
            tmp_path,
            {
                "implement": [5.0] * 10,
                "review": [3.0] * 10,
            },
        )
        r = compute_projection(
            state_total_cost=2.0,  # plan done, cost in state
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement", "review"],
            completed_phases_this_milestone=["plan"],
            telemetry_path=tel,
        )
        # Phase A done ($2), expected: 2 + (5+3) = 10 for active milestone
        # remaining milestones = 0 (this is the only one)
        assert r.source == "full_history"
        assert r.projected_total == 10.0
        # Confidence saturates with 10+ samples per remaining phase.
        assert r.confidence == 1.0

    def test_partial_history_escapes_cold_start(self, tmp_path):
        """Verdict 1 fix #4 — single-milestone run with 3+ samples per
        phase should NOT be cold_start."""
        tel = self._seed_history(
            tmp_path,
            {"implement": [4.0, 5.0, 6.0]},
        )
        r = compute_projection(
            state_total_cost=2.0,
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement"],
            completed_phases_this_milestone=["plan"],
            telemetry_path=tel,
        )
        assert r.source == "partial_history"
        # 3 implement samples (mean 5) → expected $5 for implement.
        # projected = state + active = 2 + 5 = 7.
        assert r.projected_total == 7.0
        # Confidence < 1 (only 3 samples vs 10 saturation).
        assert 0 < r.confidence < 1.0

    def test_per_phase_breakdown_returned(self, tmp_path):
        tel = self._seed_history(
            tmp_path,
            {"implement": [8.0] * 5, "review": [3.0] * 5},
        )
        r = compute_projection(
            state_total_cost=0.0,
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement", "review"],
            completed_phases_this_milestone=[],
            telemetry_path=tel,
        )
        assert r.per_phase_breakdown == {"implement": 8.0, "review": 3.0}

    def test_confidence_band_widens_with_variance(self, tmp_path):
        """High-variance history → wider p10/p90 band."""
        tel_narrow = tmp_path / "narrow.jsonl"
        tel_narrow.write_text(
            "\n".join(
                json.dumps({"type": "phase_completed", "phase": "implement", "cost_usd": 5.0})
                for _ in range(10)
            )
        )

        tel_wide = tmp_path / "wide.jsonl"
        tel_wide.write_text(
            "\n".join(
                json.dumps({"type": "phase_completed", "phase": "implement", "cost_usd": c})
                for c in [1.0, 9.0, 1.0, 9.0, 1.0, 9.0, 1.0, 9.0, 1.0, 9.0]
            )
        )

        common = dict(
            state_total_cost=0.0,
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement"],
            completed_phases_this_milestone=[],
        )
        r_narrow = compute_projection(**common, telemetry_path=tel_narrow)
        r_wide = compute_projection(**common, telemetry_path=tel_wide)

        narrow_band = r_narrow.high_p90 - r_narrow.low_p10
        wide_band = r_wide.high_p90 - r_wide.low_p10
        assert wide_band > narrow_band

    def test_projected_total_never_below_current_spend(self, tmp_path):
        """Monotonicity: projection should not go below already-spent cost."""
        tel = self._seed_history(tmp_path, {"implement": [1.0] * 10})
        r = compute_projection(
            state_total_cost=50.0,  # spent way more than implement avg suggests
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement"],
            completed_phases_this_milestone=["plan"],
            telemetry_path=tel,
        )
        assert r.projected_total >= 50.0


# ---- Verdict 1 fix #5 (all-zero costs) ----


class TestAllZeroCosts:
    def test_zero_cost_history_filtered(self, tmp_path):
        """All claude calls returning $0 → no samples added (cost > 0 filter);
        falls through to cold-start path."""
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [{"type": "phase_completed", "phase": "implement", "cost_usd": 0.0} for _ in range(10)],
        )
        r = compute_projection(
            state_total_cost=0.0,
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement"],
            completed_phases_this_milestone=[],
            telemetry_path=tel,
        )
        assert r.source == "cold_start"


# ---- variance / band sanity ----


class TestBandSanity:
    def test_low_p10_at_least_current_spend(self, tmp_path):
        """p10 is clamped to current spend — projection can be lower than
        the mean only down to what's already spent (can't refund)."""
        tel = tmp_path / "tel.jsonl"
        _write_telemetry(
            tel,
            [{"type": "phase_completed", "phase": "implement", "cost_usd": 5.0} for _ in range(10)],
        )
        r = compute_projection(
            state_total_cost=8.0,  # already spent more than implement avg
            milestones_total=1,
            milestones_completed=0,
            milestones_failed=0,
            milestones_skipped=0,
            remaining_phases=["implement"],
            completed_phases_this_milestone=["plan"],
            telemetry_path=tel,
        )
        assert r.low_p10 >= 8.0
