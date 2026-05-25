from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.docs.api_docs import build_api_docs


def _success() -> CompletedProcess:
    return CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _failure() -> CompletedProcess:
    return CompletedProcess(args=[], returncode=1, stdout="", stderr="error")


class TestBuildApiDocsSphinx:
    def test_sphinx_runs_apidoc_then_build(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch(
            "superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()
        ) as mock:
            result = build_api_docs(src, out, tool="sphinx")
        assert result is True
        cmds = [c[0][0] for c in mock.call_args_list]
        assert any("sphinx-apidoc" in cmd for cmd in cmds)
        assert any("sphinx-build" in cmd for cmd in cmds)

    def test_sphinx_apidoc_failure_returns_false(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_failure()):
            result = build_api_docs(src, out, tool="sphinx")
        assert result is False

    def test_sphinx_build_failure_returns_false(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run") as mock:
            mock.side_effect = [_success(), _failure()]
            result = build_api_docs(src, out, tool="sphinx")
        assert result is False

    def test_creates_output_dir(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch("superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()):
            build_api_docs(src, out, tool="sphinx")
        assert out.exists()


class TestBuildApiDocsMkdocs:
    def test_mkdocs_runs_build(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with patch(
            "superpower_workflow.docs.api_docs.subprocess.run", return_value=_success()
        ) as mock:
            result = build_api_docs(src, out, tool="mkdocs")
        assert result is True
        cmd = mock.call_args[0][0]
        assert "mkdocs" in cmd
        assert "build" in cmd

    def test_unsupported_tool_raises(self, tmp_path: Path):
        src = tmp_path / "src"
        out = tmp_path / "docs" / "api"
        src.mkdir()
        with pytest.raises(ValueError, match="Unsupported"):
            build_api_docs(src, out, tool="unknown")
