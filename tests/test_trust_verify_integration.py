from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from superpower_workflow.hooks.convergence_gate import compute_exit_code
from superpower_workflow.runner import ClaudeResult
from superpower_workflow.state import VALID_STEPS, WorkflowState, load_state, save_state
from superpower_workflow.telemetry import (
    FeatureVerificationCompleted,
    GapValidationEvent,
    SpecComplianceCompleted,
)


class TestEndToEndGapValidation:
    def test_full_gap_validation_pipeline(self, tmp_path: Path):
        """Full pipeline: create files, write gap report, run convergence gate."""
        (tmp_path / "src" / "mod").mkdir(parents=True)
        (tmp_path / "src" / "mod" / "store.py").write_text(
            "class Store:\n    def put(self, key, value):\n        pass\n"
        )

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        config = {
            "validation": {"gap_validator": True, "gap_validation_mode": "strict"},
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        gap_report = {
            "pass": 1,
            "critical_gaps": 1,
            "important_gaps": 3,
            "tests_green": True,
            "lint_clean": True,
            "converged": False,
            "gap_summaries": [
                "[ultrathink] src/mod/store.py:2 put method missing validation",
                "[ultrathink] nonexistent_module.py:99 has a critical bug",
                "[ultrathink] the overall architecture needs improvement",
                "[ultrathink] src/mod/store.py:1 Store class needs docstring",
            ],
        }
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))

        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))

        compute_exit_code(claude_dir)

        validation_path = claude_dir / ".gap-validation.json"
        assert validation_path.exists()
        validation = json.loads(validation_path.read_text())
        assert validation["total_gaps"] == 4
        assert validation["valid_gaps"] >= 2
        assert validation["invalid_gaps"] >= 1

    def test_validation_disabled_backward_compat(self, tmp_path: Path):
        """No validation section = backward compatible behavior."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        config = {"model": "opus"}
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        gap_report = {
            "critical_gaps": 0,
            "important_gaps": 1,
            "tests_green": True,
            "lint_clean": True,
            "gap_summaries": ["[ultrathink] concern"],
        }
        (claude_dir / ".gap-report.json").write_text(json.dumps(gap_report))
        phase = {"phase": "ultrathink", "iteration": 0, "max_iterations": 5}
        (claude_dir / ".workflow-phase.json").write_text(json.dumps(phase))

        code = compute_exit_code(claude_dir)
        assert code == 0
        assert not (claude_dir / ".gap-validation.json").exists()


class TestEndToEndResumeStates:
    def test_resume_from_spec_compliance(self, tmp_path: Path):
        """State can save and load spec_compliance step."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        state = WorkflowState()
        state.current_step = "spec_compliance"
        state.current_milestone_index = 2
        save_state(claude_dir, state)

        loaded = load_state(claude_dir)
        assert loaded.current_step == "spec_compliance"
        assert loaded.current_milestone_index == 2

    def test_resume_from_feature_verify(self, tmp_path: Path):
        """State can save and load feature_verify step."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        state = WorkflowState()
        state.current_step = "feature_verify"
        save_state(claude_dir, state)

        loaded = load_state(claude_dir)
        assert loaded.current_step == "feature_verify"


class TestEndToEndTelemetry:
    def test_gap_validation_event_serialization(self):
        e = GapValidationEvent(
            milestone="test-ms",
            total=10,
            valid=7,
            invalid=2,
            unverifiable=1,
            duplicate=1,
        )
        e.to_dict()
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "gap_validation"
        assert parsed["total"] == 10

    def test_spec_compliance_event_serialization(self):
        e = SpecComplianceCompleted(
            milestone="test-ms",
            total_requirements=15,
            implemented=13,
            missing=2,
            cost_usd=2.5,
        )
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "spec_compliance_completed"
        assert parsed["missing"] == 2

    def test_feature_verification_event_serialization(self):
        e = FeatureVerificationCompleted(
            milestone="test-ms",
            total_features=10,
            verified=8,
            broken=1,
            manual_review=1,
            cost_usd=3.5,
        )
        line = e.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "feature_verification_completed"
        assert parsed["broken"] == 1


class TestEndToEndValidSteps:
    def test_all_new_steps_in_valid_steps(self):
        assert "spec_compliance" in VALID_STEPS
        assert "feature_verify" in VALID_STEPS

    def test_existing_steps_unchanged(self):
        for step in (
            "plan",
            "implement",
            "review",
            "push",
            "quality_check_b",
            "quality_check_c",
        ):
            assert step in VALID_STEPS


class TestEndToEndConfig:
    def test_init_creates_validation_config(self, tmp_path: Path):
        from superpower_workflow.cli import _cmd_init

        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        v = config["validation"]
        assert v["gap_validator"] is True
        assert v["gap_validation_mode"] == "lenient"
        assert v["spec_compliance"] is True
        assert v["feature_verification"] is True
        assert v["spec_compliance_budget"] == 3.0
        assert v["feature_verification_budget"] == 5.0


class TestEndToEndSpecCompliance:
    @patch("superpower_workflow.orchestrator.run_claude")
    def test_orchestrator_compliance_flow(self, mock_run, tmp_path: Path):
        """Orchestrator calls spec compliance when enabled."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config = {
            "spec": "spec.md",
            "model": "opus",
            "budgets": {"plan": 1, "implement": 1, "review": 1, "push": 1},
            "milestones": [{"name": "test-ms", "spec_sections": "1, 2"}],
            "convergence": {"max_iterations": 5},
            "validation": {
                "spec_compliance": True,
                "spec_compliance_budget": 3.0,
                "feature_verification": True,
                "feature_verification_budget": 5.0,
            },
        }
        (claude_dir / "workflow.json").write_text(json.dumps(config))

        from superpower_workflow.orchestrator import Orchestrator

        with patch("superpower_workflow.orchestrator.acquire_lock", return_value=True):
            orch = Orchestrator(tmp_path)
        orch._telemetry = MagicMock()
        orch._audit = MagicMock()

        mock_run.return_value = ClaudeResult(
            text=json.dumps(
                {
                    "spec_path": "spec.md",
                    "spec_sections": "1, 2",
                    "total_requirements": 5,
                    "implemented": 5,
                    "missing": 0,
                    "details": [],
                }
            ),
            cost_usd=2.0,
        )

        report, cost = orch._run_spec_compliance(
            "test-ms", {"name": "test-ms", "spec_sections": "1, 2"}
        )
        assert report is not None
        assert report["missing"] == 0
        assert cost == 2.0
        assert (claude_dir / ".spec-compliance.json").exists()
