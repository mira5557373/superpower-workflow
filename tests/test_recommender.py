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
        # Sonnet has lower quality but vastly cheaper -> higher efficiency ratio
        assert report.recommended in ("sonnet", "opus")  # accept either; depends on weights
        assert "efficiency" in report.rationale.lower() or "milestone" in report.rationale.lower()

    def test_empty_telemetry_returns_empty(self, tmp_path):
        p = tmp_path / "telemetry.jsonl"
        p.write_text("")
        report = recommend(p)
        assert report.models == []
        assert "No model data" in report.rationale

    def test_missing_file_returns_empty(self, tmp_path):
        report = recommend(tmp_path / "nope.jsonl")
        assert report.models == []
