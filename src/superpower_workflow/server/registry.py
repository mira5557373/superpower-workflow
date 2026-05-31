from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


def get_default_registry_path() -> Path:
    return Path.home() / ".claude" / "sw-projects.json"


@dataclass
class ProjectEntry:
    name: str
    path: str
    added_at: str = ""

    def __post_init__(self) -> None:
        if not self.added_at:
            self.added_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path, "added_at": self.added_at}

    @classmethod
    def from_dict(cls, d: dict) -> ProjectEntry:
        return cls(name=d["name"], path=d["path"], added_at=d.get("added_at", ""))


class ProjectRegistry:
    """v1.3.5 #2 fix: register/remove are now atomic read-modify-write.

    Pre-fix: each public method called `_load`, mutated the list in
    Python, then `_save`. Two concurrent `sw init` (or `sw onboard`)
    invocations on different projects could both load the same baseline,
    each add their own entry, and one would overwrite the other —
    silently losing the first registration.

    Now: a process-level `threading.Lock` plus a `filelock.FileLock`
    around the file serialize register/remove across both threads and
    processes. The lock is acquired BEFORE _load so the read+write pair
    is one critical section.
    """

    _process_lock = None  # populated lazily; class-level so all instances share.

    def __init__(self, path: Path | None = None) -> None:
        import threading

        self._path = path or get_default_registry_path()
        # Class-level lock shared by every ProjectRegistry instance in
        # this process — they all manipulate the same on-disk file.
        if ProjectRegistry._process_lock is None:
            ProjectRegistry._process_lock = threading.Lock()

    def _load(self) -> list[ProjectEntry]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [ProjectEntry.from_dict(p) for p in data.get("projects", [])]
        except (json.JSONDecodeError, OSError, KeyError):
            return []

    def _save(self, entries: list[ProjectEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"projects": [e.to_dict() for e in entries]}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _file_lock(self):
        """Cross-process lock for serializing concurrent sw invocations."""
        from filelock import FileLock

        self._path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self._path) + ".filelock", timeout=30)

    def register(self, name: str, path: str) -> None:
        with ProjectRegistry._process_lock, self._file_lock():
            entries = [e for e in self._load() if e.name != name]
            entries.append(ProjectEntry(name=name, path=path))
            self._save(entries)

    def list_projects(self) -> list[ProjectEntry]:
        return self._load()

    def get_project(self, name: str) -> ProjectEntry | None:
        for e in self._load():
            if e.name == name:
                return e
        return None

    def remove(self, name: str) -> None:
        with ProjectRegistry._process_lock, self._file_lock():
            entries = [e for e in self._load() if e.name != name]
            self._save(entries)
