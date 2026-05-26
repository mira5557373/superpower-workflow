from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestValidationConfig:
    def test_init_includes_validation_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "validation" in config
        v = config["validation"]
        assert v["gap_validator"] is True
        assert v["gap_validation_mode"] == "lenient"
        assert v["spec_compliance"] is True
        assert v["feature_verification"] is True
        assert v["spec_compliance_budget"] == 3.0
        assert v["feature_verification_budget"] == 5.0

    def test_validation_package_importable(self):
        import superpower_workflow.validation

        assert hasattr(superpower_workflow.validation, "__all__")
