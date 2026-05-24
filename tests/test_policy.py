from __future__ import annotations

from superpower_workflow.policy import PolicyEngine


class TestMaxFileLines:
    def test_passes_when_under_limit(self, tmp_path):
        (tmp_path / "short.py").write_text("x = 1\ny = 2\n")
        engine = PolicyEngine({"max_file_lines": 100})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "short.py"])
        assert passed is True
        assert violations == []

    def test_fails_when_over_limit(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(101))
        (tmp_path / "long.py").write_text(content)
        engine = PolicyEngine({"max_file_lines": 100})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "long.py"])
        assert passed is False
        assert any("long.py" in v for v in violations)
        assert any("101" in v or "100" in v for v in violations)

    def test_exactly_at_limit_passes(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(100))
        (tmp_path / "exact.py").write_text(content)
        engine = PolicyEngine({"max_file_lines": 100})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "exact.py"])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(1000))
        (tmp_path / "huge.py").write_text(content)
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "huge.py"])
        assert passed is True


class TestBannedImports:
    def test_detects_banned_import(self, tmp_path):
        (tmp_path / "bad.py").write_text("import os\nos.system('rm -rf /')\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False
        assert any("os.system" in v for v in violations)

    def test_detects_banned_from_import(self, tmp_path):
        (tmp_path / "bad.py").write_text("from subprocess import call\ncall('ls')\n")
        engine = PolicyEngine({"banned_imports": ["subprocess.call"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False
        assert any("subprocess.call" in v for v in violations)

    def test_allows_non_banned_imports(self, tmp_path):
        (tmp_path / "good.py").write_text("import json\nimport pathlib\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "good.py"])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        (tmp_path / "any.py").write_text("import os\nos.system('x')\n")
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "any.py"])
        assert passed is True

    def test_handles_syntax_error_gracefully(self, tmp_path):
        (tmp_path / "broken.py").write_text("def (\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "broken.py"])
        assert passed is True

    def test_multiple_banned_in_same_file(self, tmp_path):
        code = "import os\nos.system('a')\nfrom subprocess import call\ncall('b')\n"
        (tmp_path / "multi.py").write_text(code)
        engine = PolicyEngine({"banned_imports": ["os.system", "subprocess.call"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "multi.py"])
        assert passed is False
        assert len(violations) >= 2

    def test_non_python_files_skipped(self, tmp_path):
        (tmp_path / "data.txt").write_text("import os\nos.system('x')\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "data.txt"])
        assert passed is True


class TestChangedFilesDiscovery:
    def test_changed_files_from_git_diff(self, tmp_path):
        from subprocess import CompletedProcess
        from unittest.mock import patch

        diff_output = "src/foo.py\nsrc/bar.py\n"

        def mock_run(cmd, **kwargs):
            return CompletedProcess(args=cmd, returncode=0, stdout=diff_output, stderr="")

        engine = PolicyEngine({"max_file_lines": 100})
        with patch("superpower_workflow.policy.subprocess.run", side_effect=mock_run):
            files = engine._changed_files(tmp_path, base_sha="abc123")
        assert len(files) == 2
        assert files[0] == tmp_path / "src/foo.py"

    def test_changed_files_empty_when_no_base_sha(self, tmp_path):
        engine = PolicyEngine({})
        files = engine._changed_files(tmp_path, base_sha=None)
        assert files == []

    def test_changed_files_handles_git_failure(self, tmp_path):
        from subprocess import CompletedProcess
        from unittest.mock import patch

        def mock_run(cmd, **kwargs):
            return CompletedProcess(args=cmd, returncode=128, stdout="", stderr="fatal")

        engine = PolicyEngine({})
        with patch("superpower_workflow.policy.subprocess.run", side_effect=mock_run):
            files = engine._changed_files(tmp_path, base_sha="abc123")
        assert files == []

    def test_changed_files_handles_timeout(self, tmp_path):
        import subprocess as sp_mod
        from unittest.mock import patch

        def mock_run(cmd, **kwargs):
            raise sp_mod.TimeoutExpired(cmd=cmd, timeout=10)

        engine = PolicyEngine({})
        with patch("superpower_workflow.policy.subprocess.run", side_effect=mock_run):
            files = engine._changed_files(tmp_path, base_sha="abc123")
        assert files == []
