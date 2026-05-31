"""v1.3.2 #5: `sw onboard` with accept_existing="merge" must actually merge,
not silently overwrite (which was the v1.3.1 behavior despite the menu
offering "merge" as a distinct option from "replace").
"""

from __future__ import annotations

import json

from superpower_workflow.cli import _shallow_merge


class TestShallowMerge:
    def test_overlay_keys_win_at_top_level(self):
        existing = {"model": "haiku", "spec": "old.md"}
        overlay = {"model": "opus"}
        merged = _shallow_merge(existing, overlay)
        assert merged["model"] == "opus"
        # Existing-only key preserved.
        assert merged["spec"] == "old.md"

    def test_existing_only_keys_preserved(self):
        """Hand-edited keys the user added that onboard doesn't know about
        must survive a merge."""
        existing = {
            "model": "haiku",
            "custom_user_key": "hand-edited",
            "_onboard": {"timestamp": "2025-12-01"},
        }
        overlay = {"model": "opus"}
        merged = _shallow_merge(existing, overlay)
        assert merged["custom_user_key"] == "hand-edited"
        assert merged["_onboard"] == {"timestamp": "2025-12-01"}

    def test_nested_dict_keys_merge_one_level_deep(self):
        """validation.foo and validation.bar should both survive when the
        overlay only redefines validation.foo."""
        existing = {
            "validation": {
                "spec_linter": False,
                "user_added_flag": True,
                "spec_compliance_budget": 99.0,
            }
        }
        overlay = {
            "validation": {
                "spec_linter": True,
                "strict_mode": False,
            }
        }
        merged = _shallow_merge(existing, overlay)
        assert merged["validation"]["spec_linter"] is True  # overlay wins
        assert merged["validation"]["strict_mode"] is False  # overlay adds
        assert merged["validation"]["user_added_flag"] is True  # existing preserved
        assert merged["validation"]["spec_compliance_budget"] == 99.0

    def test_overlay_scalar_replaces_existing_dict(self):
        """Documented edge: if the user had a dict where overlay has a scalar,
        overlay wins outright (no partial merge)."""
        existing = {"telemetry": {"enabled": True, "path": "custom.jsonl"}}
        overlay = {"telemetry": False}
        merged = _shallow_merge(existing, overlay)
        assert merged["telemetry"] is False

    def test_overlay_list_replaces_existing_list(self):
        """Lists replace wholesale — we don't try to be clever about
        deduplication or append semantics."""
        existing = {"milestones": [{"name": "M1"}]}
        overlay = {"milestones": []}
        merged = _shallow_merge(existing, overlay)
        assert merged["milestones"] == []


class TestOnboardMergeFlow:
    """End-to-end check that the menu option is correctly wired."""

    def test_merge_preserves_custom_keys(self, tmp_path, monkeypatch):
        from superpower_workflow.cli import _cmd_onboard

        claude = tmp_path / ".claude"
        claude.mkdir()
        existing = {
            "model": "haiku",
            "spec": "user-spec.md",
            "custom_key_user_added": "value",
            "validation": {"spec_linter": False, "extra": True},
        }
        (claude / "workflow.json").write_text(json.dumps(existing))

        # Drive non-interactive onboard with merge choice via OnboardConfig
        # override. We patch onboard.run_onboard to return a config that
        # sets accept_existing="merge".
        from superpower_workflow import cli as cli_mod
        from superpower_workflow import onboard as onboard_mod
        from superpower_workflow.onboard import OnboardConfig

        def _fake_run(project_root, interactive):
            cfg = OnboardConfig()
            cfg.accept_existing = "merge"
            cfg.spec_path = "spec.md"
            cfg.model = "opus"
            return cfg

        monkeypatch.setattr(onboard_mod, "run_onboard", _fake_run)
        # Drop the noop reference so ruff/import-check stays happy.
        assert cli_mod is not None

        # Suppress interactive confirmation prompt by forcing non-interactive.
        _cmd_onboard(tmp_path, interactive=False)

        written = json.loads((claude / "workflow.json").read_text())
        # Onboard answers won
        assert written["model"] == "opus"
        # User-added custom key preserved
        assert written.get("custom_key_user_added") == "value"
        # Nested validation: existing extra preserved, overlay overrides shared
        assert written["validation"].get("extra") is True
        # Onboard sets spec_linter back to True
        assert written["validation"].get("spec_linter") is True
