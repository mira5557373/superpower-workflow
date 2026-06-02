from __future__ import annotations

import inspect
import tomllib
from pathlib import Path


class TestValidation:
    """Quality gate validation tests."""

    def test_ruff_config_valid(self) -> None:
        """Verify ruff configuration is valid."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Verify [tool.ruff] section exists
        assert "tool" in config
        assert "ruff" in config["tool"]
        ruff_config = config["tool"]["ruff"]

        # Verify line-length is set
        assert "line-length" in ruff_config
        assert ruff_config["line-length"] == 100

        # Verify target-version is set
        assert "target-version" in ruff_config
        assert ruff_config["target-version"] == "py311"

        # Verify lint section exists
        assert "lint" in ruff_config
        lint_config = ruff_config["lint"]

        # Verify select rules are correct
        assert "select" in lint_config
        selected_rules = set(lint_config["select"])
        required_rules = {"E", "F", "I", "B", "UP", "SIM"}
        assert selected_rules == required_rules

        # Verify isort config exists
        assert "isort" in lint_config
        assert "known-first-party" in lint_config["isort"]
        assert lint_config["isort"]["known-first-party"] == ["todo"]

    def test_coverage_spec_minimum(self) -> None:
        """Verify coverage spec minimum of ≥90% is configured in pyproject.toml."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Verify coverage configuration exists
        assert "tool" in config
        assert "coverage" in config["tool"]
        coverage_config = config["tool"]["coverage"]

        # Verify [tool.coverage.report] has fail_under >= 90
        assert "report" in coverage_config
        assert "fail_under" in coverage_config["report"]
        fail_under = coverage_config["report"]["fail_under"]
        assert fail_under >= 90, f"Coverage fail_under {fail_under} is below spec minimum of 90"

    def test_no_circular_imports(self) -> None:
        """Verify package imports cleanly with no circular imports."""
        # This is a smoke test: if import succeeds, circular imports are not present
        import todo  # noqa: F401

        # Verify all __all__ exports are accessible immediately after import
        assert hasattr(todo, "Status")
        assert hasattr(todo, "Todo")
        assert hasattr(todo, "TodoList")
        assert hasattr(todo, "JsonStore")

    def test_package_exports_complete(self) -> None:
        """Verify package __all__ is complete and correct."""
        import todo

        # Assert exact __all__ contents
        expected_all = {"Status", "Todo", "TodoList", "JsonStore"}
        actual_all = set(todo.__all__)
        assert actual_all == expected_all, f"Expected __all__={expected_all}, got {actual_all}"

        # Verify each name is present in module namespace
        for name in expected_all:
            assert hasattr(todo, name), f"Export '{name}' not found in module namespace"
            obj = getattr(todo, name)
            assert obj is not None, f"Export '{name}' is None"
            # Verify it's a class or function (not a constant)
            assert inspect.isclass(obj) or inspect.isfunction(obj), (
                f"Export '{name}' is neither class nor function"
            )
