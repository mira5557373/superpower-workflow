from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class WorkflowLogger:
    def __init__(self, claude_dir: Path, run_id: str) -> None:
        self._path = claude_dir / f"workflow-{run_id}.log"
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115

    def log(self, event: str, **kwargs: object) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017
        parts = [f"[{ts}]", event]
        for k, v in kwargs.items():
            parts.append(f"{k}={v}")
        self._file.write(" ".join(parts) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
