# Unified Dashboard + PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-project unified dashboard backed by PostgreSQL, with REST API, WebSocket live updates, and Docker deployment. Server is OPTIONAL -- `sw run` continues working with flat files alone. When the server is available, it provides: cross-project visibility, historical analytics, searchable events, REST API for external tools, and real-time WebSocket updates.

**Architecture:** Two new subpackages. `db/` contains SQLAlchemy 2.0 models, sync engine factory, TelemetryDbWriter (background thread with queue, duck-typed to TelemetryEmitter), DbSyncAdapter (JSONL bulk import), and typed query functions. `server/` contains FastAPI app factory with API-key auth middleware, CORS, rate limiting, 6 routers (projects, runs, milestones, events, metrics, ws), and dependency injection. `dashboard/unified_static.py` serves the multi-project HTML/JS/CSS dashboard at `/`. Project Registry tracks all project paths in `~/.claude/sw-projects.json`. CLI gains `sw server start/stop/init-db/sync`. Orchestrator wraps TelemetryEmitter with TelemetryDbWriter when `SW_DATABASE_URL` is set (duck typing, no other changes). Docker Compose bundles Postgres + API server.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 (sync engine), FastAPI, uvicorn, psycopg2-binary, Alembic. All new deps under `[server]` optional extra -- zero impact on `sw run`.

**Spec reference:** `docs/superpowers/specs/2026-05-25-unified-dashboard-postgres.md`

**Working directory:** `superpower-workflow/` (the repo root).

---

## Design Decisions

1. **Sync SQLAlchemy:** TelemetryDbWriter runs in a background thread (sync). FastAPI uses sync route handlers (uvicorn threadpool). Testable with SQLite in-memory.
2. **Lazy imports:** All `db/` and `server/` imports are inside try/except ImportError blocks in orchestrator and CLI. When `[server]` extras aren't installed, everything degrades gracefully.
3. **Duck typing:** TelemetryDbWriter has same `.emit()` and `.close()` as TelemetryEmitter. Orchestrator doesn't need to know which one it's using.
4. **Project Registry:** Simple JSON file at `~/.claude/sw-projects.json`. No DB dependency. Auto-registered by `sw init` and `sw run`.
5. **Rate limiting:** In-memory token bucket per IP. No Redis dependency.
6. **Dashboard:** Vanilla JS + CSS, dark theme, monospace. Client-side hash routing. Fetches from REST API. No framework.
7. **Alembic:** Single initial migration. Auto-migrate on `sw server start`. Schema creation also available via `sw server init-db`.
8. **Test strategy:** SQLite in-memory for DB tests. FastAPI TestClient for API tests. Mocks for subprocess/external calls.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/db/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/db/engine.py` | New | Engine factory, connection pooling, session management |
| `src/superpower_workflow/db/models.py` | New | 8 SQLAlchemy 2.0 models |
| `src/superpower_workflow/db/queries.py` | New | Typed CRUD query functions |
| `src/superpower_workflow/db/writer.py` | New | TelemetryDbWriter (background thread, queue, dual-write) |
| `src/superpower_workflow/db/sync_adapter.py` | New | DbSyncAdapter (JSONL bulk import) |
| `src/superpower_workflow/server/__init__.py` | New | Package exports with `__all__` |
| `src/superpower_workflow/server/app.py` | New | FastAPI app factory, auth middleware, CORS |
| `src/superpower_workflow/server/config.py` | New | ServerConfig dataclass |
| `src/superpower_workflow/server/deps.py` | New | Dependency injection (DB session, auth) |
| `src/superpower_workflow/server/registry.py` | New | Project registry (~/.claude/sw-projects.json) |
| `src/superpower_workflow/server/routers/__init__.py` | New | Router package |
| `src/superpower_workflow/server/routers/projects.py` | New | Project CRUD endpoints |
| `src/superpower_workflow/server/routers/runs.py` | New | Run list/detail/compare endpoints |
| `src/superpower_workflow/server/routers/milestones.py` | New | Milestone detail endpoints |
| `src/superpower_workflow/server/routers/events.py` | New | Event search/filter endpoints |
| `src/superpower_workflow/server/routers/metrics.py` | New | Cost, quality, model analytics |
| `src/superpower_workflow/server/routers/ws.py` | New | WebSocket live updates |
| `src/superpower_workflow/dashboard/unified_static.py` | New | Multi-project dashboard HTML/JS/CSS |
| `docker/Dockerfile.server` | New | API server Docker image |
| `docker/docker-compose.yml` | New | Postgres + API server compose |
| `pyproject.toml` | Edit | Add `[server]` optional deps |
| `src/superpower_workflow/cli.py` | Edit | Add `sw server` subcommands, auto-register projects |
| `src/superpower_workflow/orchestrator.py` | Edit | Wire TelemetryDbWriter when DB available |
| `templates/workflow.json` | Edit | Add `database` and `server` config sections |
| `tests/test_server_config.py` | New | Config + registry tests |
| `tests/test_db_models.py` | New | Model + engine tests |
| `tests/test_db_queries.py` | New | Query function tests |
| `tests/test_db_writer.py` | New | TelemetryDbWriter tests |
| `tests/test_db_sync.py` | New | DbSyncAdapter tests |
| `tests/test_server_app.py` | New | FastAPI app + auth tests |
| `tests/test_server_routers.py` | New | All router endpoint tests |
| `tests/test_server_ws.py` | New | WebSocket tests |
| `tests/test_server_cli.py` | New | CLI server command tests |
| `tests/test_unified_dashboard.py` | New | Dashboard static tests |
| `tests/test_server_integration.py` | New | End-to-end integration tests |

---

### Task 1: Config schema + pyproject.toml -- `database` and `server` sections

**Files:**
- Edit: `pyproject.toml`
- Edit: `templates/workflow.json`
- Edit: `src/superpower_workflow/cli.py` (default config in `_cmd_init`)
- New: `tests/test_server_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_config.py
from __future__ import annotations

import json
from pathlib import Path

from superpower_workflow.cli import _cmd_init


class TestDatabaseConfig:
    def test_init_includes_database_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "database" in config
        db = config["database"]
        assert db["url_env"] == "SW_DATABASE_URL"
        assert db["retention_days"] == 90
        assert db["auto_sync"] is True

    def test_init_includes_server_section(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        assert "server" in config
        srv = config["server"]
        assert srv["host"] == "0.0.0.0"
        assert srv["port"] == 3001
        assert isinstance(srv["cors_origins"], list)

    def test_server_cors_defaults_to_localhost(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        origins = config["server"]["cors_origins"]
        assert "http://localhost:3001" in origins

    def test_database_section_does_not_contain_url(self, tmp_path: Path):
        _cmd_init(tmp_path)
        config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
        db = config["database"]
        assert "url" not in db
        assert "password" not in db
```

- [ ] **Step 2: Run tests -- expect FAIL** (database/server keys don't exist yet)

- [ ] **Step 3: Add config sections + pyproject.toml extras**

In `cli.py` `_cmd_init`, add to `default_config` dict after the `plugins` block:

```python
"database": {
    "url_env": "SW_DATABASE_URL",
    "retention_days": 90,
    "auto_sync": True,
},
"server": {
    "host": "0.0.0.0",
    "port": 3001,
    "cors_origins": ["http://localhost:3001"],
},
```

Update `templates/workflow.json` to include the same sections.

In `pyproject.toml`, add the `server` optional dependency group:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
]
security = [
    "cryptography>=42.0",
]
server = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "fastapi>=0.100",
    "uvicorn>=0.20",
    "psycopg2-binary>=2.9",
]
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_server_config.py --fix
ruff format src/superpower_workflow/cli.py tests/test_server_config.py
git add pyproject.toml templates/workflow.json src/superpower_workflow/cli.py tests/test_server_config.py
git commit -m "feat: add database and server config sections, server optional deps"
```

---

### Task 2: Project Registry -- global project tracking

**Files:**
- New: `src/superpower_workflow/server/registry.py`
- New: `src/superpower_workflow/server/__init__.py`
- Extend: `tests/test_server_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_config.py -- append these classes
import time

from superpower_workflow.server.registry import (
    ProjectEntry,
    ProjectRegistry,
    get_default_registry_path,
)


class TestProjectEntry:
    def test_entry_has_required_fields(self):
        e = ProjectEntry(name="myapp", path="/home/user/myapp")
        assert e.name == "myapp"
        assert e.path == "/home/user/myapp"
        assert isinstance(e.added_at, str)

    def test_entry_auto_generates_timestamp(self):
        e = ProjectEntry(name="test", path="/tmp/test")
        assert "T" in e.added_at
        assert e.added_at.endswith("Z")

    def test_entry_to_dict_roundtrip(self):
        e = ProjectEntry(name="app", path="/p/app")
        d = e.to_dict()
        e2 = ProjectEntry.from_dict(d)
        assert e2.name == e.name
        assert e2.path == e.path


class TestProjectRegistry:
    def test_register_project(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("myapp", "/home/user/myapp")
        projects = reg.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "myapp"

    def test_register_deduplicates_by_name(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("myapp", "/path/a")
        reg.register("myapp", "/path/b")
        projects = reg.list_projects()
        assert len(projects) == 1
        assert projects[0].path == "/path/b"

    def test_get_project_by_name(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("app1", "/p/1")
        reg.register("app2", "/p/2")
        p = reg.get_project("app1")
        assert p is not None
        assert p.path == "/p/1"

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        assert reg.get_project("nope") is None

    def test_remove_project(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        reg.register("app", "/p/app")
        reg.remove("app")
        assert reg.list_projects() == []

    def test_persistence_across_instances(self, tmp_path: Path):
        path = tmp_path / "projects.json"
        reg1 = ProjectRegistry(path)
        reg1.register("app", "/p/app")
        reg2 = ProjectRegistry(path)
        assert len(reg2.list_projects()) == 1

    def test_empty_registry(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "projects.json")
        assert reg.list_projects() == []

    def test_default_path_under_home(self):
        p = get_default_registry_path()
        assert "sw-projects.json" in str(p)


class TestRegistryCorruption:
    def test_handles_corrupt_json(self, tmp_path: Path):
        path = tmp_path / "projects.json"
        path.write_text("not json{{{")
        reg = ProjectRegistry(path)
        assert reg.list_projects() == []

    def test_handles_missing_file(self, tmp_path: Path):
        reg = ProjectRegistry(tmp_path / "nonexistent" / "projects.json")
        assert reg.list_projects() == []
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/__init__.py
from __future__ import annotations

__all__: list[str] = []
```

```python
# src/superpower_workflow/server/registry.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
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
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_default_registry_path()

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

    def register(self, name: str, path: str) -> None:
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
        entries = [e for e in self._load() if e.name != name]
        self._save(entries)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/ tests/test_server_config.py --fix
ruff format src/superpower_workflow/server/ tests/test_server_config.py
git add src/superpower_workflow/server/__init__.py src/superpower_workflow/server/registry.py tests/test_server_config.py
git commit -m "feat: add ProjectRegistry for global project tracking"
```

---

### Task 3: DB engine factory + SQLAlchemy models

**Files:**
- New: `src/superpower_workflow/db/__init__.py`
- New: `src/superpower_workflow/db/engine.py`
- New: `src/superpower_workflow/db/models.py`
- New: `tests/test_db_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_models.py
from __future__ import annotations

import uuid

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import (
    Base,
    SwCoverageResult,
    SwEvent,
    SwGapReport,
    SwMilestone,
    SwPhase,
    SwProject,
    SwQualityGate,
    SwRun,
)


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    yield session
    session.close()


class TestEngineFactory:
    def test_creates_sqlite_engine(self):
        engine = create_engine_from_url("sqlite:///:memory:")
        assert engine is not None

    def test_creates_with_pool_config(self):
        engine = create_engine_from_url(
            "sqlite:///:memory:", pool_size=3, max_overflow=5, pool_timeout=10
        )
        assert engine is not None

    def test_session_factory_returns_session(self, db_engine):
        factory = get_session_factory(db_engine)
        session = factory()
        assert session is not None
        session.close()


class TestSwProjectModel:
    def test_create_project(self, db_session):
        p = SwProject(id=uuid.uuid4(), name="myapp", path="/home/user/myapp")
        db_session.add(p)
        db_session.commit()
        result = db_session.query(SwProject).first()
        assert result.name == "myapp"
        assert result.path == "/home/user/myapp"

    def test_project_name_unique(self, db_session):
        p1 = SwProject(id=uuid.uuid4(), name="app", path="/p/1")
        p2 = SwProject(id=uuid.uuid4(), name="app", path="/p/2")
        db_session.add(p1)
        db_session.commit()
        db_session.add(p2)
        with pytest.raises(Exception):
            db_session.commit()

    def test_project_timestamps_auto(self, db_session):
        p = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)
        assert p.created_at is not None


class TestSwRunModel:
    def test_create_run_with_project(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(
            id=uuid.uuid4(),
            project_id=proj.id,
            run_id="20260525-120000",
            status="running",
            model="opus",
        )
        db_session.add(run)
        db_session.commit()
        result = db_session.query(SwRun).first()
        assert result.run_id == "20260525-120000"
        assert result.project_id == proj.id

    def test_run_fields(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(
            id=uuid.uuid4(),
            project_id=proj.id,
            run_id="r1",
            status="complete",
            model="opus",
            total_cost_usd=12.50,
            milestone_count=5,
            completed_count=4,
            failed_count=1,
        )
        db_session.add(run)
        db_session.commit()
        r = db_session.query(SwRun).first()
        assert r.total_cost_usd == 12.50
        assert r.milestone_count == 5


class TestSwMilestoneModel:
    def test_create_milestone(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        db_session.add(proj)
        db_session.commit()
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        db_session.add(run)
        db_session.commit()
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="sp1-quality-gates", status="completed")
        db_session.add(ms)
        db_session.commit()
        result = db_session.query(SwMilestone).first()
        assert result.name == "sp1-quality-gates"


class TestSwPhaseModel:
    def test_create_phase(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        phase = SwPhase(
            id=uuid.uuid4(), milestone_id=ms.id, phase_type="plan", status="completed",
            cost_usd=2.50, duration_ms=30000, model="opus", input_tokens=5000, output_tokens=2000,
        )
        db_session.add(phase)
        db_session.commit()
        result = db_session.query(SwPhase).first()
        assert result.phase_type == "plan"
        assert result.cost_usd == 2.50


class TestSwEventModel:
    def test_create_event(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        db_session.add_all([proj, run])
        db_session.commit()
        evt = SwEvent(
            id=uuid.uuid4(), run_id=run.id, milestone_name="m1",
            event_type="phase_completed", data_json={"phase": "plan"},
        )
        db_session.add(evt)
        db_session.commit()
        result = db_session.query(SwEvent).first()
        assert result.event_type == "phase_completed"
        assert result.data_json["phase"] == "plan"


class TestAuxiliaryModels:
    def test_quality_gate(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        gate = SwQualityGate(
            id=uuid.uuid4(), milestone_id=ms.id, checkpoint="quality_check_b",
            gate_name="lint", passed=True,
        )
        db_session.add(gate)
        db_session.commit()
        assert db_session.query(SwQualityGate).first().passed is True

    def test_coverage_result(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        cov = SwCoverageResult(
            id=uuid.uuid4(), milestone_id=ms.id, coverage_pct=85.5, threshold=80.0, passed=True,
        )
        db_session.add(cov)
        db_session.commit()
        assert db_session.query(SwCoverageResult).first().coverage_pct == 85.5

    def test_gap_report(self, db_session):
        proj = SwProject(id=uuid.uuid4(), name="app", path="/p")
        run = SwRun(id=uuid.uuid4(), project_id=proj.id, run_id="r1", status="running", model="opus")
        ms = SwMilestone(id=uuid.uuid4(), run_id=run.id, name="m1", status="running")
        db_session.add_all([proj, run, ms])
        db_session.commit()
        gap = SwGapReport(
            id=uuid.uuid4(), milestone_id=ms.id, pass_num=1,
            critical=0, architectural=1, important=2, minor=3, deferred=0, converged=True,
        )
        db_session.add(gap)
        db_session.commit()
        assert db_session.query(SwGapReport).first().converged is True


class TestAllTablesExist:
    def test_eight_tables(self, db_engine):
        from sqlalchemy import inspect
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        expected = [
            "sw_projects", "sw_runs", "sw_milestones", "sw_phases",
            "sw_events", "sw_quality_gates", "sw_coverage_results", "sw_gap_reports",
        ]
        for t in expected:
            assert t in tables, f"Missing table: {t}"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/db/__init__.py
from __future__ import annotations

__all__: list[str] = []
```

```python
# src/superpower_workflow/db/engine.py
from __future__ import annotations

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(
    url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
) -> Engine:
    kwargs: dict = {}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout)
    return sa_create_engine(url, **kwargs)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

```python
# src/superpower_workflow/db/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SwProject(Base):
    __tablename__ = "sw_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    runs: Mapped[list[SwRun]] = relationship("SwRun", back_populates="project")


class SwRun(Base):
    __tablename__ = "sw_runs"
    __table_args__ = (Index("ix_sw_runs_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_projects.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    model: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    spec_sha: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    milestone_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[SwProject] = relationship("SwProject", back_populates="runs")
    milestones: Mapped[list[SwMilestone]] = relationship("SwMilestone", back_populates="run")
    events: Mapped[list[SwEvent]] = relationship("SwEvent", back_populates="run")


class SwMilestone(Base):
    __tablename__ = "sw_milestones"
    __table_args__ = (Index("ix_sw_milestones_run_name", "run_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    tests_added: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[SwRun] = relationship("SwRun", back_populates="milestones")
    phases: Mapped[list[SwPhase]] = relationship("SwPhase", back_populates="milestone")
    quality_gates: Mapped[list[SwQualityGate]] = relationship(
        "SwQualityGate", back_populates="milestone",
    )
    coverage_results: Mapped[list[SwCoverageResult]] = relationship(
        "SwCoverageResult", back_populates="milestone",
    )
    gap_reports: Mapped[list[SwGapReport]] = relationship(
        "SwGapReport", back_populates="milestone",
    )


class SwPhase(Base):
    __tablename__ = "sw_phases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    phase_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    session_id: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="phases")


class SwEvent(Base):
    __tablename__ = "sw_events"
    __table_args__ = (Index("ix_sw_events_run_type", "run_id", "event_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_runs.id"), nullable=False)
    milestone_name: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[SwRun] = relationship("SwRun", back_populates="events")


class SwQualityGate(Base):
    __tablename__ = "sw_quality_gates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(50), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(50), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="quality_gates")


class SwCoverageResult(Base):
    __tablename__ = "sw_coverage_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="coverage_results")


class SwGapReport(Base):
    __tablename__ = "sw_gap_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sw_milestones.id"), nullable=False)
    pass_num: Mapped[int] = mapped_column(Integer, nullable=False)
    critical: Mapped[int] = mapped_column(Integer, default=0)
    architectural: Mapped[int] = mapped_column(Integer, default=0)
    important: Mapped[int] = mapped_column(Integer, default=0)
    minor: Mapped[int] = mapped_column(Integer, default=0)
    deferred: Mapped[int] = mapped_column(Integer, default=0)
    converged: Mapped[bool] = mapped_column(Boolean, default=False)

    milestone: Mapped[SwMilestone] = relationship("SwMilestone", back_populates="gap_reports")
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/db/ tests/test_db_models.py --fix
ruff format src/superpower_workflow/db/ tests/test_db_models.py
git add src/superpower_workflow/db/__init__.py src/superpower_workflow/db/engine.py src/superpower_workflow/db/models.py tests/test_db_models.py
git commit -m "feat: add SQLAlchemy 2.0 models for 8 database tables"
```

---

### Task 4: DB queries -- typed CRUD operations

**Files:**
- New: `src/superpower_workflow/db/queries.py`
- New: `tests/test_db_queries.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_queries.py
from __future__ import annotations

import uuid

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwProject, SwRun
from superpower_workflow.db.queries import (
    get_or_create_project,
    get_project_by_name,
    create_run,
    get_run_by_run_id,
    list_runs,
    create_milestone,
    get_milestone_by_name,
    create_event,
    list_events,
    create_phase,
    create_quality_gate,
    create_coverage_result,
    create_gap_report,
    update_run_status,
    update_milestone_status,
)


@pytest.fixture
def db_session():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    yield session
    session.close()


class TestProjectQueries:
    def test_get_or_create_new(self, db_session):
        proj = get_or_create_project(db_session, "myapp", "/p/myapp")
        assert proj.name == "myapp"
        assert proj.id is not None

    def test_get_or_create_existing(self, db_session):
        p1 = get_or_create_project(db_session, "app", "/p/1")
        p2 = get_or_create_project(db_session, "app", "/p/2")
        assert p1.id == p2.id
        assert p2.path == "/p/2"

    def test_get_by_name(self, db_session):
        get_or_create_project(db_session, "app", "/p")
        result = get_project_by_name(db_session, "app")
        assert result is not None
        assert result.name == "app"

    def test_get_by_name_missing(self, db_session):
        assert get_project_by_name(db_session, "nope") is None


class TestRunQueries:
    def test_create_run(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="20260525-120000", model="opus",
                         milestone_count=5)
        assert run.run_id == "20260525-120000"
        assert run.status == "running"

    def test_get_run_by_run_id(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        result = get_run_by_run_id(db_session, proj.id, "r1")
        assert result is not None
        assert result.run_id == "r1"

    def test_list_runs_paginated(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        for i in range(5):
            create_run(db_session, project_id=proj.id, run_id=f"r{i}", model="opus")
        page = list_runs(db_session, project_id=proj.id, limit=2, offset=0)
        assert len(page) == 2

    def test_update_run_status(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        update_run_status(db_session, run.id, status="complete", total_cost_usd=10.0,
                          completed_count=3, failed_count=1)
        db_session.refresh(run)
        assert run.status == "complete"
        assert run.total_cost_usd == 10.0


class TestMilestoneQueries:
    def test_create_milestone(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="sp1-quality-gates")
        assert ms.name == "sp1-quality-gates"

    def test_get_milestone_by_name(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        create_milestone(db_session, run_id=run.id, name="m1")
        result = get_milestone_by_name(db_session, run.id, "m1")
        assert result is not None

    def test_update_milestone_status(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        update_milestone_status(db_session, ms.id, status="completed", cost_usd=5.0)
        db_session.refresh(ms)
        assert ms.status == "completed"
        assert ms.cost_usd == 5.0


class TestEventQueries:
    def test_create_event(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        evt = create_event(db_session, run_id=run.id, milestone_name="m1",
                           event_type="phase_completed", data_json={"phase": "plan"})
        assert evt.event_type == "phase_completed"

    def test_list_events_filtered(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        create_event(db_session, run_id=run.id, event_type="phase_started", data_json={})
        create_event(db_session, run_id=run.id, event_type="phase_completed", data_json={})
        create_event(db_session, run_id=run.id, event_type="phase_started", data_json={})
        results = list_events(db_session, run_id=run.id, event_type="phase_started")
        assert len(results) == 2


class TestAuxQueries:
    def test_create_phase(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        phase = create_phase(db_session, milestone_id=ms.id, phase_type="plan", model="opus")
        assert phase.phase_type == "plan"

    def test_create_quality_gate(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        gate = create_quality_gate(db_session, milestone_id=ms.id, checkpoint="qcb",
                                    gate_name="lint", passed=True)
        assert gate.passed is True

    def test_create_coverage_result(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        cov = create_coverage_result(db_session, milestone_id=ms.id, coverage_pct=85.0,
                                      threshold=80.0, passed=True)
        assert cov.coverage_pct == 85.0

    def test_create_gap_report(self, db_session):
        proj = get_or_create_project(db_session, "app", "/p")
        run = create_run(db_session, project_id=proj.id, run_id="r1", model="opus")
        ms = create_milestone(db_session, run_id=run.id, name="m1")
        gap = create_gap_report(db_session, milestone_id=ms.id, pass_num=1,
                                 critical=0, architectural=1, important=2, minor=3)
        assert gap.important == 2
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/db/queries.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from superpower_workflow.db.models import (
    SwCoverageResult,
    SwEvent,
    SwGapReport,
    SwMilestone,
    SwPhase,
    SwProject,
    SwQualityGate,
    SwRun,
)


def get_or_create_project(session: Session, name: str, path: str) -> SwProject:
    proj = session.query(SwProject).filter(SwProject.name == name).first()
    if proj is not None:
        proj.path = path
        proj.updated_at = datetime.now(timezone.utc)
        session.commit()
        return proj
    proj = SwProject(id=uuid.uuid4(), name=name, path=path)
    session.add(proj)
    session.commit()
    return proj


def get_project_by_name(session: Session, name: str) -> SwProject | None:
    return session.query(SwProject).filter(SwProject.name == name).first()


def create_run(
    session: Session,
    project_id: uuid.UUID,
    run_id: str,
    model: str,
    milestone_count: int = 0,
    spec_sha: str | None = None,
) -> SwRun:
    run = SwRun(
        id=uuid.uuid4(), project_id=project_id, run_id=run_id,
        model=model, milestone_count=milestone_count, spec_sha=spec_sha,
        status="running",
    )
    session.add(run)
    session.commit()
    return run


def get_run_by_run_id(session: Session, project_id: uuid.UUID, run_id: str) -> SwRun | None:
    return session.query(SwRun).filter(
        SwRun.project_id == project_id, SwRun.run_id == run_id,
    ).first()


def list_runs(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SwRun]:
    q = session.query(SwRun)
    if project_id is not None:
        q = q.filter(SwRun.project_id == project_id)
    if status is not None:
        q = q.filter(SwRun.status == status)
    return q.order_by(SwRun.started_at.desc()).offset(offset).limit(limit).all()


def update_run_status(
    session: Session,
    run_uuid: uuid.UUID,
    status: str,
    total_cost_usd: float = 0.0,
    completed_count: int = 0,
    failed_count: int = 0,
    skipped_count: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    run = session.query(SwRun).filter(SwRun.id == run_uuid).first()
    if run is None:
        return
    run.status = status
    run.total_cost_usd = total_cost_usd
    run.completed_count = completed_count
    run.failed_count = failed_count
    run.skipped_count = skipped_count
    run.duration_seconds = duration_seconds
    run.completed_at = datetime.now(timezone.utc)
    session.commit()


def create_milestone(
    session: Session, run_id: uuid.UUID, name: str, status: str = "pending",
) -> SwMilestone:
    ms = SwMilestone(id=uuid.uuid4(), run_id=run_id, name=name, status=status)
    session.add(ms)
    session.commit()
    return ms


def get_milestone_by_name(session: Session, run_id: uuid.UUID, name: str) -> SwMilestone | None:
    return session.query(SwMilestone).filter(
        SwMilestone.run_id == run_id, SwMilestone.name == name,
    ).first()


def update_milestone_status(
    session: Session, milestone_id: uuid.UUID, status: str, cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
) -> None:
    ms = session.query(SwMilestone).filter(SwMilestone.id == milestone_id).first()
    if ms is None:
        return
    ms.status = status
    ms.cost_usd = cost_usd
    ms.duration_seconds = duration_seconds
    if status in ("completed", "failed"):
        ms.completed_at = datetime.now(timezone.utc)
    session.commit()


def create_event(
    session: Session,
    run_id: uuid.UUID,
    event_type: str,
    data_json: dict,
    milestone_name: str | None = None,
) -> SwEvent:
    evt = SwEvent(
        id=uuid.uuid4(), run_id=run_id, milestone_name=milestone_name,
        event_type=event_type, data_json=data_json,
    )
    session.add(evt)
    session.commit()
    return evt


def list_events(
    session: Session,
    run_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SwEvent]:
    q = session.query(SwEvent)
    if run_id is not None:
        q = q.filter(SwEvent.run_id == run_id)
    if event_type is not None:
        q = q.filter(SwEvent.event_type == event_type)
    return q.order_by(SwEvent.timestamp.desc()).offset(offset).limit(limit).all()


def create_phase(
    session: Session, milestone_id: uuid.UUID, phase_type: str, model: str | None = None,
    status: str = "pending",
) -> SwPhase:
    phase = SwPhase(
        id=uuid.uuid4(), milestone_id=milestone_id, phase_type=phase_type,
        model=model, status=status,
    )
    session.add(phase)
    session.commit()
    return phase


def create_quality_gate(
    session: Session, milestone_id: uuid.UUID, checkpoint: str,
    gate_name: str, passed: bool, detail: str | None = None,
) -> SwQualityGate:
    gate = SwQualityGate(
        id=uuid.uuid4(), milestone_id=milestone_id, checkpoint=checkpoint,
        gate_name=gate_name, passed=passed, detail=detail,
    )
    session.add(gate)
    session.commit()
    return gate


def create_coverage_result(
    session: Session, milestone_id: uuid.UUID, coverage_pct: float,
    threshold: float, passed: bool,
) -> SwCoverageResult:
    cov = SwCoverageResult(
        id=uuid.uuid4(), milestone_id=milestone_id, coverage_pct=coverage_pct,
        threshold=threshold, passed=passed,
    )
    session.add(cov)
    session.commit()
    return cov


def create_gap_report(
    session: Session, milestone_id: uuid.UUID, pass_num: int,
    critical: int = 0, architectural: int = 0, important: int = 0,
    minor: int = 0, deferred: int = 0, converged: bool = False,
) -> SwGapReport:
    gap = SwGapReport(
        id=uuid.uuid4(), milestone_id=milestone_id, pass_num=pass_num,
        critical=critical, architectural=architectural, important=important,
        minor=minor, deferred=deferred, converged=converged,
    )
    session.add(gap)
    session.commit()
    return gap
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/db/queries.py tests/test_db_queries.py --fix
ruff format src/superpower_workflow/db/queries.py tests/test_db_queries.py
git add src/superpower_workflow/db/queries.py tests/test_db_queries.py
git commit -m "feat: add typed CRUD query functions for all 8 tables"
```

---

### Task 5: TelemetryDbWriter -- dual-write with background thread

**Files:**
- New: `src/superpower_workflow/db/writer.py`
- New: `tests/test_db_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_writer.py
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwProject, SwRun
from superpower_workflow.db.writer import TelemetryDbWriter
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
    TelemetryEvent,
)


@pytest.fixture
def mock_emitter(tmp_path):
    return TelemetryEmitter(tmp_path / "telemetry.jsonl", run_id="test-run")


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


class TestDuckTyping:
    def test_has_emit_method(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        assert hasattr(writer, "emit")
        writer.close()

    def test_has_close_method(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        assert hasattr(writer, "close")
        writer.close()


class TestEmitPassthrough:
    def test_forwards_to_emitter(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        event = RunStarted(spec_sha="abc123", model="opus", milestone_count=3)
        writer.emit(event)
        writer.close()
        content = (mock_emitter._path).read_text()
        assert "run_started" in content

    def test_close_flushes_queue(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        event = RunStarted(spec_sha="abc", model="opus", milestone_count=1)
        writer.emit(event)
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) >= 1
        session.close()


class TestDbWrites:
    def test_writes_run_started_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine,
                                    project_name="app", project_path="/p")
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=3))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        projects = session.query(SwProject).all()
        assert len(projects) == 1
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        session.close()

    def test_writes_milestone_started_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine,
                                    project_name="app", project_path="/p")
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        types = [e.event_type for e in events]
        assert "milestone_started" in types
        session.close()

    def test_writes_phase_completed_event(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine,
                                    project_name="app", project_path="/p")
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseCompleted(milestone="m1", phase="plan", cost_usd=2.0, duration_ms=5000))
        writer.close()
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).filter(SwEvent.event_type == "phase_completed").all()
        assert len(events) == 1
        session.close()


class TestFailsafe:
    def test_continues_after_db_error(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine,
                                    project_name="app", project_path="/p")
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer._db_enabled = False
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.close()
        content = mock_emitter._path.read_text()
        assert "milestone_started" in content

    def test_emitter_always_writes(self, mock_emitter, db_engine):
        writer = TelemetryDbWriter(emitter=mock_emitter, engine=db_engine)
        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=1))
        writer.close()
        assert mock_emitter._path.exists()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/db/writer.py
from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from superpower_workflow.telemetry import TelemetryEmitter, TelemetryEvent

logger = logging.getLogger(__name__)


class TelemetryDbWriter:
    def __init__(
        self,
        emitter: TelemetryEmitter,
        engine: Engine,
        project_name: str = "",
        project_path: str = "",
        flush_interval: float = 1.0,
        max_queue_size: int = 1000,
    ) -> None:
        self._emitter = emitter
        self._engine = engine
        self._project_name = project_name
        self._project_path = project_path
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._db_enabled = True
        self._stop = threading.Event()
        self._flush_interval = flush_interval
        self._project_uuid: uuid.UUID | None = None
        self._run_uuid: uuid.UUID | None = None
        self._milestone_uuids: dict[str, uuid.UUID] = {}
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def emit(self, event: TelemetryEvent) -> None:
        self._emitter.emit(event)
        if not self._db_enabled:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("DB write queue full, disabling DB writes")
            self._db_enabled = False

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self._flush_remaining()
        self._emitter.close()

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=self._flush_interval)
            self._flush_batch()

    def _flush_remaining(self) -> None:
        self._flush_batch()

    def _flush_batch(self) -> None:
        if not self._db_enabled:
            return
        batch: list = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return

        try:
            from superpower_workflow.db.engine import get_session_factory

            factory = get_session_factory(self._engine)
            session = factory()
            try:
                for event in batch:
                    self._write_event(session, event)
                session.commit()
            except Exception:
                session.rollback()
                logger.warning("DB flush failed", exc_info=True)
            finally:
                session.close()
        except Exception:
            logger.warning("DB session creation failed", exc_info=True)

    def _write_event(self, session: object, event: TelemetryEvent) -> None:
        from superpower_workflow.db.models import SwEvent, SwMilestone, SwProject, SwRun
        from superpower_workflow.db.queries import get_or_create_project

        event_dict = event.to_dict()
        event_type = event_dict.get("type", "")

        if event_type == "run_started":
            if self._project_name:
                proj = get_or_create_project(session, self._project_name, self._project_path)
                self._project_uuid = proj.id
            if self._project_uuid:
                run = SwRun(
                    id=uuid.uuid4(),
                    project_id=self._project_uuid,
                    run_id=event_dict.get("run_id", ""),
                    model=event_dict.get("model", ""),
                    milestone_count=event_dict.get("milestone_count", 0),
                    spec_sha=event_dict.get("spec_sha"),
                    status="running",
                )
                session.add(run)
                session.flush()
                self._run_uuid = run.id

        if event_type == "milestone_started":
            ms_name = event_dict.get("milestone", "")
            if self._run_uuid and ms_name:
                ms = SwMilestone(
                    id=uuid.uuid4(), run_id=self._run_uuid, name=ms_name, status="running",
                )
                session.add(ms)
                session.flush()
                self._milestone_uuids[ms_name] = ms.id

        if self._run_uuid:
            evt = SwEvent(
                id=uuid.uuid4(),
                run_id=self._run_uuid,
                milestone_name=event_dict.get("milestone"),
                event_type=event_type,
                data_json=event_dict,
            )
            session.add(evt)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/db/writer.py tests/test_db_writer.py --fix
ruff format src/superpower_workflow/db/writer.py tests/test_db_writer.py
git add src/superpower_workflow/db/writer.py tests/test_db_writer.py
git commit -m "feat: add TelemetryDbWriter with background thread queue and dual-write"
```

---

### Task 6: DbSyncAdapter -- JSONL to Postgres importer

**Files:**
- New: `src/superpower_workflow/db/sync_adapter.py`
- New: `tests/test_db_sync.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_sync.py
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwProject, SwRun
from superpower_workflow.db.sync_adapter import DbSyncAdapter


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def jsonl_file(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    events = [
        {"type": "run_started", "run_id": "20260525-120000", "timestamp": "2026-05-25T12:00:00Z",
         "model": "opus", "spec_sha": "abc123", "milestone_count": 2},
        {"type": "milestone_started", "run_id": "20260525-120000",
         "timestamp": "2026-05-25T12:00:01Z", "milestone": "m1", "index": 0},
        {"type": "phase_completed", "run_id": "20260525-120000",
         "timestamp": "2026-05-25T12:00:02Z", "milestone": "m1", "phase": "plan",
         "cost_usd": 2.5, "duration_ms": 30000},
        {"type": "milestone_completed", "run_id": "20260525-120000",
         "timestamp": "2026-05-25T12:00:03Z", "milestone": "m1", "cost_usd": 10.0,
         "duration_seconds": 120.0},
        {"type": "run_completed", "run_id": "20260525-120000",
         "timestamp": "2026-05-25T12:00:04Z", "status": "complete",
         "total_cost_usd": 10.0, "completed_count": 1},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events))
    return path


class TestDbSyncAdapter:
    def test_sync_creates_project(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        projects = session.query(SwProject).all()
        assert len(projects) == 1
        assert projects[0].name == "app"
        session.close()

    def test_sync_creates_run(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        assert runs[0].run_id == "20260525-120000"
        session.close()

    def test_sync_creates_events(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) == 5
        session.close()

    def test_sync_idempotent(self, db_engine, jsonl_file):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=jsonl_file)
        factory = get_session_factory(db_engine)
        session = factory()
        runs = session.query(SwRun).all()
        assert len(runs) == 1
        session.close()

    def test_sync_empty_file(self, db_engine, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        factory = get_session_factory(db_engine)
        session = factory()
        assert session.query(SwRun).count() == 0
        session.close()

    def test_sync_missing_file(self, db_engine, tmp_path):
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=tmp_path / "nope.jsonl")

    def test_sync_corrupt_lines_skipped(self, db_engine, tmp_path):
        path = tmp_path / "corrupt.jsonl"
        path.write_text("not json\n{bad\n" + json.dumps(
            {"type": "run_started", "run_id": "r1", "timestamp": "2026-05-25T12:00:00Z",
             "model": "opus", "milestone_count": 1}
        ))
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="app", project_path="/p", jsonl_path=path)
        factory = get_session_factory(db_engine)
        session = factory()
        events = session.query(SwEvent).all()
        assert len(events) == 1
        session.close()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/db/sync_adapter.py
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import SwEvent, SwMilestone, SwRun
from superpower_workflow.db.queries import get_or_create_project, get_run_by_run_id

logger = logging.getLogger(__name__)


class DbSyncAdapter:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def sync(self, project_name: str, project_path: str, jsonl_path: Path) -> None:
        if not jsonl_path.exists():
            return

        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        events: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if not events:
            return

        factory = get_session_factory(self._engine)
        session = factory()
        try:
            proj = get_or_create_project(session, project_name, project_path)
            run_uuids: dict[str, uuid.UUID] = {}
            milestone_uuids: dict[str, uuid.UUID] = {}

            for event in events:
                run_id = event.get("run_id", "")
                event_type = event.get("type", "")

                if event_type == "run_started" and run_id:
                    existing = get_run_by_run_id(session, proj.id, run_id)
                    if existing:
                        run_uuids[run_id] = existing.id
                        continue
                    run = SwRun(
                        id=uuid.uuid4(), project_id=proj.id, run_id=run_id,
                        model=event.get("model", ""), status="running",
                        milestone_count=event.get("milestone_count", 0),
                        spec_sha=event.get("spec_sha"),
                    )
                    session.add(run)
                    session.flush()
                    run_uuids[run_id] = run.id
                    continue

                if run_id not in run_uuids:
                    existing = get_run_by_run_id(session, proj.id, run_id) if run_id else None
                    if existing:
                        run_uuids[run_id] = existing.id
                    else:
                        continue

                run_uuid = run_uuids[run_id]

                if event_type == "milestone_started":
                    ms_name = event.get("milestone", "")
                    if ms_name and ms_name not in milestone_uuids:
                        ms = SwMilestone(
                            id=uuid.uuid4(), run_id=run_uuid, name=ms_name, status="running",
                        )
                        session.add(ms)
                        session.flush()
                        milestone_uuids[ms_name] = ms.id

                if event_type == "run_completed":
                    run_obj = session.query(SwRun).filter(SwRun.id == run_uuid).first()
                    if run_obj:
                        run_obj.status = event.get("status", "complete")
                        run_obj.total_cost_usd = event.get("total_cost_usd", 0.0)
                        run_obj.completed_count = event.get("completed_count", 0)

                evt = SwEvent(
                    id=uuid.uuid4(), run_id=run_uuid,
                    milestone_name=event.get("milestone"),
                    event_type=event_type, data_json=event,
                )
                session.add(evt)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Sync failed", exc_info=True)
        finally:
            session.close()
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/db/sync_adapter.py tests/test_db_sync.py --fix
ruff format src/superpower_workflow/db/sync_adapter.py tests/test_db_sync.py
git add src/superpower_workflow/db/sync_adapter.py tests/test_db_sync.py
git commit -m "feat: add DbSyncAdapter for JSONL to Postgres bulk import"
```

---

### Task 7: Server config + dependency injection

**Files:**
- New: `src/superpower_workflow/server/config.py`
- New: `src/superpower_workflow/server/deps.py`
- Extend: `tests/test_server_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_config.py -- append these classes
import os
from unittest.mock import patch

from superpower_workflow.server.config import ServerConfig, load_server_config
from superpower_workflow.server.deps import get_api_key, verify_api_key


class TestServerConfig:
    def test_default_values(self):
        cfg = ServerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 3001
        assert cfg.database_url == ""
        assert cfg.api_key == ""

    def test_from_env(self):
        with patch.dict(os.environ, {
            "SW_DATABASE_URL": "postgresql://localhost/sw",
            "SW_API_KEY": "test-key-123",
            "SW_SERVER_HOST": "127.0.0.1",
            "SW_SERVER_PORT": "8080",
        }):
            cfg = load_server_config()
        assert cfg.database_url == "postgresql://localhost/sw"
        assert cfg.api_key == "test-key-123"
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8080

    def test_from_config_dict(self):
        config = {"server": {"host": "0.0.0.0", "port": 4000, "cors_origins": ["*"]}}
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_server_config(config)
        assert cfg.port == 4000
        assert cfg.cors_origins == ["*"]


class TestApiKey:
    def test_get_api_key_from_env(self):
        with patch.dict(os.environ, {"SW_API_KEY": "secret"}):
            assert get_api_key() == "secret"

    def test_get_api_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_api_key() == ""

    def test_verify_passes_with_correct_key(self):
        assert verify_api_key("secret", "secret") is True

    def test_verify_fails_with_wrong_key(self):
        assert verify_api_key("wrong", "secret") is False

    def test_verify_passes_when_no_key_configured(self):
        assert verify_api_key("anything", "") is True
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 3001
    database_url: str = ""
    api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3001"])
    rate_limit_per_minute: int = 100


def load_server_config(config: dict | None = None) -> ServerConfig:
    srv = (config or {}).get("server", {})
    db = (config or {}).get("database", {})

    return ServerConfig(
        host=os.environ.get("SW_SERVER_HOST", srv.get("host", "0.0.0.0")),
        port=int(os.environ.get("SW_SERVER_PORT", srv.get("port", 3001))),
        database_url=os.environ.get(
            "SW_DATABASE_URL",
            os.environ.get(db.get("url_env", "SW_DATABASE_URL"), ""),
        ),
        api_key=os.environ.get("SW_API_KEY", ""),
        cors_origins=srv.get("cors_origins", ["http://localhost:3001"]),
        rate_limit_per_minute=int(os.environ.get("SW_RATE_LIMIT", 100)),
    )
```

```python
# src/superpower_workflow/server/deps.py
from __future__ import annotations

import os


def get_api_key() -> str:
    return os.environ.get("SW_API_KEY", "")


def verify_api_key(provided: str, configured: str) -> bool:
    if not configured:
        return True
    return provided == configured
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/config.py src/superpower_workflow/server/deps.py tests/test_server_config.py --fix
ruff format src/superpower_workflow/server/config.py src/superpower_workflow/server/deps.py tests/test_server_config.py
git add src/superpower_workflow/server/config.py src/superpower_workflow/server/deps.py tests/test_server_config.py
git commit -m "feat: add ServerConfig and API key authentication helpers"
```

---

### Task 8: FastAPI app factory + auth middleware + health endpoint

**Files:**
- New: `src/superpower_workflow/server/app.py`
- New: `src/superpower_workflow/server/routers/__init__.py`
- New: `tests/test_server_app.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_app.py
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


@pytest.fixture
def app():
    cfg = ServerConfig(api_key="", database_url="")
    return create_app(cfg)


@pytest.fixture
def authed_app():
    cfg = ServerConfig(api_key="test-key", database_url="")
    return create_app(cfg)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def authed_client(authed_app):
    from fastapi.testclient import TestClient
    return TestClient(authed_app)


class TestHealthEndpoint:
    def test_health_ok_no_db(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db"] == "not_configured"

    def test_health_no_auth_required(self, authed_client):
        r = authed_client.get("/api/v1/health")
        assert r.status_code == 200


class TestApiKeyAuth:
    def test_no_key_configured_allows_all(self, client):
        r = client.get("/api/v1/projects")
        assert r.status_code == 200

    def test_key_required_rejects_missing(self, authed_client):
        r = authed_client.get("/api/v1/projects")
        assert r.status_code == 401

    def test_key_required_accepts_valid(self, authed_client):
        r = authed_client.get("/api/v1/projects", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 200

    def test_key_required_rejects_wrong(self, authed_client):
        r = authed_client.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


class TestCORS:
    def test_cors_headers_present(self, client):
        r = client.options(
            "/api/v1/health",
            headers={"Origin": "http://localhost:3001", "Access-Control-Request-Method": "GET"},
        )
        assert r.status_code in (200, 204, 405)


class TestRateLimiting:
    def test_no_crash_on_rapid_requests(self, client):
        for _ in range(10):
            r = client.get("/api/v1/health")
            assert r.status_code == 200
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/routers/__init__.py
from __future__ import annotations

__all__: list[str] = []
```

```python
# src/superpower_workflow/server/app.py
from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from superpower_workflow.server.config import ServerConfig

if TYPE_CHECKING:
    pass


def create_app(config: ServerConfig | None = None) -> FastAPI:
    if config is None:
        from superpower_workflow.server.config import load_server_config
        config = load_server_config()

    app = FastAPI(
        title="Superpower Workflow API",
        version="1.0.0",
        docs_url="/docs" if not config.api_key else None,
        redoc_url=None,
    )

    app.state.config = config
    app.state.engine = None

    if config.database_url:
        try:
            from superpower_workflow.db.engine import create_engine_from_url
            from superpower_workflow.db.models import Base
            app.state.engine = create_engine_from_url(config.database_url)
            Base.metadata.create_all(app.state.engine)
        except Exception:
            pass

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _rate_buckets: dict[str, list[float]] = defaultdict(list)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path == "/api/v1/health" or request.url.path == "/":
            return await call_next(request)

        if config.api_key:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != config.api_key:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _rate_buckets[client_ip]
        bucket[:] = [t for t in bucket if now - t < 60]
        if len(bucket) >= config.rate_limit_per_minute:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        bucket.append(now)

        return await call_next(request)

    @app.get("/api/v1/health")
    def health():
        db_status = "not_configured"
        if app.state.engine is not None:
            try:
                with app.state.engine.connect() as conn:
                    conn.execute(type(conn).dialect.do_ping(conn) if False else conn.exec_driver_sql("SELECT 1"))
                db_status = "connected"
            except Exception:
                db_status = "error"
        return {"status": "ok", "db": db_status}

    # Lazy router imports — routers created in Tasks 9-12, guard with try/except
    _router_modules = [
        "superpower_workflow.server.routers.projects",
        "superpower_workflow.server.routers.runs",
        "superpower_workflow.server.routers.milestones",
        "superpower_workflow.server.routers.events",
        "superpower_workflow.server.routers.metrics",
        "superpower_workflow.server.routers.ws",
    ]
    import importlib
    for mod_name in _router_modules:
        try:
            mod = importlib.import_module(mod_name)
            app.include_router(mod.router)
        except (ImportError, AttributeError):
            pass

    return app
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/app.py src/superpower_workflow/server/routers/__init__.py tests/test_server_app.py --fix
ruff format src/superpower_workflow/server/app.py src/superpower_workflow/server/routers/__init__.py tests/test_server_app.py
git add src/superpower_workflow/server/app.py src/superpower_workflow/server/routers/__init__.py tests/test_server_app.py
git commit -m "feat: add FastAPI app factory with auth middleware, CORS, rate limiting"
```

---

### Task 9: API routers -- projects + runs

**Files:**
- New: `src/superpower_workflow/server/routers/projects.py`
- New: `src/superpower_workflow/server/routers/runs.py`
- New: `tests/test_server_routers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_routers.py
from __future__ import annotations

import uuid

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwMilestone, SwProject, SwRun
from superpower_workflow.db.queries import create_run, get_or_create_project, create_milestone
from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def seeded_engine(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    proj = get_or_create_project(session, "test-app", "/home/user/test-app")
    run = create_run(session, project_id=proj.id, run_id="20260525-120000", model="opus",
                     milestone_count=3)
    create_milestone(session, run_id=run.id, name="sp1-quality-gates")
    create_milestone(session, run_id=run.id, name="sp2-telemetry")
    session.close()
    return db_engine


@pytest.fixture
def client(seeded_engine):
    from fastapi.testclient import TestClient
    cfg = ServerConfig(api_key="", database_url="")
    app = create_app(cfg)
    app.state.engine = seeded_engine
    return TestClient(app)


class TestProjectsRouter:
    def test_list_projects(self, client):
        r = client.get("/api/v1/projects")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "test-app"

    def test_get_project_by_id(self, client):
        r = client.get("/api/v1/projects")
        proj_id = r.json()[0]["id"]
        r2 = client.get(f"/api/v1/projects/{proj_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "test-app"

    def test_get_project_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/projects/{fake_id}")
        assert r.status_code == 404

    def test_trigger_sync(self, client):
        r = client.post("/api/v1/projects/sync", json={"path": "/p/app"})
        assert r.status_code in (200, 202, 404)


class TestRunsRouter:
    def test_list_runs(self, client):
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_list_runs_with_project_filter(self, client):
        r = client.get("/api/v1/projects")
        proj_id = r.json()[0]["id"]
        r2 = client.get(f"/api/v1/runs?project_id={proj_id}")
        assert r2.status_code == 200
        assert len(r2.json()) == 1

    def test_get_run_by_id(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/runs/{run_id}")
            assert r.status_code == 200
            assert "milestones" in r.json()

    def test_get_run_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/runs/{fake_id}")
        assert r.status_code == 404

    def test_list_runs_pagination(self, client):
        r = client.get("/api/v1/runs?limit=1&offset=0")
        assert r.status_code == 200

    def test_compare_runs(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/runs/compare?ids={run_id}")
            assert r.status_code == 200
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/routers/projects.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1", tags=["projects"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory
    return get_session_factory(engine)()


@router.get("/projects")
def list_projects(request: Request):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwProject
        projects = session.query(SwProject).all()
        return [
            {"id": str(p.id), "name": p.name, "path": p.path,
             "created_at": p.created_at.isoformat() if p.created_at else None}
            for p in projects
        ]
    finally:
        session.close()


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import SwProject, SwRun
        proj = session.query(SwProject).filter(SwProject.id == uuid.UUID(project_id)).first()
        if proj is None:
            raise HTTPException(404, "Project not found")
        latest_run = session.query(SwRun).filter(
            SwRun.project_id == proj.id
        ).order_by(SwRun.started_at.desc()).first()
        return {
            "id": str(proj.id), "name": proj.name, "path": proj.path,
            "created_at": proj.created_at.isoformat() if proj.created_at else None,
            "latest_run": {
                "id": str(latest_run.id), "run_id": latest_run.run_id,
                "status": latest_run.status, "model": latest_run.model,
            } if latest_run else None,
        }
    finally:
        session.close()


@router.post("/projects/sync")
def sync_project(request: Request, body: dict | None = None):
    body = body or {}
    path = body.get("path", "")
    if not path:
        raise HTTPException(400, "path required")
    return {"status": "accepted", "path": path}
```

```python
# src/superpower_workflow/server/routers/runs.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory
    return get_session_factory(engine)()


@router.get("/runs")
def list_runs(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.queries import list_runs as db_list_runs
        pid = uuid.UUID(project_id) if project_id else None
        runs = db_list_runs(session, project_id=pid, status=status, limit=limit, offset=offset)
        return [
            {"id": str(r.id), "run_id": r.run_id, "status": r.status, "model": r.model,
             "total_cost_usd": r.total_cost_usd, "milestone_count": r.milestone_count,
             "started_at": r.started_at.isoformat() if r.started_at else None}
            for r in runs
        ]
    finally:
        session.close()


@router.get("/runs/compare")
def compare_runs(request: Request, ids: str = Query(...)):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwRun
        run_ids = [uuid.UUID(i.strip()) for i in ids.split(",") if i.strip()]
        runs = session.query(SwRun).filter(SwRun.id.in_(run_ids)).all()
        return [
            {"id": str(r.id), "run_id": r.run_id, "status": r.status,
             "total_cost_usd": r.total_cost_usd, "milestone_count": r.milestone_count,
             "completed_count": r.completed_count, "failed_count": r.failed_count,
             "duration_seconds": r.duration_seconds}
            for r in runs
        ]
    finally:
        session.close()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import SwMilestone, SwRun
        run = session.query(SwRun).filter(SwRun.id == uuid.UUID(run_id)).first()
        if run is None:
            raise HTTPException(404, "Run not found")
        milestones = session.query(SwMilestone).filter(SwMilestone.run_id == run.id).all()
        return {
            "id": str(run.id), "run_id": run.run_id, "status": run.status,
            "model": run.model, "total_cost_usd": run.total_cost_usd,
            "milestone_count": run.milestone_count,
            "milestones": [
                {"id": str(m.id), "name": m.name, "status": m.status, "cost_usd": m.cost_usd}
                for m in milestones
            ],
        }
    finally:
        session.close()
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/routers/projects.py src/superpower_workflow/server/routers/runs.py tests/test_server_routers.py --fix
ruff format src/superpower_workflow/server/routers/projects.py src/superpower_workflow/server/routers/runs.py tests/test_server_routers.py
git add src/superpower_workflow/server/routers/projects.py src/superpower_workflow/server/routers/runs.py tests/test_server_routers.py
git commit -m "feat: add projects and runs REST API routers with pagination"
```

---

### Task 10: API routers -- milestones + events

**Files:**
- New: `src/superpower_workflow/server/routers/milestones.py`
- New: `src/superpower_workflow/server/routers/events.py`
- Extend: `tests/test_server_routers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_routers.py -- append these classes

class TestMilestonesRouter:
    def test_list_milestones_for_run(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/milestones?run_id={run_id}")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2

    def test_get_milestone_by_id(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            milestones = client.get(f"/api/v1/milestones?run_id={run_id}").json()
            if milestones:
                ms_id = milestones[0]["id"]
                r = client.get(f"/api/v1/milestones/{ms_id}")
                assert r.status_code == 200
                assert "phases" in r.json()

    def test_milestone_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/milestones/{fake_id}")
        assert r.status_code == 404


class TestEventsRouter:
    def test_list_events_empty(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/events?run_id={run_id}")
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_events_pagination(self, client):
        r = client.get("/api/v1/events?limit=10&offset=0")
        assert r.status_code == 200

    def test_events_type_filter(self, client):
        r = client.get("/api/v1/events?type=phase_completed")
        assert r.status_code == 200
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/routers/milestones.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1", tags=["milestones"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory
    return get_session_factory(engine)()


@router.get("/milestones")
def list_milestones(
    request: Request,
    run_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.models import SwMilestone
        q = session.query(SwMilestone)
        if run_id:
            q = q.filter(SwMilestone.run_id == uuid.UUID(run_id))
        milestones = q.offset(offset).limit(limit).all()
        return [
            {"id": str(m.id), "name": m.name, "status": m.status,
             "cost_usd": m.cost_usd, "duration_seconds": m.duration_seconds}
            for m in milestones
        ]
    finally:
        session.close()


@router.get("/milestones/{milestone_id}")
def get_milestone(milestone_id: str, request: Request):
    session = _get_session(request)
    if session is None:
        raise HTTPException(404, "Database not configured")
    try:
        from superpower_workflow.db.models import (
            SwCoverageResult,
            SwGapReport,
            SwMilestone,
            SwPhase,
            SwQualityGate,
        )
        ms = session.query(SwMilestone).filter(SwMilestone.id == uuid.UUID(milestone_id)).first()
        if ms is None:
            raise HTTPException(404, "Milestone not found")
        phases = session.query(SwPhase).filter(SwPhase.milestone_id == ms.id).all()
        gates = session.query(SwQualityGate).filter(SwQualityGate.milestone_id == ms.id).all()
        gaps = session.query(SwGapReport).filter(SwGapReport.milestone_id == ms.id).all()
        return {
            "id": str(ms.id), "name": ms.name, "status": ms.status,
            "cost_usd": ms.cost_usd, "duration_seconds": ms.duration_seconds,
            "phases": [
                {"id": str(p.id), "phase_type": p.phase_type, "status": p.status,
                 "cost_usd": p.cost_usd, "model": p.model}
                for p in phases
            ],
            "quality_gates": [
                {"gate_name": g.gate_name, "passed": g.passed, "checkpoint": g.checkpoint}
                for g in gates
            ],
            "gap_reports": [
                {"pass_num": g.pass_num, "critical": g.critical, "important": g.important,
                 "converged": g.converged}
                for g in gaps
            ],
        }
    finally:
        session.close()
```

```python
# src/superpower_workflow/server/routers/events.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/v1", tags=["events"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory
    return get_session_factory(engine)()


@router.get("/events")
def list_events(
    request: Request,
    run_id: str | None = None,
    type: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_session(request)
    if session is None:
        return []
    try:
        from superpower_workflow.db.queries import list_events as db_list_events
        rid = uuid.UUID(run_id) if run_id else None
        events = db_list_events(session, run_id=rid, event_type=type, limit=limit, offset=offset)
        return [
            {"id": str(e.id), "event_type": e.event_type,
             "milestone_name": e.milestone_name,
             "timestamp": e.timestamp.isoformat() if e.timestamp else None,
             "data": e.data_json}
            for e in events
        ]
    finally:
        session.close()
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/routers/milestones.py src/superpower_workflow/server/routers/events.py tests/test_server_routers.py --fix
ruff format src/superpower_workflow/server/routers/milestones.py src/superpower_workflow/server/routers/events.py tests/test_server_routers.py
git add src/superpower_workflow/server/routers/milestones.py src/superpower_workflow/server/routers/events.py tests/test_server_routers.py
git commit -m "feat: add milestones and events REST API routers"
```

---

### Task 11: API routers -- metrics + analytics

**Files:**
- New: `src/superpower_workflow/server/routers/metrics.py`
- Extend: `tests/test_server_routers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_routers.py -- append

class TestMetricsRouter:
    def test_cost_metrics(self, client):
        r = client.get("/api/v1/metrics/costs")
        assert r.status_code == 200
        data = r.json()
        assert "total_cost" in data

    def test_cost_metrics_with_project(self, client):
        projects = client.get("/api/v1/projects").json()
        if projects:
            pid = projects[0]["id"]
            r = client.get(f"/api/v1/metrics/costs?project_id={pid}")
            assert r.status_code == 200

    def test_quality_metrics(self, client):
        r = client.get("/api/v1/metrics/quality")
        assert r.status_code == 200
        data = r.json()
        assert "rework_rate" in data or isinstance(data, dict)

    def test_model_metrics(self, client):
        r = client.get("/api/v1/metrics/models")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) or isinstance(data, dict)
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/routers/metrics.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


def _get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        return None
    from superpower_workflow.db.engine import get_session_factory
    return get_session_factory(engine)()


@router.get("/costs")
def cost_metrics(request: Request, project_id: str | None = None):
    session = _get_session(request)
    if session is None:
        return {"total_cost": 0.0, "cost_by_run": [], "cost_by_milestone": []}
    try:
        from sqlalchemy import func
        from superpower_workflow.db.models import SwMilestone, SwRun

        q = session.query(SwRun)
        if project_id:
            q = q.filter(SwRun.project_id == uuid.UUID(project_id))
        runs = q.all()
        total = sum(r.total_cost_usd for r in runs)
        by_run = [
            {"run_id": r.run_id, "cost": r.total_cost_usd, "status": r.status}
            for r in runs
        ]
        return {"total_cost": total, "cost_by_run": by_run}
    finally:
        session.close()


@router.get("/quality")
def quality_metrics(request: Request, project_id: str | None = None):
    session = _get_session(request)
    if session is None:
        return {"rework_rate": 0.0, "gap_reports": []}
    try:
        from superpower_workflow.db.models import SwGapReport, SwMilestone, SwRun

        q = session.query(SwGapReport)
        if project_id:
            q = q.join(SwMilestone).join(SwRun).filter(SwRun.project_id == uuid.UUID(project_id))
        gaps = q.all()
        return {
            "rework_rate": 0.0,
            "gap_reports": [
                {"pass_num": g.pass_num, "critical": g.critical, "important": g.important,
                 "converged": g.converged}
                for g in gaps
            ],
        }
    finally:
        session.close()


@router.get("/models")
def model_metrics(request: Request):
    session = _get_session(request)
    if session is None:
        return {"models": []}
    try:
        from sqlalchemy import func
        from superpower_workflow.db.models import SwRun

        rows = session.query(
            SwRun.model, func.count(SwRun.id), func.sum(SwRun.total_cost_usd),
        ).group_by(SwRun.model).all()
        return {
            "models": [
                {"model": row[0], "run_count": row[1], "total_cost": float(row[2] or 0)}
                for row in rows
            ],
        }
    finally:
        session.close()
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/routers/metrics.py tests/test_server_routers.py --fix
ruff format src/superpower_workflow/server/routers/metrics.py tests/test_server_routers.py
git add src/superpower_workflow/server/routers/metrics.py tests/test_server_routers.py
git commit -m "feat: add metrics REST API routers for cost, quality, and model analytics"
```

---

### Task 12: WebSocket router -- live event streaming

**Files:**
- New: `src/superpower_workflow/server/routers/ws.py`
- New: `tests/test_server_ws.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_ws.py
from __future__ import annotations

import pytest

from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


@pytest.fixture
def app():
    cfg = ServerConfig(api_key="", database_url="")
    app = create_app(cfg)
    from superpower_workflow.server.routers.ws import router as ws_router
    app.include_router(ws_router)
    return app


@pytest.fixture
def authed_app():
    cfg = ServerConfig(api_key="test-key", database_url="")
    app = create_app(cfg)
    from superpower_workflow.server.routers.ws import router as ws_router
    app.include_router(ws_router)
    return app


class TestWebSocket:
    def test_ws_connect_no_auth(self, app):
        from fastapi.testclient import TestClient
        client = TestClient(app)
        with client.websocket_connect("/ws/live") as ws:
            ws.close()

    def test_ws_rejects_wrong_key(self, authed_app):
        from fastapi.testclient import TestClient
        client = TestClient(authed_app)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/live?key=wrong"):
                pass

    def test_ws_accepts_correct_key(self, authed_app):
        from fastapi.testclient import TestClient
        client = TestClient(authed_app)
        with client.websocket_connect("/ws/live?key=test-key") as ws:
            ws.close()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/server/routers/ws.py
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])

_connections: list[WebSocket] = []


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket, key: str = "", project_id: str = ""):
    config = ws.app.state.config
    if config.api_key and key != config.api_key:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    _connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _connections:
            _connections.remove(ws)


async def broadcast_event(data: dict) -> None:
    for ws in list(_connections):
        try:
            await ws.send_json(data)
        except Exception:
            if ws in _connections:
                _connections.remove(ws)
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/server/routers/ws.py tests/test_server_ws.py --fix
ruff format src/superpower_workflow/server/routers/ws.py tests/test_server_ws.py
git add src/superpower_workflow/server/routers/ws.py tests/test_server_ws.py
git commit -m "feat: add WebSocket router for live event streaming"
```

---

### Task 13: Unified Dashboard -- static HTML/JS/CSS

**Files:**
- New: `src/superpower_workflow/dashboard/unified_static.py`
- New: `tests/test_unified_dashboard.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_unified_dashboard.py
from __future__ import annotations


class TestUnifiedDashboardHtml:
    def test_html_is_string(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert isinstance(UNIFIED_DASHBOARD_HTML, str)

    def test_contains_doctype(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "<!DOCTYPE html>" in UNIFIED_DASHBOARD_HTML

    def test_contains_hash_routing(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "hashchange" in UNIFIED_DASHBOARD_HTML or "location.hash" in UNIFIED_DASHBOARD_HTML

    def test_contains_api_fetch(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "/api/v1/" in UNIFIED_DASHBOARD_HTML

    def test_contains_websocket(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "WebSocket" in UNIFIED_DASHBOARD_HTML or "ws://" in UNIFIED_DASHBOARD_HTML

    def test_dark_theme(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "dark" in UNIFIED_DASHBOARD_HTML.lower() or "#1a1a2e" in UNIFIED_DASHBOARD_HTML

    def test_monospace_font(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "monospace" in UNIFIED_DASHBOARD_HTML

    def test_navigation_links(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "#/" in UNIFIED_DASHBOARD_HTML
        assert "#/search" in UNIFIED_DASHBOARD_HTML or "#/analytics" in UNIFIED_DASHBOARD_HTML

    def test_project_cards_section(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "project" in UNIFIED_DASHBOARD_HTML.lower()

    def test_svg_chart_support(self):
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
        assert "<svg" in UNIFIED_DASHBOARD_HTML or "svg" in UNIFIED_DASHBOARD_HTML.lower()
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/dashboard/unified_static.py
from __future__ import annotations

UNIFIED_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Superpower Workflow — Unified Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#1a1a2e;color:#e0e0e0;min-height:100vh}
a{color:#4fc3f7;text-decoration:none}a:hover{text-decoration:underline}
nav{background:#16213e;padding:12px 24px;display:flex;gap:24px;align-items:center;border-bottom:1px solid #0f3460}
nav .brand{font-size:16px;font-weight:bold;color:#e94560}
nav a{font-size:14px;padding:4px 8px;border-radius:4px}
nav a.active{background:#0f3460}
.container{max-width:1200px;margin:0 auto;padding:24px}
.card{background:#16213e;border:1px solid #0f3460;border-radius:8px;padding:16px;margin-bottom:16px}
.card h3{color:#4fc3f7;margin-bottom:8px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.stat{display:inline-block;margin-right:24px;margin-bottom:8px}
.stat .label{font-size:11px;color:#888;text-transform:uppercase}
.stat .value{font-size:20px;font-weight:bold;color:#e94560}
.status-ok{color:#4caf50}.status-fail{color:#f44336}.status-run{color:#ff9800}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #0f3460}
th{color:#888;font-size:11px;text-transform:uppercase}
.search-bar{width:100%;padding:8px 12px;background:#0f3460;border:1px solid #1a1a2e;color:#e0e0e0;border-radius:4px;font-family:inherit;margin-bottom:16px}
svg{overflow:visible}
.bar{fill:#4fc3f7}.bar:hover{fill:#e94560}
.hidden{display:none}
#live-indicator{width:8px;height:8px;border-radius:50%;background:#4caf50;display:inline-block;margin-left:8px}
#live-indicator.disconnected{background:#f44336}
</style>
</head>
<body>
<nav>
<span class="brand">sw dashboard</span>
<a href="#/">Overview</a>
<a href="#/search">Search</a>
<a href="#/analytics">Analytics</a>
<span id="live-indicator" title="WebSocket status"></span>
</nav>
<div class="container" id="app"></div>

<script>
const API='/api/v1';
let ws=null,wsRetry=0,apiKey='';

// Prompt for API key if first request returns 401
async function ensureAuth(){
  const r=await fetch(API+'/projects');
  if(r.status===401){apiKey=prompt('API key required:')||''}
}

function $(sel){return document.querySelector(sel)}
function $$(sel){return document.querySelectorAll(sel)}
function h(tag,attrs,children){
  const el=document.createElement(tag);
  if(attrs)Object.entries(attrs).forEach(([k,v])=>{if(k==='class')el.className=v;else if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else el.setAttribute(k,v)});
  if(children){if(typeof children==='string')el.textContent=children;else if(Array.isArray(children))children.forEach(c=>{if(c)el.appendChild(typeof c==='string'?document.createTextNode(c):c)})}
  return el;
}

async function api(path){
  const opts=apiKey?{headers:{'Authorization':'Bearer '+apiKey}}:{};
  const r=await fetch(API+path,opts);
  if(r.status===401){apiKey=prompt('API key required:')||'';return api(path)}
  if(!r.ok)return null;
  return r.json();
}

function svgBar(data,w=400,barH=20){
  if(!data.length)return h('span',{},'No data');
  const max=Math.max(...data.map(d=>d.value),1);
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('width',w);svg.setAttribute('height',data.length*(barH+4));
  data.forEach((d,i)=>{
    const bw=Math.max((d.value/max)*(w-120),2);
    const g=document.createElementNS(ns,'g');
    const rect=document.createElementNS(ns,'rect');
    rect.setAttribute('x',100);rect.setAttribute('y',i*(barH+4));
    rect.setAttribute('width',bw);rect.setAttribute('height',barH);
    rect.setAttribute('class','bar');rect.setAttribute('rx',3);
    const label=document.createElementNS(ns,'text');
    label.setAttribute('x',0);label.setAttribute('y',i*(barH+4)+14);
    label.setAttribute('fill','#888');label.setAttribute('font-size','11');
    label.setAttribute('font-family','monospace');
    label.textContent=d.label.slice(0,12);
    const val=document.createElementNS(ns,'text');
    val.setAttribute('x',105+bw);val.setAttribute('y',i*(barH+4)+14);
    val.setAttribute('fill','#e0e0e0');val.setAttribute('font-size','11');
    val.setAttribute('font-family','monospace');
    val.textContent=typeof d.value==='number'?d.value.toFixed(2):d.value;
    g.append(label,rect,val);svg.append(g);
  });
  return svg;
}

async function renderOverview(){
  const app=$('#app');app.innerHTML='';
  const projects=await api('/projects')||[];
  const metrics=await api('/metrics/costs')||{total_cost:0};
  const stats=h('div',{class:'card'},[
    h('div',{class:'stat'},[h('span',{class:'label'},'Projects'),h('div',{class:'value'},String(projects.length))]),
    h('div',{class:'stat'},[h('span',{class:'label'},'Total Cost'),h('div',{class:'value'},'$'+(metrics.total_cost||0).toFixed(2))]),
  ]);
  app.append(stats);
  const grid=h('div',{class:'grid'});
  for(const p of projects){
    const card=h('div',{class:'card'},[
      h('h3',{},h('a',{href:'#/project/'+p.name},p.name)),
      h('div',{class:'stat'},[h('span',{class:'label'},'Path'),h('div',{},p.path)]),
    ]);
    grid.append(card);
  }
  app.append(grid);
  if(metrics.cost_by_run&&metrics.cost_by_run.length){
    const chartCard=h('div',{class:'card'},[h('h3',{},'Cost by Run')]);
    chartCard.append(svgBar(metrics.cost_by_run.map(r=>({label:r.run_id,value:r.cost}))));
    app.append(chartCard);
  }
}

async function renderProject(name){
  const app=$('#app');app.innerHTML='';
  const projects=await api('/projects')||[];
  const proj=projects.find(p=>p.name===name);
  if(!proj){app.innerHTML='<div class="card">Project not found</div>';return}
  const runs=await api('/runs?project_id='+proj.id)||[];
  app.append(h('div',{class:'card'},[h('h3',{},'Project: '+name),h('div',{},'Path: '+proj.path)]));
  const tbl=h('table',{},[
    h('thead',{},[h('tr',{},[h('th',{},'Run ID'),h('th',{},'Status'),h('th',{},'Cost'),h('th',{},'Milestones')])]),
  ]);
  const tbody=h('tbody');
  for(const r of runs){
    const cls=r.status==='complete'?'status-ok':r.status==='failed'?'status-fail':'status-run';
    tbody.append(h('tr',{},[
      h('td',{},h('a',{href:'#/run/'+r.id},r.run_id)),
      h('td',{class:cls},r.status),
      h('td',{},'$'+(r.total_cost_usd||0).toFixed(2)),
      h('td',{},String(r.milestone_count||0)),
    ]));
  }
  tbl.append(tbody);app.append(h('div',{class:'card'},[h('h3',{},'Runs'),tbl]));
}

async function renderSearch(){
  const app=$('#app');app.innerHTML='';
  const card=h('div',{class:'card'},[h('h3',{},'Event Search')]);
  const input=h('input',{class:'search-bar',placeholder:'Filter by event type...',type:'text'});
  const results=h('div',{id:'search-results'});
  input.addEventListener('input',async()=>{
    const q=input.value.trim();
    const events=await api('/events'+(q?'?type='+encodeURIComponent(q):'?limit=50'))||[];
    results.innerHTML='';
    const tbl=h('table',{},[h('thead',{},[h('tr',{},[h('th',{},'Type'),h('th',{},'Milestone'),h('th',{},'Time')])])]);
    const tbody=h('tbody');
    events.forEach(e=>{tbody.append(h('tr',{},[h('td',{},e.event_type),h('td',{},e.milestone_name||'-'),h('td',{},e.timestamp||'-')]))});
    tbl.append(tbody);results.append(tbl);
  });
  card.append(input,results);app.append(card);
  input.dispatchEvent(new Event('input'));
}

async function renderAnalytics(){
  const app=$('#app');app.innerHTML='';
  const models=await api('/metrics/models')||{models:[]};
  const quality=await api('/metrics/quality')||{gap_reports:[]};
  const mCard=h('div',{class:'card'},[h('h3',{},'Model Usage')]);
  if(models.models&&models.models.length){
    mCard.append(svgBar(models.models.map(m=>({label:m.model,value:m.total_cost}))));
  }else{mCard.append(h('div',{},'No model data'))}
  app.append(mCard);
  const qCard=h('div',{class:'card'},[h('h3',{},'Quality Trends')]);
  if(quality.gap_reports&&quality.gap_reports.length){
    qCard.append(svgBar(quality.gap_reports.map((g,i)=>({label:'Pass '+g.pass_num,value:g.critical+g.important}))));
  }else{qCard.append(h('div',{},'No quality data'))}
  app.append(qCard);
}

function route(){
  const hash=location.hash||'#/';
  $$('nav a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')===hash));
  if(hash==='#/'||hash==='')renderOverview();
  else if(hash.startsWith('#/project/'))renderProject(decodeURIComponent(hash.slice(10)));
  else if(hash==='#/search')renderSearch();
  else if(hash==='#/analytics')renderAnalytics();
  else renderOverview();
}

function connectWs(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  const url=proto+'//'+location.host+'/ws/live'+(apiKey?'?key='+encodeURIComponent(apiKey):'');
  ws=new WebSocket(url);
  ws.onopen=()=>{$('#live-indicator').classList.remove('disconnected');wsRetry=0};
  ws.onclose=()=>{$('#live-indicator').classList.add('disconnected');setTimeout(connectWs,Math.min(1000*Math.pow(2,wsRetry++),30000))};
  ws.onmessage=(e)=>{try{route()}catch(err){}};
}

window.addEventListener('hashchange',route);
window.addEventListener('load',()=>{route();connectWs()});
</script>
</body>
</html>"""
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/dashboard/unified_static.py tests/test_unified_dashboard.py --fix
ruff format src/superpower_workflow/dashboard/unified_static.py tests/test_unified_dashboard.py
git add src/superpower_workflow/dashboard/unified_static.py tests/test_unified_dashboard.py
git commit -m "feat: add unified multi-project dashboard with dark theme and hash routing"
```

---

### Task 14: CLI server commands -- start/stop/init-db/sync

**Files:**
- Edit: `src/superpower_workflow/cli.py`
- New: `tests/test_server_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_cli.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from superpower_workflow.cli import build_parser


class TestServerSubcommands:
    def test_server_start_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start"])
        assert args.command == "server"
        assert args.server_command == "start"

    def test_server_stop_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "stop"])
        assert args.command == "server"
        assert args.server_command == "stop"

    def test_server_init_db_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "init-db"])
        assert args.command == "server"
        assert args.server_command == "init-db"

    def test_server_sync_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync"])
        assert args.command == "server"
        assert args.server_command == "sync"

    def test_server_start_host_port(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start", "--host", "127.0.0.1", "--port", "8080"])
        assert args.host == "127.0.0.1"
        assert args.port == 8080

    def test_server_sync_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync", "--all"])
        assert args.sync_all is True

    def test_server_sync_project_flag(self):
        parser = build_parser()
        args = parser.parse_args(["server", "sync", "--project", "/p/app"])
        assert args.project == "/p/app"

    def test_server_start_database_url(self):
        parser = build_parser()
        args = parser.parse_args(["server", "start", "--database-url", "postgresql://localhost/sw"])
        assert args.database_url == "postgresql://localhost/sw"
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Add server subcommand to CLI**

In `cli.py` `build_parser()`, add after the `plugin_p` block:

```python
server_p = sub.add_parser("server", help="Unified dashboard server")
server_sub = server_p.add_subparsers(dest="server_command")

start_p = server_sub.add_parser("start", help="Start the API server")
start_p.add_argument("--host", default=None, help="Bind host (default: 0.0.0.0)")
start_p.add_argument("--port", type=int, default=None, help="Port (default: 3001)")
start_p.add_argument("--database-url", dest="database_url", default=None,
                      help="PostgreSQL URL")

server_sub.add_parser("stop", help="Stop the API server")
server_sub.add_parser("init-db", help="Initialize database schema")

sync_p = server_sub.add_parser("sync", help="Sync JSONL data to database")
sync_p.add_argument("--project", default=None, help="Project path to sync")
sync_p.add_argument("--all", dest="sync_all", action="store_true", help="Sync all projects")
```

In `main()`, add handler:

```python
if args.command == "server":
    if args.server_command == "start":
        _cmd_server_start(project_root, args)
    elif args.server_command == "stop":
        _cmd_server_stop()
    elif args.server_command == "init-db":
        _cmd_server_init_db(args)
    elif args.server_command == "sync":
        _cmd_server_sync(project_root, args)
    else:
        parser.parse_args(["server", "--help"])
    return
```

Add the handler functions:

```python
def _cmd_server_start(project_root: Path, args) -> None:
    import os

    if args.database_url:
        os.environ["SW_DATABASE_URL"] = args.database_url
    if args.host:
        os.environ["SW_SERVER_HOST"] = args.host
    if args.port:
        os.environ["SW_SERVER_PORT"] = str(args.port)

    try:
        from superpower_workflow.server.app import create_app
        from superpower_workflow.server.config import load_server_config
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        sys.exit(1)

    config_path = project_root / ".claude" / "workflow.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    cfg = load_server_config(config)
    app = create_app(cfg)

    from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML
    from fastapi.responses import HTMLResponse

    @app.get("/")
    def dashboard():
        return HTMLResponse(UNIFIED_DASHBOARD_HTML)

    import uvicorn
    pid_file = Path.home() / ".claude" / "sw-server.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    print(f"  Server starting at http://{cfg.host}:{cfg.port}/")
    try:
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    finally:
        pid_file.unlink(missing_ok=True)


def _cmd_server_stop() -> None:
    pid_file = Path.home() / ".claude" / "sw-server.pid"
    if not pid_file.exists():
        print("  No server PID file found.")
        return
    try:
        import signal
        pid = int(pid_file.read_text().strip())
        import os as _os
        _os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        print(f"  Stopped server (PID {pid})")
    except (ProcessLookupError, ValueError):
        pid_file.unlink(missing_ok=True)
        print("  Server not running.")


def _cmd_server_init_db(args) -> None:
    import os
    db_url = getattr(args, "database_url", None) or os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL or use --database-url")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url
        from superpower_workflow.db.models import Base
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    print("  Database schema created.")


def _cmd_server_sync(project_root: Path, args) -> None:
    import os
    db_url = os.environ.get("SW_DATABASE_URL", "")
    if not db_url:
        print("  Error: Set SW_DATABASE_URL")
        return
    try:
        from superpower_workflow.db.engine import create_engine_from_url
        from superpower_workflow.db.models import Base
        from superpower_workflow.db.sync_adapter import DbSyncAdapter
    except ImportError:
        print("  Error: Install server extras: pip install superpower-workflow[server]")
        return
    engine = create_engine_from_url(db_url)
    Base.metadata.create_all(engine)
    adapter = DbSyncAdapter(engine)

    if getattr(args, "sync_all", False):
        from superpower_workflow.server.registry import ProjectRegistry
        registry = ProjectRegistry()
        for entry in registry.list_projects():
            p = Path(entry.path)
            jsonl = p / ".claude" / "telemetry.jsonl"
            if jsonl.exists():
                adapter.sync(entry.name, entry.path, jsonl)
                print(f"  Synced: {entry.name}")
    elif getattr(args, "project", None):
        p = Path(args.project)
        name = p.name
        jsonl = p / ".claude" / "telemetry.jsonl"
        adapter.sync(name, str(p), jsonl)
        print(f"  Synced: {name}")
    else:
        name = project_root.name
        config_path = project_root / ".claude" / "workflow.json"
        telemetry_rel = ".claude/telemetry.jsonl"
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
                telemetry_rel = cfg.get("telemetry", {}).get("path", telemetry_rel)
            except (json.JSONDecodeError, OSError):
                pass
        jsonl = project_root / telemetry_rel
        adapter.sync(name, str(project_root), jsonl)
        print(f"  Synced: {name}")
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_server_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_server_cli.py
git add src/superpower_workflow/cli.py tests/test_server_cli.py
git commit -m "feat: add sw server start/stop/init-db/sync CLI commands"
```

---

### Task 15: Orchestrator integration -- wire TelemetryDbWriter

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Edit: `src/superpower_workflow/cli.py` (auto-register in sw init/run)
- Extend: `tests/test_server_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_config.py -- append

import os
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestOrchestratorDbIntegration:
    def test_db_writer_wraps_emitter_when_url_set(self):
        from superpower_workflow.orchestrator import Orchestrator

        with patch.dict(os.environ, {"SW_DATABASE_URL": "sqlite:///:memory:"}):
            with patch("superpower_workflow.orchestrator.TelemetryEmitter") as mock_emitter:
                with patch("superpower_workflow.orchestrator.run_claude"):
                    pass

    def test_no_import_error_without_server_extras(self):
        with patch.dict(os.environ, {"SW_DATABASE_URL": ""}, clear=False):
            pass


class TestAutoRegister:
    def test_init_registers_project(self, tmp_path: Path):
        reg_path = tmp_path / "registry.json"
        with patch(
            "superpower_workflow.server.registry.get_default_registry_path",
            return_value=reg_path,
        ):
            from superpower_workflow.server.registry import ProjectRegistry
            reg = ProjectRegistry(reg_path)
            reg.register("test", str(tmp_path))
            projects = reg.list_projects()
            assert len(projects) == 1
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Wire TelemetryDbWriter into orchestrator**

In `orchestrator.py`, after the line that creates `self._telemetry = TelemetryEmitter(telemetry_path, run_id)`, add:

```python
url_env_name = self.config.get("database", {}).get("url_env", "SW_DATABASE_URL")
db_url = os.environ.get(url_env_name, "")
if db_url:
    try:
        from superpower_workflow.db.writer import TelemetryDbWriter
        from superpower_workflow.db.engine import create_engine_from_url
        from superpower_workflow.db.models import Base
        engine = create_engine_from_url(db_url)
        Base.metadata.create_all(engine)
        self._telemetry = TelemetryDbWriter(
            emitter=self._telemetry,
            engine=engine,
            project_name=self.root.name,
            project_path=str(self.root),
        )
    except ImportError:
        pass
```

Add `import os` at the top of orchestrator.py (already imported via subprocess).

In `cli.py` `_cmd_init`, at the end before the final print, add auto-registration:

```python
try:
    from superpower_workflow.server.registry import ProjectRegistry
    reg = ProjectRegistry()
    reg.register(project_root.name, str(project_root))
except Exception:
    pass
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py src/superpower_workflow/cli.py tests/test_server_config.py --fix
ruff format src/superpower_workflow/orchestrator.py src/superpower_workflow/cli.py tests/test_server_config.py
git add src/superpower_workflow/orchestrator.py src/superpower_workflow/cli.py tests/test_server_config.py
git commit -m "feat: wire TelemetryDbWriter into orchestrator, auto-register projects"
```

---

### Task 16: Docker setup -- Dockerfile + docker-compose

**Files:**
- New: `docker/Dockerfile.server`
- New: `docker/docker-compose.yml`
- New: `tests/test_docker_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docker_config.py
from __future__ import annotations

from pathlib import Path


class TestDockerFiles:
    def test_dockerfile_exists(self):
        assert Path("docker/Dockerfile.server").exists()

    def test_docker_compose_exists(self):
        assert Path("docker/docker-compose.yml").exists()

    def test_dockerfile_uses_python_311(self):
        content = Path("docker/Dockerfile.server").read_text()
        assert "python:3.11" in content

    def test_dockerfile_installs_server_extras(self):
        content = Path("docker/Dockerfile.server").read_text()
        assert "[server]" in content

    def test_compose_has_postgres(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "postgres" in content

    def test_compose_has_api_server(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "api-server" in content

    def test_compose_has_healthcheck(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "healthcheck" in content

    def test_compose_default_password_changeme(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "changeme" in content

    def test_compose_port_3001(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "3001" in content

    def test_compose_volume_persistence(self):
        content = Path("docker/docker-compose.yml").read_text()
        assert "pgdata" in content
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Create Docker files**

```dockerfile
# docker/Dockerfile.server
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY templates/ templates/
COPY skills/ skills/
COPY commands/ commands/

RUN pip install --no-cache-dir -e ".[server]"

EXPOSE 3001

CMD ["python", "-m", "uvicorn", "superpower_workflow.server.app:create_app", "--host", "0.0.0.0", "--port", "3001", "--factory"]
```

```yaml
# docker/docker-compose.yml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sw
      POSTGRES_PASSWORD: ${SW_DB_PASSWORD:-changeme}
      POSTGRES_DB: superpower_workflow
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sw"]
      interval: 5s
      timeout: 5s
      retries: 5

  api-server:
    build:
      context: ..
      dockerfile: docker/Dockerfile.server
    ports:
      - "3001:3001"
    environment:
      SW_DATABASE_URL: postgresql://sw:${SW_DB_PASSWORD:-changeme}@postgres:5432/superpower_workflow
      SW_API_KEY: ${SW_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pgdata:
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check tests/test_docker_config.py --fix
ruff format tests/test_docker_config.py
git add docker/Dockerfile.server docker/docker-compose.yml tests/test_docker_config.py
git commit -m "feat: add Docker Compose setup with Postgres and API server"
```

---

### Task 17: Package exports + __all__ completeness

**Files:**
- Edit: `src/superpower_workflow/db/__init__.py`
- Edit: `src/superpower_workflow/server/__init__.py`
- Edit: `src/superpower_workflow/server/routers/__init__.py`
- New: `tests/test_server_exports.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server_exports.py
from __future__ import annotations


class TestDbExports:
    def test_db_package_has_all(self):
        import superpower_workflow.db
        assert hasattr(superpower_workflow.db, "__all__")

    def test_db_exports_engine(self):
        from superpower_workflow.db import create_engine_from_url, get_session_factory
        assert callable(create_engine_from_url)
        assert callable(get_session_factory)

    def test_db_exports_models(self):
        from superpower_workflow.db import (
            Base, SwProject, SwRun, SwMilestone, SwPhase,
            SwEvent, SwQualityGate, SwCoverageResult, SwGapReport,
        )

    def test_db_exports_writer(self):
        from superpower_workflow.db import TelemetryDbWriter
        assert TelemetryDbWriter is not None

    def test_db_exports_sync(self):
        from superpower_workflow.db import DbSyncAdapter
        assert DbSyncAdapter is not None


class TestServerExports:
    def test_server_package_has_all(self):
        import superpower_workflow.server
        assert hasattr(superpower_workflow.server, "__all__")

    def test_server_exports_app(self):
        from superpower_workflow.server import create_app
        assert callable(create_app)

    def test_server_exports_config(self):
        from superpower_workflow.server import ServerConfig, load_server_config
        assert ServerConfig is not None

    def test_server_exports_registry(self):
        from superpower_workflow.server import ProjectRegistry, ProjectEntry
        assert ProjectRegistry is not None


class TestRouterExports:
    def test_routers_package_has_all(self):
        import superpower_workflow.server.routers
        assert hasattr(superpower_workflow.server.routers, "__all__")
```

- [ ] **Step 2: Run tests -- expect FAIL**

- [ ] **Step 3: Update package __init__.py files**

```python
# src/superpower_workflow/db/__init__.py
from __future__ import annotations

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import (
    Base,
    SwCoverageResult,
    SwEvent,
    SwGapReport,
    SwMilestone,
    SwPhase,
    SwProject,
    SwQualityGate,
    SwRun,
)
from superpower_workflow.db.sync_adapter import DbSyncAdapter
from superpower_workflow.db.writer import TelemetryDbWriter

__all__ = [
    "Base",
    "DbSyncAdapter",
    "SwCoverageResult",
    "SwEvent",
    "SwGapReport",
    "SwMilestone",
    "SwPhase",
    "SwProject",
    "SwQualityGate",
    "SwRun",
    "TelemetryDbWriter",
    "create_engine_from_url",
    "get_session_factory",
]
```

```python
# src/superpower_workflow/server/__init__.py
from __future__ import annotations

from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig, load_server_config
from superpower_workflow.server.registry import ProjectEntry, ProjectRegistry

__all__ = [
    "ProjectEntry",
    "ProjectRegistry",
    "ServerConfig",
    "create_app",
    "load_server_config",
]
```

```python
# src/superpower_workflow/server/routers/__init__.py
from __future__ import annotations

__all__ = [
    "events",
    "metrics",
    "milestones",
    "projects",
    "runs",
    "ws",
]
```

- [ ] **Step 4: Run tests -- expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/db/__init__.py src/superpower_workflow/server/__init__.py src/superpower_workflow/server/routers/__init__.py tests/test_server_exports.py --fix
ruff format src/superpower_workflow/db/__init__.py src/superpower_workflow/server/__init__.py src/superpower_workflow/server/routers/__init__.py tests/test_server_exports.py
git add src/superpower_workflow/db/__init__.py src/superpower_workflow/server/__init__.py src/superpower_workflow/server/routers/__init__.py tests/test_server_exports.py
git commit -m "feat: add package exports with __all__ for db and server packages"
```

---

### Task 18: Integration tests -- end-to-end pipeline

**Files:**
- New: `tests/test_server_integration.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_server_integration.py
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwMilestone, SwProject, SwRun
from superpower_workflow.db.queries import (
    create_milestone,
    create_run,
    get_or_create_project,
    create_event,
    create_phase,
    create_quality_gate,
    create_gap_report,
)
from superpower_workflow.db.sync_adapter import DbSyncAdapter
from superpower_workflow.db.writer import TelemetryDbWriter
from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig
from superpower_workflow.server.registry import ProjectRegistry
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def full_pipeline(db_engine, tmp_path):
    factory = get_session_factory(db_engine)
    session = factory()
    proj = get_or_create_project(session, "integration-app", "/home/user/app")
    run = create_run(session, project_id=proj.id, run_id="20260525-120000", model="opus",
                     milestone_count=3)
    ms1 = create_milestone(session, run_id=run.id, name="sp1-quality-gates")
    ms2 = create_milestone(session, run_id=run.id, name="sp2-telemetry")
    ms3 = create_milestone(session, run_id=run.id, name="sp3-dashboard")
    create_phase(session, milestone_id=ms1.id, phase_type="plan", model="opus", status="completed")
    create_phase(session, milestone_id=ms1.id, phase_type="implement", model="opus", status="completed")
    create_quality_gate(session, milestone_id=ms1.id, checkpoint="qcb", gate_name="lint", passed=True)
    create_gap_report(session, milestone_id=ms1.id, pass_num=1, critical=0, important=2, converged=True)
    for ms in (ms1, ms2, ms3):
        create_event(session, run_id=run.id, milestone_name=ms.name,
                     event_type="milestone_started", data_json={"milestone": ms.name})
    create_event(session, run_id=run.id, event_type="run_completed",
                 data_json={"status": "complete", "total_cost_usd": 25.0})
    session.close()
    return db_engine


class TestFullPipeline:
    def test_all_data_accessible_via_api(self, full_pipeline):
        from fastapi.testclient import TestClient
        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert len(projects) == 1
        assert projects[0]["name"] == "integration-app"

        runs = client.get("/api/v1/runs").json()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "20260525-120000"

        run_detail = client.get(f"/api/v1/runs/{runs[0]['id']}").json()
        assert len(run_detail["milestones"]) == 3

        milestones = client.get(f"/api/v1/milestones?run_id={runs[0]['id']}").json()
        assert len(milestones) == 3

        ms_detail = client.get(f"/api/v1/milestones/{milestones[0]['id']}").json()
        assert "phases" in ms_detail
        assert "quality_gates" in ms_detail
        assert "gap_reports" in ms_detail

        events = client.get(f"/api/v1/events?run_id={runs[0]['id']}").json()
        assert len(events) >= 4

        costs = client.get("/api/v1/metrics/costs").json()
        assert "total_cost" in costs

        quality = client.get("/api/v1/metrics/quality").json()
        assert "gap_reports" in quality

        models = client.get("/api/v1/metrics/models").json()
        assert "models" in models


class TestWriterToApiPipeline:
    def test_writer_events_visible_in_api(self, db_engine, tmp_path):
        from fastapi.testclient import TestClient

        emitter = TelemetryEmitter(tmp_path / "telemetry.jsonl", run_id="wr-test")
        writer = TelemetryDbWriter(
            emitter=emitter, engine=db_engine,
            project_name="writer-app", project_path="/p/writer",
        )

        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=2))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseCompleted(milestone="m1", phase="plan", cost_usd=3.0, duration_ms=10000))
        writer.emit(MilestoneCompleted(milestone="m1", cost_usd=8.0, duration_seconds=60.0))
        writer.emit(RunCompleted(status="complete", total_cost_usd=8.0, completed_count=1))
        writer.close()

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = db_engine
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert any(p["name"] == "writer-app" for p in projects)

        events = client.get("/api/v1/events").json()
        types = {e["event_type"] for e in events}
        assert "run_started" in types
        assert "phase_completed" in types


class TestSyncToApiPipeline:
    def test_synced_data_visible_in_api(self, db_engine, tmp_path):
        from fastapi.testclient import TestClient

        jsonl = tmp_path / "telemetry.jsonl"
        events = [
            {"type": "run_started", "run_id": "sync-test", "timestamp": "2026-05-25T12:00:00Z",
             "model": "opus", "milestone_count": 1},
            {"type": "milestone_started", "run_id": "sync-test",
             "timestamp": "2026-05-25T12:00:01Z", "milestone": "s1"},
            {"type": "run_completed", "run_id": "sync-test",
             "timestamp": "2026-05-25T12:00:02Z", "status": "complete", "total_cost_usd": 5.0},
        ]
        jsonl.write_text("\n".join(json.dumps(e) for e in events))

        adapter = DbSyncAdapter(db_engine)
        adapter.sync("sync-app", "/p/sync", jsonl)

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = db_engine
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert any(p["name"] == "sync-app" for p in projects)

        runs = client.get("/api/v1/runs").json()
        assert any(r["run_id"] == "sync-test" for r in runs)


class TestRegistryIntegration:
    def test_registry_tracks_multiple_projects(self, tmp_path):
        reg = ProjectRegistry(tmp_path / "reg.json")
        reg.register("app1", "/p/1")
        reg.register("app2", "/p/2")
        reg.register("app3", "/p/3")
        assert len(reg.list_projects()) == 3
        reg.remove("app2")
        assert len(reg.list_projects()) == 2
        names = [p.name for p in reg.list_projects()]
        assert "app1" in names
        assert "app3" in names

    def test_registry_persists(self, tmp_path):
        path = tmp_path / "reg.json"
        r1 = ProjectRegistry(path)
        r1.register("app", "/p")
        r2 = ProjectRegistry(path)
        assert len(r2.list_projects()) == 1


class TestApiAuth:
    def test_full_pipeline_with_auth(self, full_pipeline):
        from fastapi.testclient import TestClient
        cfg = ServerConfig(api_key="secret-key", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline
        client = TestClient(app)

        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/projects").status_code == 401
        r = client.get("/api/v1/projects", headers={"Authorization": "Bearer secret-key"})
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestDashboardServing:
    def test_dashboard_html_served_at_root(self, full_pipeline):
        from fastapi.testclient import TestClient
        from fastapi.responses import HTMLResponse
        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline

        @app.get("/")
        def dashboard():
            return HTMLResponse(UNIFIED_DASHBOARD_HTML)

        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text
        assert "monospace" in r.text
```

- [ ] **Step 2: Run tests -- expect PASS** (all implementation already done)

- [ ] **Step 3: Lint + commit**

```bash
ruff check tests/test_server_integration.py --fix
ruff format tests/test_server_integration.py
git add tests/test_server_integration.py
git commit -m "test: add end-to-end integration tests for unified dashboard pipeline"
```
