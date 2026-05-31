"""v1.3.2 #16: pin `pyproject.toml[project].version` == `superpower_workflow.__version__`.

Without this, a release that hand-bumps one file but forgets the other
ships a wheel where `sw --version` reports a stale number. Trivial check
with high catch-rate; runs in every test run.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import superpower_workflow

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_version_matches_init_dunder_version():
    pyproject = ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pyproject_version = data["project"]["version"]
    assert pyproject_version == superpower_workflow.__version__, (
        f"version drift: pyproject.toml says {pyproject_version!r} but "
        f"superpower_workflow.__version__ is {superpower_workflow.__version__!r}. "
        "Update both files together."
    )


def test_cli_version_string_matches_init():
    """`sw --version` (built from __version__) must agree with the module's
    __version__ — both are downstream of pyproject.toml."""
    # Just check that argparse `--version` action wires to __version__.
    from superpower_workflow.cli import build_parser

    parser = build_parser()
    # The version action stores the version string on the parser; argparse
    # exposes it via the version action's `version` attribute.
    version_action = None
    for action in parser._actions:
        if action.dest == "version":
            version_action = action
            break
    assert version_action is not None, "sw --version not wired"
    assert superpower_workflow.__version__ in version_action.version
    # And we're on a supported Python that has tomllib (just guards against
    # an accidental drop of py3.11+).
    assert sys.version_info >= (3, 11)
