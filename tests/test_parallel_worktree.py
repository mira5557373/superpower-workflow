from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.parallel.worktree import (
    WorktreeManager,
)


def _success(stdout: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _failure(stderr: str = "error") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class TestWorktreeCreate:
    def test_creates_worktree_with_branch(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()):
            info = mgr.create("m1")
        assert info.name == "m1"
        assert info.branch == "sw-parallel/m1"
        assert info.path == tmp_path / ".worktrees" / "m1"

    def test_create_calls_git_worktree_add(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()
        ) as mock:
            mgr.create("m1", base_ref="main")
        cmd = mock.call_args[0][0]
        assert "worktree" in cmd
        assert "add" in cmd
        assert "-b" in cmd
        assert "sw-parallel/m1" in cmd
        assert "main" in cmd

    def test_create_custom_worktree_dir(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path, worktree_dir=tmp_path / "custom")
        with patch("superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()):
            info = mgr.create("m1")
        assert info.path == tmp_path / "custom" / "m1"

    def test_create_raises_on_git_failure(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with (
            patch(
                "superpower_workflow.parallel.worktree.subprocess.run",
                return_value=_failure("fatal: already exists"),
            ),
            pytest.raises(RuntimeError, match="already exists"),
        ):
            mgr.create("m1")


class TestWorktreeRemove:
    def test_remove_calls_git_worktree_remove(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()
        ) as mock:
            mgr.remove("m1")
        cmd = mock.call_args_list[0][0][0]
        assert "worktree" in cmd
        assert "remove" in cmd

    def test_remove_prunes_branch(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run", return_value=_success()
        ) as mock:
            mgr.remove("m1", prune_branch=True)
        calls = [c[0][0] for c in mock.call_args_list]
        branch_delete = [c for c in calls if "branch" in c and "-D" in c]
        assert len(branch_delete) == 1
        assert "sw-parallel/m1" in branch_delete[0]

    def test_remove_silent_on_missing(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_failure("not a working tree"),
        ):
            mgr.remove("nonexistent")


class TestWorktreeList:
    def test_list_parses_porcelain_output(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\n"
            "HEAD abc1234\n"
            "branch refs/heads/main\n"
            "\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\n"
            "HEAD def5678\n"
            "branch refs/heads/sw-parallel/m1\n"
            "\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert len(parallel_trees) == 1
        assert parallel_trees[0].name == "m1"
        assert parallel_trees[0].branch == "sw-parallel/m1"

    def test_list_empty_when_no_worktrees(self, tmp_path: Path):
        porcelain = f"worktree {tmp_path}\nHEAD abc1234\nbranch refs/heads/main\n\n"
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert parallel_trees == []

    def test_list_returns_all_parallel_worktrees(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\nHEAD a\nbranch refs/heads/main\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\nHEAD b\nbranch refs/heads/sw-parallel/m1\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm2'}\nHEAD c\nbranch refs/heads/sw-parallel/m2\n\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ):
            trees = mgr.list()
        parallel_trees = [t for t in trees if t.branch.startswith("sw-parallel/")]
        assert len(parallel_trees) == 2


class TestWorktreeCleanupAll:
    def test_cleanup_removes_all_parallel_worktrees(self, tmp_path: Path):
        porcelain = (
            f"worktree {tmp_path}\nHEAD a\nbranch refs/heads/main\n\n"
            f"worktree {tmp_path / '.worktrees' / 'm1'}\nHEAD b\nbranch refs/heads/sw-parallel/m1\n\n"
        )
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success(porcelain),
        ) as mock:
            mgr.cleanup_all()
        remove_calls = [c for c in mock.call_args_list if "remove" in c[0][0]]
        assert len(remove_calls) >= 1


class TestWorktreeMerge:
    def test_merge_success(self, tmp_path: Path):
        mgr = WorktreeManager(tmp_path)
        with patch(
            "superpower_workflow.parallel.worktree.subprocess.run",
            return_value=_success("Already up to date."),
        ):
            result = mgr.merge("m1")
        assert result.success is True
        assert result.merged_branch == "sw-parallel/m1"
        assert result.conflicts == []

    def test_merge_with_conflicts_aborts(self, tmp_path: Path):
        conflict_output = CompletedProcess(
            args=[],
            returncode=1,
            stdout="CONFLICT (content): Merge conflict in src/foo.py\n",
            stderr="Automatic merge failed; fix conflicts and then commit.\n",
        )
        mgr = WorktreeManager(tmp_path)
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            if "merge" in cmd and "--abort" not in cmd:
                return conflict_output
            return _success()

        with patch("superpower_workflow.parallel.worktree.subprocess.run", side_effect=mock_run):
            result = mgr.merge("m1")
        assert result.success is False
        assert len(result.conflicts) == 1
        assert "foo.py" in result.conflicts[0]
        abort_calls = [c for c in calls if "--abort" in c]
        assert len(abort_calls) == 1

    def test_merge_failure_message_preserved(self, tmp_path: Path):
        fail = CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="fatal: not something we can merge",
        )
        mgr = WorktreeManager(tmp_path)
        with patch("superpower_workflow.parallel.worktree.subprocess.run") as mock:
            mock.side_effect = [fail, _success()]
            result = mgr.merge("m1")
        assert result.success is False
        assert "not something we can merge" in result.message
