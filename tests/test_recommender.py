"""Tests for the model recommender (T1.9.3)."""

from __future__ import annotations

import json

from superpower_workflow.recommender import _compute_stats, recommend


def _write(tmp_path, events):
    p = tmp_path / "telemetry.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events))
    return p


class TestComputeStats:
    def test_attributes_milestones_to_model(self):
        events = [
            {"type": "run_started", "run_id": "r1", "model": "opus"},
            {"type": "milestone_completed", "run_id": "r1", "cost_usd": 7.0},
            {"type": "milestone_completed", "run_id": "r1", "cost_usd": 5.0},
            {"type": "run_started", "run_id": "r2", "model": "sonnet"},
            {"type": "milestone_completed", "run_id": "r2", "cost_usd": 2.0},
        ]
        stats = _compute_stats(events)
        assert stats["opus"].milestone_count == 2
        assert stats["opus"].total_cost == 12.0
        assert stats["opus"].avg_cost_per_milestone == 6.0
        assert stats["sonnet"].milestone_count == 1

    def test_includes_spec_compliance_rate(self):
        events = [
            {"type": "run_started", "run_id": "r1", "model": "opus"},
            {"type": "milestone_completed", "run_id": "r1", "cost_usd": 1.0},
            {
                "type": "spec_compliance_completed",
                "run_id": "r1",
                "total_requirements": 10,
                "implemented": 9,
            },
        ]
        stats = _compute_stats(events)
        assert stats["opus"].spec_compliance_rate == 0.9


class TestRecommend:
    def test_insufficient_data_returns_provisional(self, tmp_path):
        p = _write(
            tmp_path,
            [
                {"type": "run_started", "run_id": "r1", "model": "opus"},
                {"type": "milestone_completed", "run_id": "r1", "cost_usd": 5.0},
            ],
        )
        report = recommend(p)
        assert report.recommended == "opus"
        assert "Insufficient" in report.rationale

    def test_recommends_best_efficiency(self, tmp_path):
        # opus: 3 milestones at $7 avg, 100% compliance -> quality 1.0
        # sonnet: 3 milestones at $2 avg, 80% compliance -> quality lower but cheaper
        events = [
            {"type": "run_started", "run_id": "ro", "model": "opus"},
        ]
        for _ in range(3):
            events.extend(
                [
                    {"type": "milestone_completed", "run_id": "ro", "cost_usd": 7.0},
                    {
                        "type": "spec_compliance_completed",
                        "run_id": "ro",
                        "total_requirements": 10,
                        "implemented": 10,
                    },
                ]
            )
        events.append({"type": "run_started", "run_id": "rs", "model": "sonnet"})
        for _ in range(3):
            events.extend(
                [
                    {"type": "milestone_completed", "run_id": "rs", "cost_usd": 2.0},
                    {
                        "type": "spec_compliance_completed",
                        "run_id": "rs",
                        "total_requirements": 10,
                        "implemented": 8,
                    },
                ]
            )
        p = _write(tmp_path, events)
        report = recommend(p)
        # v1.3.1 HIGH #7: tautological assertion replaced with deterministic check.
        # With the documented weights (0.4 compliance + 0.3*(1-strict) + 0.2*first_pass
        # + 0.1*curator_health), opus quality_score=0.95 at $7/ms → efficiency 0.136.
        # Sonnet quality_score=0.87 at $2/ms → efficiency 0.435. Sonnet wins.
        assert report.recommended == "sonnet", (
            f"sonnet has efficiency 0.435 vs opus 0.136; expected sonnet, got {report.recommended}"
        )
        # Rationale must name the winning model (non-tautological — production code
        # could change to omit the model name and this would catch it).
        assert "sonnet" in report.rationale

    def test_empty_telemetry_returns_empty(self, tmp_path):
        p = tmp_path / "telemetry.jsonl"
        p.write_text("")
        report = recommend(p)
        assert report.models == []
        assert "No model data" in report.rationale

    def test_missing_file_returns_empty(self, tmp_path):
        report = recommend(tmp_path / "nope.jsonl")
        assert report.models == []


class TestQualityScoreFormulaDecoupling:
    """v1.3.2 #20: first_pass_rate must be an INDEPENDENT signal from
    strict_iter_rate. Pre-fix, `first_pass_rate = 1 - strict_iter_rate`,
    so the 0.3 and 0.2 weighted terms collapsed into 0.5*(1-strict_iter_rate).
    These tests pin the new independent computation.
    """

    def test_first_pass_rate_from_milestone_count_not_strict_iter(self):
        # Model with 4 milestones, ONE has 4 strict iters (normalized to 1.0
        # in strict_iter_rate). pre-fix: first_pass_rate would be 1 -
        # (1.0/4) = 0.75 (a function of strict_iter_rate). new behavior:
        # first_pass_rate = milestones-without-strict / total = 3/4 = 0.75
        # — but only because the numerator and denominator coincidentally
        # produce the same ratio for this single-spike case. Verify by
        # forcing a divergent case below.
        events = [{"type": "run_started", "run_id": "rA", "model": "opus"}]
        for i in range(4):
            events.append({"type": "milestone_completed", "run_id": "rA", "milestone": f"M{i}"})
        # All 4 strict iters land on M0 → milestone count = 4, first-pass = 3.
        for _ in range(4):
            events.append({"type": "strict_mode_iteration", "run_id": "rA", "milestone": "M0"})

        stats = _compute_stats(events)
        s = stats["opus"]
        assert s.milestone_count == 4
        assert s.first_pass_milestones == 3
        assert s.first_pass_rate == 0.75

    def test_diverging_signals_produce_distinct_score(self):
        """Construct a scenario where strict_iter_rate and first_pass_rate
        give DIFFERENT numerical answers, so the new formula's score
        differs from what the collapsed pre-fix formula would have produced.
        """
        # 2 milestones, both have 2 strict iters each.
        # strict_iter_rate = (min(2/4,1) + min(2/4,1)) / 2 = 0.5
        # first_pass_rate (new) = 0 (no milestone is strict-iter-free)
        # Old formula's implied first_pass_rate = 1 - 0.5 = 0.5
        # New score has: 0.3*(1-0.5) + 0.2*0.0 = 0.15
        # Old score had: 0.3*(1-0.5) + 0.2*0.5 = 0.25
        # Delta = 0.10 → strictly different formulas.
        events = [{"type": "run_started", "run_id": "rB", "model": "opus"}]
        for i in range(2):
            events.append({"type": "milestone_completed", "run_id": "rB", "milestone": f"M{i}"})
        for ms in ("M0", "M1"):
            for _ in range(2):
                events.append({"type": "strict_mode_iteration", "run_id": "rB", "milestone": ms})

        stats = _compute_stats(events)
        s = stats["opus"]
        assert s.strict_iter_rate == 0.5
        assert s.first_pass_rate == 0.0
        # The collapsed pre-fix formula would have scored these two terms
        # at 0.5*(1-strict_iter_rate) = 0.25. The new formula scores 0.15.
        # Quality = 0.4*0 + 0.3*0.5 + 0.2*0 + 0.1*curator_health(0=0.5) = 0.20
        assert s.quality_score == 0.20, (
            f"expected 0.20 under new independent-signal formula, got {s.quality_score}; "
            "if this is failing because the formula collapsed back to "
            "first_pass_rate = 1 - strict_iter_rate, fix the implementation"
        )

    def test_zero_strict_means_full_first_pass(self):
        """Sanity: no strict iters anywhere → first_pass_rate = 1.0."""
        events = [{"type": "run_started", "run_id": "rC", "model": "opus"}]
        for i in range(3):
            events.append({"type": "milestone_completed", "run_id": "rC", "milestone": f"M{i}"})
        stats = _compute_stats(events)
        s = stats["opus"]
        assert s.strict_iter_rate == 0.0
        assert s.first_pass_rate == 1.0
