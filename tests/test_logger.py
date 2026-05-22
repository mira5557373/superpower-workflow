from __future__ import annotations

import tempfile
from pathlib import Path

from superpower_workflow.logger import WorkflowLogger


def test_logger_creates_log_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        claude_dir = Path(tmpdir)
        run_id = "test-run-123"
        logger = WorkflowLogger(claude_dir, run_id)
        logger.close()

        log_file = claude_dir / f"workflow-{run_id}.log"
        assert log_file.exists()


def test_logger_writes_structured_lines() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        claude_dir = Path(tmpdir)
        logger = WorkflowLogger(claude_dir, "test-run")
        logger.log("start", task="init", version="1.0")
        logger.close()

        log_file = claude_dir / "workflow-test-run.log"
        content = log_file.read_text()

        assert "start" in content
        assert "task=init" in content
        assert "version=1.0" in content
        assert content.startswith("[")  # ISO timestamp


def test_logger_appends_multiple_entries() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        claude_dir = Path(tmpdir)
        logger = WorkflowLogger(claude_dir, "test-run")
        logger.log("event1", key1="value1")
        logger.log("event2", key2="value2")
        logger.log("event3", key3="value3")
        logger.close()

        log_file = claude_dir / "workflow-test-run.log"
        lines = log_file.read_text().strip().split("\n")

        assert len(lines) == 3
        assert "event1" in lines[0]
        assert "event2" in lines[1]
        assert "event3" in lines[2]
