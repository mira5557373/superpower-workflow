"""v1.3.1 HIGH #3: `sw init` and `sw onboard` must produce equivalent
workflow.json shape + side effects (gitignore, project-local assets).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from superpower_workflow.cli import _cmd_init, _cmd_onboard, _postinit_setup


@pytest.fixture
def git_inited(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


class TestPostinitSetup:
    def test_writes_gitignore(self, git_inited):
        _postinit_setup(git_inited)
        gi = (git_inited / ".gitignore").read_text()
        assert ".claude/workflow-state.json" in gi
        assert ".coverage" in gi

    def test_idempotent(self, git_inited):
        _postinit_setup(git_inited)
        first = (git_inited / ".gitignore").read_text()
        _postinit_setup(git_inited)
        second = (git_inited / ".gitignore").read_text()
        assert first == second

    def test_install_assets_skipped_when_minimal(self, git_inited):
        """--minimal: skip skill/command install but keep gitignore."""
        _postinit_setup(git_inited, install_assets=False)
        assert (git_inited / ".gitignore").exists()
        # No skills directory was created
        assert not (git_inited / ".claude" / "skills").exists()


class TestInitOnboardParity:
    def _convergence_keys(self, config):
        return set(config["convergence"].keys())

    def _validation_keys(self, config):
        return set(config["validation"].keys())

    def test_init_writes_full_convergence_block(self, git_inited):
        _cmd_init(git_inited)
        config = json.loads((git_inited / ".claude" / "workflow.json").read_text())
        keys = self._convergence_keys(config)
        assert {
            "max_iterations",
            "min_gaps_for_substantial",
            "persistent_gap_downgrade_after",
        } <= keys

    def test_onboard_writes_full_convergence_block(self, git_inited):
        """v1.3.1 HIGH #3 parity fix: onboard previously only wrote max_iterations."""
        _cmd_onboard(git_inited, interactive=False)
        config = json.loads((git_inited / ".claude" / "workflow.json").read_text())
        keys = self._convergence_keys(config)
        assert "min_gaps_for_substantial" in keys
        assert "persistent_gap_downgrade_after" in keys

    def test_onboard_validation_block_complete(self, git_inited):
        """Onboard must include every key cli.py default_config writes."""
        _cmd_onboard(git_inited, interactive=False)
        onb = json.loads((git_inited / ".claude" / "workflow.json").read_text())
        # Compare against a fresh init in a sibling dir
        sib = git_inited.parent / (git_inited.name + "-init")
        sib.mkdir()
        subprocess.run(["git", "init"], cwd=sib, check=True, capture_output=True)
        _cmd_init(sib)
        init = json.loads((sib / ".claude" / "workflow.json").read_text())
        # All validation keys init writes should be in onboard's block.
        missing = self._validation_keys(init) - self._validation_keys(onb)
        assert not missing, f"onboard is missing validation keys: {missing}"

    def test_top_level_keys_bidirectional_parity(self, git_inited):
        """v1.3.3 #7: bidirectional parity check across all top-level keys.

        Pre-v1.3.3, the test only checked `init - onb` (one direction).
        Now assert symmetric difference is empty except for the explicit
        `_onboard` audit key onboard adds. A future contributor adding a
        new top-level key to ONE surface but not the other will fail this
        test loudly.
        """
        _cmd_onboard(git_inited, interactive=False)
        onb = json.loads((git_inited / ".claude" / "workflow.json").read_text())

        sib = git_inited.parent / (git_inited.name + "-init2")
        sib.mkdir()
        subprocess.run(["git", "init"], cwd=sib, check=True, capture_output=True)
        _cmd_init(sib)
        init = json.loads((sib / ".claude" / "workflow.json").read_text())

        init_keys = set(init)
        onb_keys = set(onb)
        # Onboard adds `_onboard` (audit trail) — that's the only allowed delta.
        allowed_onb_extras = {"_onboard"}

        missing_in_onb = init_keys - onb_keys
        extra_in_onb = onb_keys - init_keys - allowed_onb_extras
        assert not missing_in_onb, (
            f"onboard missing top-level keys that init writes: {sorted(missing_in_onb)}"
        )
        assert not extra_in_onb, (
            f"onboard writes unexpected top-level keys that init doesn't: "
            f"{sorted(extra_in_onb)} (add to allowed_onb_extras if intentional)"
        )

    def test_nested_block_parity_for_every_dict(self, git_inited):
        """v1.3.3 #7: for every nested dict block init writes, onboard's
        equivalent block must contain the same sub-keys. Catches drift one
        level deeper than the top-level test.
        """
        _cmd_onboard(git_inited, interactive=False)
        onb = json.loads((git_inited / ".claude" / "workflow.json").read_text())

        sib = git_inited.parent / (git_inited.name + "-init3")
        sib.mkdir()
        subprocess.run(["git", "init"], cwd=sib, check=True, capture_output=True)
        _cmd_init(sib)
        init = json.loads((sib / ".claude" / "workflow.json").read_text())

        # Compare every shared key whose value is a dict.
        offenders = []
        for k in set(init) & set(onb):
            if isinstance(init[k], dict) and isinstance(onb[k], dict):
                missing = set(init[k]) - set(onb[k])
                if missing:
                    offenders.append(f"  {k}.{sorted(missing)}")
        assert not offenders, "nested-block drift:\n" + "\n".join(offenders)

    def test_onboard_runs_postinit(self, git_inited):
        """Onboard must trigger the gitignore+install side effects."""
        _cmd_onboard(git_inited, interactive=False)
        # Gitignore populated
        gi = (git_inited / ".gitignore").read_text()
        assert ".claude/workflow-state.json" in gi
        # Project-local skills installed
        assert (git_inited / ".claude" / "skills").exists()
        assert any((git_inited / ".claude" / "skills").iterdir())
