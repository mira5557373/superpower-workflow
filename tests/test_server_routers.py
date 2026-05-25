from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import Base
from superpower_workflow.db.queries import create_milestone, create_run, get_or_create_project
from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def seeded_engine(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    proj = get_or_create_project(session, "test-app", "/home/user/test-app")
    run = create_run(
        session,
        project_id=proj.id,
        run_id="20260525-120000",
        model="opus",
        milestone_count=3,
    )
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
